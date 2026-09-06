"""
FastAPI wrapper for ERP Orchestrator with hybrid LLM support (Gemini + GPT-4 fallback)
"""
import time
import uuid as uuid_lib
import sys
import json

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List, Dict
from pathlib import Path
import os
import uvicorn
import structlog

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.orchestrator import orchestrator
from src.config.settings import settings
import src.utils.llm as llm_mod
from src.agents import requirements_agent, training_agent
from src.memory import agent_memory
from src.tools.info_retriever import info_retriever
from src.utils.logger import get_logger
from src.utils.prompts import get_synthesis_prompt
from src.models.chat_intent_schema import ChatIntent, ChatIntentDecision
from src.auth.dependencies import get_current_user, get_db
from src.auth.schemas import SignupRequest, LoginRequest, TokenResponse, UserOut
from src.auth.security import create_access_token
from src.auth import service as auth_service
from src.db.base import engine as db_engine
from src.db.models import User, Feedback

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.init_directories()
    yield

app = FastAPI(title="ERP Orchestrator API", lifespan=lifespan)

logger = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Auth endpoints get their own (stricter) limits since brute-forcing
# passwords is the main threat there. Effectively disabled under pytest -
# TestClient shares one fake IP across every test, so a real per-minute
# limit would fail unrelated tests depending on run order, not because of
# a real vulnerability. Real requests never carry PYTEST_CURRENT_TEST.
_TESTING = "pytest" in sys.modules
AUTH_RATE_LIMIT = "10000/minute" if _TESTING else "5/minute"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Every request gets a correlation ID: generated if the caller didn't
    send one, echoed back on X-Request-ID, and bound into every structlog
    line emitted while handling this request (via contextvars, already wired
    into the logger's processor chain - see src/utils/logger.py) so a
    support request referencing an ID can be grepped straight out of logs."""
    request_id = request.headers.get("X-Request-ID", str(uuid_lib.uuid4()))
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)

    response.headers["X-Request-ID"] = request_id
    logger.info("Request completed", path=request.url.path, method=request.method,
                status_code=response.status_code, duration_ms=duration_ms)
    return response


def _error_envelope(request: Request, status_code: int, message: str) -> Dict:
    return {
        "error": {
            "code": status_code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Consistent JSON error shape for every HTTPException raised anywhere
    in the app, instead of each endpoint's raise producing a differently
    shaped body. detail is still whatever the endpoint set - only the
    envelope around it is standardized."""
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope(request, exc.status_code, str(exc.detail)),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler for anything that isn't an HTTPException - an
    unexpected bug, a third-party library error, etc. Logs the real
    exception (with traceback) server-side, keyed by request_id, but the
    client only ever sees a generic message - never a stack trace, a file
    path, or an internal error string."""
    logger.error("Unhandled exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content=_error_envelope(request, 500, "Internal server error. If this persists, "
                                              "please contact support with the request ID above."),
    )


app.mount("/ui", StaticFiles(directory="ui"), name="ui")


class ProjectStart(BaseModel):
    project_name: str
    module: str
    erp_system: Optional[str] = "SAP S/4HANA"
    initial_input: Optional[str] = None


class ProjectRename(BaseModel):
    project_name: str


class FeedbackRequest(BaseModel):
    session_id: Optional[str] = None
    rating: Optional[int] = None
    comment: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    agent_hint: Optional[str] = None
    prefer_web: Optional[bool] = False


def extract_text(response) -> str:
    """Normalize any LLM response to a string for frontend display."""
    if response is None:
        return "No response from LLM."
    if hasattr(response, "text"):
        return response.text
    if isinstance(response, dict):
        for key in ("text", "output_text", "answer"):
            if key in response:
                return str(response[key])
        return str(response)
    if isinstance(response, str):
        return response
    return str(response)


def _get_owned_session(session_id: str, current_user: User):
    """Fetch a session and verify it belongs to current_user. Sessions
    created before per-user auth existed (user_id is None) are treated as
    not owned by anyone and are therefore inaccessible via the API - not
    silently reassigned to whichever user happens to ask first. Returns
    404 (never 403) for both "doesn't exist" and "not yours", so the API
    never confirms a session ID exists to someone who doesn't own it."""
    session = agent_memory.session_service.get_session(session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/auth/signup", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
def signup(request: Request, req: SignupRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.create_user(db, req.email, req.password)
    except auth_service.EmailAlreadyRegistered:
        raise HTTPException(status_code=409, detail="Email already registered")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in_minutes=settings.access_token_expire_minutes)


@app.post("/api/auth/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    user = auth_service.authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, expires_in_minutes=settings.access_token_expire_minutes)


@app.get("/api/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness check: is the process up and able to respond at all. Does
    not touch the database or any external service - see /ready for that."""
    serpapi_installed = True
    try:
        import serpapi  # type: ignore
    except ImportError:
        serpapi_installed = False

    llm_instance = llm_mod.get_llm()
    llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

    return {
        "status": "ok",
        "llm_mode": llm_mode,
        "serpapi_installed": serpapi_installed,
        "gemini_key_present": bool(settings.gemini_api_key),
        "serpapi_key_present": bool(settings.serpapi_api_key)
    }


@app.get("/ready")
def ready():
    """Readiness check: can this instance actually serve traffic right now -
    specifically, is the database reachable. Distinct from /health because a
    process can be alive (health=ok) while its database connection is down,
    e.g. during a Postgres failover - a load balancer or orchestrator should
    stop routing traffic in that case, which /health alone can't signal."""
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        raise HTTPException(status_code=503, detail="Database is not reachable")

    return {"status": "ready"}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def list_projects(include_archived: bool = False, current_user: User = Depends(get_current_user)):
    """List the current user's projects, most recently updated first.
    Archived projects are hidden unless include_archived=true."""
    session_ids = agent_memory.session_service.list_sessions_for_user(
        current_user.id, include_archived=include_archived
    )
    summaries = [agent_memory.session_service.get_session_summary(sid) for sid in session_ids]
    return {"projects": [s for s in summaries if s]}


@app.post("/api/projects/start")
def start_project(req: ProjectStart, current_user: User = Depends(get_current_user)):
    result = orchestrator.start_project(
        project_name=req.project_name,
        module=req.module,
        erp_system=req.erp_system,
        initial_input=req.initial_input,
        user_id=current_user.id
    )
    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error', 'Unknown error'))
    return result


@app.patch("/api/projects/{session_id}")
def rename_project(session_id: str, req: ProjectRename, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    session = agent_memory.session_service.rename_session(session_id, req.project_name)
    return {"session_id": session_id, "project_name": session.project_name}


@app.delete("/api/projects/{session_id}")
def archive_project(session_id: str, current_user: User = Depends(get_current_user)):
    """Archives (soft-deletes) a conversation - hides it from the default
    list without destroying the underlying data. There is currently no
    unarchive/restore endpoint; add one if that turns out to be needed."""
    _get_owned_session(session_id, current_user)
    archived = agent_memory.session_service.archive_session(session_id)
    if not archived:
        raise HTTPException(status_code=409, detail="Project is already archived")
    return {"session_id": session_id, "archived": True}


@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest, current_user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    if req.session_id:
        _get_owned_session(req.session_id, current_user)
    if req.rating is not None and not (1 <= req.rating <= 5):
        raise HTTPException(status_code=422, detail="rating must be between 1 and 5")

    feedback = Feedback(
        id=uuid_lib.uuid4().hex,
        user_id=current_user.id,
        session_id=req.session_id,
        rating=req.rating,
        comment=req.comment,
    )
    db.add(feedback)
    db.commit()
    return {"success": True, "feedback_id": feedback.id}


@app.post("/api/projects/{session_id}/phase/{phase_name}/execute")
def execute_phase(session_id: str, phase_name: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)

    phase_map = {
        'requirements': orchestrator.execute_requirements_phase,
        'process_mapping': orchestrator.execute_process_mapping_phase,
        'solution_design': orchestrator.execute_solution_design_phase,
        'qa_testing': orchestrator.execute_qa_testing_phase,
        'uat_testing': orchestrator.execute_uat_testing_phase,
        'training': orchestrator.execute_training_phase
    }

    if phase_name not in phase_map:
        raise HTTPException(status_code=400, detail=f"Unknown phase: {phase_name}")

    result = phase_map[phase_name](session_id=session_id)
    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error'))
    return result


@app.get("/api/projects/{session_id}/status")
def project_status(session_id: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    return orchestrator.get_project_status(session_id)


_PHASES_WITH_DOCUMENTS = [
    'requirements_gathering', 'process_mapping', 'solution_design',
    'qa_testing', 'uat_testing', 'training'
]


def _collect_session_documents(session_id: str) -> List[Dict[str, str]]:
    """Collect every generated document for a session, across all phases
    whose output included one. Most phases store a single 'document_path';
    training stores multiple named documents under 'documents'. Process
    mapping produces no downloadable document at all."""
    documents = []

    for phase in _PHASES_WITH_DOCUMENTS:
        output = agent_memory.get_phase_output(session_id, phase)
        if not output or not isinstance(output, dict):
            continue

        doc_path = output.get('document_path')
        if doc_path:
            documents.append({'phase': phase, 'label': phase, 'path': doc_path})

        for label, path in (output.get('documents') or {}).items():
            if path:
                documents.append({'phase': phase, 'label': label, 'path': path})

    return documents


@app.get("/api/projects/{session_id}/documents")
def list_documents(session_id: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)

    docs = _collect_session_documents(session_id)
    return {
        'session_id': session_id,
        'documents': [
            {'phase': d['phase'], 'label': d['label'], 'filename': os.path.basename(d['path'])}
            for d in docs
        ]
    }


@app.get("/api/projects/{session_id}/documents/{filename}")
def download_document(session_id: str, filename: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)

    # Whitelist match only: the requested filename must exactly match the
    # basename of a document already known to belong to this session. The
    # client-supplied filename is never resolved against the filesystem
    # directly - only a server-known path is ever opened - so a crafted
    # filename like "../../etc/passwd" simply won't match anything and
    # fails with 404, regardless of what's requested.
    docs = _collect_session_documents(session_id)
    match = next((d for d in docs if os.path.basename(d['path']) == filename), None)
    if not match:
        raise HTTPException(status_code=404, detail="Document not found for this session")

    file_path = Path(match['path'])
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document file is missing on disk")

    return FileResponse(path=str(file_path), filename=file_path.name, media_type="text/markdown")


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def _chat_response(answer: str, llm_mode: str, success: bool = True, session_id: Optional[str] = None):
    return {
        'success': success,
        'answer': answer,
        'llm_mode': llm_mode,
        'session_id': session_id,
    }

def classify_intent(llm_instance, message: str, has_session: bool) -> ChatIntentDecision:
    """Classify the user's chat message into a known action. Falls back
    to ASK_QUESTION on any failure - an unclear or misclassified message
    should never accidentally trigger a workflow action. Takes the
    already-resolved llm_instance rather than fetching its own, so a
    single chat request only ever resolves the LLM client once."""
    prompt = f"""Classify this user message into exactly one intent.

Message: "{message}"
User currently has an active project session: {has_session}

Intents:
- start_project: user explicitly wants to begin a new ERP project (e.g. "start a new project called X", "let's begin implementation for Y"). If they mention a specific ERP system (SAP, Oracle, Dynamics 365, NetSuite, Odoo, Infor, Workday) or module (e.g. FI, MM, SD, HCM, financials), extract them into module/erp_system. Leave them unset if not mentioned.
- run_phase: user explicitly wants to execute a specific workflow phase on their CURRENT project. Only valid if a session already exists. Phase must be one of: requirements, process_mapping, solution_design, qa_testing, uat_testing, training
- generate_training: user explicitly wants training materials or a user guide generated as a document
- ask_question: anything else - general questions, discussion, or requests for information, even if they mention topics like "training" or "requirements" without asking to generate or run something

Default to ask_question whenever the message is ambiguous, conversational, or informational rather than a direct command."""

    try:
        response = llm_instance.generate_content(
            prompt,
            generation_config={'response_schema': ChatIntentDecision, 'temperature': 0.0}
        )
        return ChatIntentDecision.model_validate_json(response.text)
    except Exception as e:
        logger.warning(f"Intent classification failed, defaulting to ask_question: {e}")
        return ChatIntentDecision(intent=ChatIntent.ASK_QUESTION)

@app.post("/api/chat")
def chat(req: ChatRequest, current_user: User = Depends(get_current_user)):
    logger.info({"event": "Chat request received", "message": req.message, "session_id": req.session_id})

    # A session_id in the request must belong to this user - checked once,
    # up front, so every branch below can trust req.session_id is theirs.
    if req.session_id:
        _get_owned_session(req.session_id, current_user)

    llm_instance = llm_mod.get_llm()
    llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

    # Explicit agent_hint always wins - it's a direct instruction from the
    # caller, not something that needs classifying
    if req.agent_hint and req.session_id:
        if req.agent_hint.lower() == 'requirements':
            session = agent_memory.session_service.get_session(req.session_id)
            if not session:
                return _chat_response("Session not found.", llm_mode=llm_mode, success=False)
            res = requirements_agent.gather_requirements(
                session_id=req.session_id,
                project_name=session.project_name,
                module=session.module,
                stakeholder_input=req.message,
                erp_system=session.erp_system
            )
            summary = res.get('requirements', {}).get('executive_summary', 'No summary available.')
            return _chat_response(f"Requirements gathered: {summary}", llm_mode=llm_mode)

    decision = classify_intent(llm_instance, req.message, has_session=bool(req.session_id))
    logger.info({"event": "Intent classified", "intent": decision.intent.value})

    if decision.intent == ChatIntent.START_PROJECT:
        project_name = decision.project_name or 'Chat Project'
        module = decision.module or 'FI'
        erp_system = decision.erp_system or 'SAP S/4HANA'
        res = orchestrator.start_project(project_name, module, erp_system=erp_system, initial_input=None,
                                          user_id=current_user.id)
        if res.get('success'):
            return _chat_response(f"Project '{project_name}' started ({module} / {erp_system}). You can now ask me to gather requirements, run a phase, or ask any question about it.",
                                  llm_mode=llm_mode, session_id=res.get('session_id'))
        else:
            return _chat_response(f"Failed to start project: {res.get('error', 'Unknown error')}",
                                  llm_mode=llm_mode, success=False)

    if decision.intent == ChatIntent.RUN_PHASE:
        if not req.session_id:
            return _chat_response("session_id is required to run a phase.", llm_mode=llm_mode, success=False)

        phase_map = {
            'requirements': orchestrator.execute_requirements_phase,
            'process_mapping': orchestrator.execute_process_mapping_phase,
            'solution_design': orchestrator.execute_solution_design_phase,
            'qa_testing': orchestrator.execute_qa_testing_phase,
            'uat_testing': orchestrator.execute_uat_testing_phase,
            'training': orchestrator.execute_training_phase
        }
        if decision.phase not in phase_map:
            return _chat_response("Could not determine which phase to run.", llm_mode=llm_mode, success=False)

        result = phase_map[decision.phase](session_id=req.session_id)
        if result.get('success'):
            return _chat_response(f"Phase '{decision.phase}' executed successfully.", llm_mode=llm_mode, session_id=req.session_id)
        else:
            return _chat_response(f"Failed to execute phase '{decision.phase}': {result.get('error', 'Unknown error')}",
                                  llm_mode=llm_mode, success=False, session_id=req.session_id)

    if decision.intent == ChatIntent.GENERATE_TRAINING and req.session_id is None:
        session_id = agent_memory.create_project(project_name='AP Invoice Posting', module='FI',
                                                  user_id=current_user.id)
        result = training_agent.create_training_materials(
            session_id=session_id,
            process_name='AP Invoice Posting',
            user_roles=['AP Clerk', 'Accounts Payable Supervisor', 'Finance Manager'],
            solution_design={}
        )
        if result.get('success'):
            return _chat_response("Training materials for 'AP Invoice Posting' have been generated.",
                                  llm_mode=llm_mode)
        else:
            return _chat_response("Failed to generate training materials.", llm_mode=llm_mode, success=False)

    # ASK_QUESTION (default) - info retrieval + LLM synthesis, with a
    # plain conversational fallback when there's nothing to retrieve
    # (e.g. "thanks", small talk) rather than a robotic error string
    data = info_retriever(req.message, {'summary': ''}, prefer_web=req.prefer_web)
    generation_config = {
        'temperature': 0.5,
        'max_output_tokens': 2048,
    }

    if data and (data.get('kb_results') or data.get('web_results') or data.get('sources')):
        prompt = get_synthesis_prompt(req.message, data)
    else:
        prompt = f'Respond naturally and briefly, as a helpful ERP consulting assistant, to this message: "{req.message}"'

    try:
        response = llm_instance.generate_content(prompt, generation_config=generation_config)
        final_answer = extract_text(response)
    except Exception as e:
        logger.error(f"Error during final answer synthesis: {e}")
        final_answer = "I found some information, but I had trouble summarizing it."

    logger.info({"event": "Chat response ready", "session_id": req.session_id})
    return _chat_response(final_answer, llm_mode=llm_mode, session_id=req.session_id)


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event. Every event carries a JSON `data` line -
    even short ones - so the frontend has one consistent parse path
    regardless of event type."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_chat_events(req: ChatRequest, current_user: User, request_id: Optional[str]):
    """Generator of SSE-formatted events for one chat turn. Mirrors chat()'s
    branching exactly (same intents, same agent calls) but emits progress
    events around each step instead of returning a single JSON blob at the
    end - this is what actually addresses the spec's "don't show an empty
    screen while the backend works" requirement for multi-second/multi-phase
    operations. Internal reasoning (prompts, raw LLM chain-of-thought) is
    never emitted - only short, user-safe status strings, exactly like the
    "agent activity" UI the roadmap describes.

    Ownership of req.session_id is verified by the caller (the endpoint
    function) before this generator is even constructed, so every branch
    here can trust it - same pattern as chat() itself.
    """
    def ev(event_type, **data):
        if request_id:
            data['request_id'] = request_id
        return _sse(event_type, data)

    try:
        yield ev('message_start', session_id=req.session_id)

        llm_instance = llm_mod.get_llm()
        llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

        if req.agent_hint and req.session_id and req.agent_hint.lower() == 'requirements':
            yield ev('agent_started', agent='requirements', message='Gathering requirements')
            session = agent_memory.session_service.get_session(req.session_id)
            if not session:
                yield ev('error', message='Session not found.')
                return
            res = requirements_agent.gather_requirements(
                session_id=req.session_id, project_name=session.project_name,
                module=session.module, stakeholder_input=req.message, erp_system=session.erp_system
            )
            summary = res.get('requirements', {}).get('executive_summary', 'No summary available.')
            answer = f"Requirements gathered: {summary}"
            yield ev('agent_progress', agent='requirements', message='Requirements captured')
            yield ev('text_delta', text=answer)
            yield ev('workflow_completed')
            yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=req.session_id)
            return

        yield ev('agent_started', agent='router', message='Understanding your request')
        decision = classify_intent(llm_instance, req.message, has_session=bool(req.session_id))
        logger.info({"event": "Intent classified", "intent": decision.intent.value})

        if decision.intent == ChatIntent.START_PROJECT:
            project_name = decision.project_name or 'Chat Project'
            module = decision.module or 'FI'
            erp_system = decision.erp_system or 'SAP S/4HANA'
            yield ev('agent_started', agent='orchestrator', message=f"Starting project '{project_name}'")
            res = orchestrator.start_project(project_name, module, erp_system=erp_system,
                                              initial_input=None, user_id=current_user.id)
            if res.get('success'):
                answer = (f"Project '{project_name}' started ({module} / {erp_system}). "
                          f"You can now ask me to gather requirements, run a phase, or ask any question about it.")
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=res.get('session_id'))
            else:
                yield ev('error', message=f"Failed to start project: {res.get('error', 'Unknown error')}")
            return

        if decision.intent == ChatIntent.RUN_PHASE:
            if not req.session_id:
                yield ev('error', message='session_id is required to run a phase.')
                return

            phase_map = {
                'requirements': orchestrator.execute_requirements_phase,
                'process_mapping': orchestrator.execute_process_mapping_phase,
                'solution_design': orchestrator.execute_solution_design_phase,
                'qa_testing': orchestrator.execute_qa_testing_phase,
                'uat_testing': orchestrator.execute_uat_testing_phase,
                'training': orchestrator.execute_training_phase
            }
            if decision.phase not in phase_map:
                yield ev('error', message='Could not determine which phase to run.')
                return

            yield ev('agent_started', agent=decision.phase, message=f"Running {decision.phase.replace('_', ' ')} phase")
            result = phase_map[decision.phase](session_id=req.session_id)
            if result.get('success'):
                doc_path = result.get('document_path')
                if doc_path:
                    yield ev('document_created', phase=decision.phase, filename=os.path.basename(doc_path))
                answer = f"Phase '{decision.phase}' executed successfully."
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=req.session_id)
            else:
                yield ev('error', message=f"Failed to execute phase '{decision.phase}': {result.get('error', 'Unknown error')}")
            return

        if decision.intent == ChatIntent.GENERATE_TRAINING and req.session_id is None:
            yield ev('agent_started', agent='training', message='Generating training materials')
            session_id = agent_memory.create_project(project_name='AP Invoice Posting', module='FI',
                                                      user_id=current_user.id)
            result = training_agent.create_training_materials(
                session_id=session_id, process_name='AP Invoice Posting',
                user_roles=['AP Clerk', 'Accounts Payable Supervisor', 'Finance Manager'],
                solution_design={}
            )
            if result.get('success'):
                for label, path in (result.get('documents') or {}).items():
                    if path:
                        yield ev('document_created', phase='training', label=label, filename=os.path.basename(path))
                answer = "Training materials for 'AP Invoice Posting' have been generated."
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=session_id)
            else:
                yield ev('error', message='Failed to generate training materials.')
            return

        # ASK_QUESTION (default) - this is the one branch where token-level
        # streaming actually happens, since it's the only path whose LLM
        # call produces free-form prose rather than a short fixed
        # confirmation string.
        yield ev('tool_started', tool='info_retriever', message='Searching knowledge base and web')
        data = info_retriever(req.message, {'summary': ''}, prefer_web=req.prefer_web)
        yield ev('tool_completed', tool='info_retriever')

        generation_config = {'temperature': 0.5, 'max_output_tokens': 2048}
        if data and (data.get('kb_results') or data.get('web_results') or data.get('sources')):
            prompt = get_synthesis_prompt(req.message, data)
        else:
            prompt = f'Respond naturally and briefly, as a helpful ERP consulting assistant, to this message: "{req.message}"'

        yield ev('agent_started', agent='synthesis', message='Preparing your answer')
        full_answer_parts = []
        try:
            if hasattr(llm_instance, 'generate_content_stream'):
                for chunk in llm_instance.generate_content_stream(prompt, generation_config=generation_config):
                    full_answer_parts.append(chunk)
                    yield ev('text_delta', text=chunk)
            else:
                response = llm_instance.generate_content(prompt, generation_config=generation_config)
                text = extract_text(response)
                full_answer_parts.append(text)
                yield ev('text_delta', text=text)
        except Exception as e:
            logger.error(f"Error during streamed answer synthesis: {e}")
            if not full_answer_parts:
                fallback = "I found some information, but I had trouble summarizing it."
                full_answer_parts.append(fallback)
                yield ev('text_delta', text=fallback)
            # else: a partial answer already reached the client - see the
            # docstring on generate_content_stream for why this can't
            # transparently retry on another tier mid-stream.

        final_answer = "".join(full_answer_parts)
        logger.info({"event": "Chat response ready", "session_id": req.session_id})
        yield ev('workflow_completed')
        yield ev('message_complete', answer=final_answer, llm_mode=llm_mode, session_id=req.session_id)

    except Exception as e:
        logger.error("Unhandled error in chat stream", error=str(e), exc_info=True)
        yield ev('error', message='Internal server error while processing your message.')


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, request: Request, current_user: User = Depends(get_current_user)):
    """Server-Sent Events version of /api/chat. Same intents and same agent
    calls as /api/chat (which stays exactly as it was, for any client that
    prefers a single JSON response) - this just exposes the same work as a
    progressive event stream, per the roadmap's streaming-chat phase."""
    if req.session_id:
        _get_owned_session(req.session_id, current_user)

    request_id = getattr(request.state, "request_id", None)
    return StreamingResponse(
        _stream_chat_events(req, current_user, request_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
def get_ui():
    try:
        with open('ui/index.html', 'r', encoding='utf-8') as f:
            html = f.read()
        return HTMLResponse(content=html, status_code=200)
    except Exception:
        return HTMLResponse(content='<h3>ERP Orchestrator API</h3><p>Visit /docs for API.</p>', status_code=200)


def start_server(host: str = '127.0.0.1', port: int = 8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    start_server()
