"""
FastAPI wrapper for ERP Orchestrator with hybrid LLM support (Gemini + GPT-4 fallback)
"""
import time
import uuid as uuid_lib
import sys
import json

from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional, List, Dict, Any
from pathlib import Path
import os
import uvicorn
import structlog

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

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
from src.auth.schemas import (
    SignupRequest, LoginRequest, TokenResponse, UserOut,
    ProfileUpdateRequest, PasswordChangeRequest,
)
from src.auth.security import create_access_token
from src.auth import service as auth_service
from src.db.base import engine as db_engine
from src.db.models import User, Feedback, SessionRecord
from src.utils.model_selection import TaskCategory

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.init_directories()
    yield

app = FastAPI(title="ERP Orchestrator API", lifespan=lifespan)

logger = get_logger(__name__)

_TESTING = "pytest" in sys.modules
AUTH_RATE_LIMIT = "10000/minute" if _TESTING else "5/minute"
DEFAULT_RATE_LIMIT = "100000/minute" if _TESTING else "60/minute"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[DEFAULT_RATE_LIMIT],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
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
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope(request, exc.status_code, str(exc.detail)),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content=_error_envelope(request, 500, "Internal server error. If this persists, "
                                              "please contact support with the request ID above."),
    )


if os.path.isdir("frontend/dist/assets"):
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="frontend_assets")


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

def _derive_chat_title(message: str) -> str:
    words = message.strip().split()
    if not words:
        return "New chat"
    title = " ".join(words[:6])
    if len(title) > 60:
        title = title[:57].rstrip() + "..."
    return title[0].upper() + title[1:]

PHASE_ORDER = ['requirements_gathering', 'process_mapping', 'solution_design', 'qa_testing', 'uat_testing', 'training', 'completed']

PHASE_LABELS = {
    'process_mapping': 'Map the business process',
    'solution_design': 'Design the ERP solution',
    'qa_testing': 'Generate QA test cases',
    'uat_testing': 'Prepare UAT scenarios',
    'training': 'Create training material',
}

# ---------------------------------------------------------------------------
# Requirements intake - plain per-session state (no LangGraph)
# ---------------------------------------------------------------------------
# Replaces the earlier LangGraph/checkpointer-based intake flow. Same
# observable behavior for the user: 4 fixed questions asked in order, then
# a generated stakeholder questionnaire template, then pasted stakeholder
# answers get structured into a formal requirements document. State now
# lives as plain data in session.metadata['intake'], scoped by session_id
# exactly like every other piece of per-session data in this app (there's
# no separate DB connection/pool/checkpointer to keep in sync with it,
# which is what caused the earlier intermittent bugs).

INTAKE_QUESTIONS = [
    {"key": "industry", "text": "What industry is the client in?"},
    {"key": "company_size", "text": "Roughly how large is the organization (employee count or revenue range)?"},
    {"key": "primary_goal", "text": "What's the primary business problem or goal driving this ERP initiative?"},
    {"key": "scope_areas", "text": "Which business areas are in scope for this phase (e.g. Finance, Supply Chain, HR)?"},
]

MIN_STAKEHOLDER_ANSWER_LENGTH = 40


def _get_intake_state(session) -> dict:
    """Reads the intake sub-state out of session.metadata, defaulting to
    a fresh not-started shape if this session has never begun intake."""
    metadata = session.metadata or {}
    return dict(metadata.get("intake") or {"stage": "not_started", "answers": {}})


def _save_intake_state(session_id: str, intake_state: dict) -> None:
    """Writes the intake sub-state back into session.metadata under the
    'intake' key, leaving every other metadata key (e.g.
    requirements_template_path) untouched."""
    session = agent_memory.session_service.get_session(session_id)
    metadata = dict(session.metadata or {})
    metadata["intake"] = intake_state
    agent_memory.session_service.update_session(session_id, {"metadata": metadata})


def _next_action_for(session) -> Optional[Dict[str, Any]]:
    """Deterministic suggestion for the next guided action in a structured
    project - drives the frontend's action buttons instead of relying on
    free-text intent classification, which proved unreliable for
    triggering phases. Returns None for casual chats (no guided workflow)
    and while mid-intake (the next question IS the response; no button
    needed until intake finishes)."""
    if session.is_casual:
        return None

    has_requirements = bool(agent_memory.get_phase_output(session.session_id, 'requirements_gathering'))

    if session.current_phase == 'requirements_gathering' and not has_requirements:
        if _intake_is_pending(session.session_id):
            return None
        if not _intake_is_complete(session.session_id):
            return {'label': 'Start requirements intake', 'agent_hint': 'start_intake'}
        return None

    if session.current_phase in PHASE_LABELS:
        return {'label': PHASE_LABELS[session.current_phase], 'agent_hint': session.current_phase}

    return None


def _intake_is_pending(session_id: str) -> bool:
    """True if this session has an intake in progress - either still
    collecting the 4 questions, or waiting on the pasted stakeholder
    answers."""
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        return False
    state = _get_intake_state(session)
    return state.get("stage") in ("collecting", "awaiting_stakeholder_answers")


def _intake_is_complete(session_id: str) -> bool:
    """True once intake has run all the way through to structured
    requirements being saved."""
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        return False
    state = _get_intake_state(session)
    return state.get("stage") == "complete"


def _run_intake_step(session_id: str, user_input: Optional[str], resume: bool) -> Dict[str, Any]:
    """Advances the intake flow by one step - either starting fresh
    (resume=False, asks question 1) or supplying the answer to whatever
    it's currently waiting on (resume=True). Returns a dict shaped like
    an agent phase result so callers can treat it uniformly, same as the
    old graph-backed version."""
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        return {'success': False, 'error': 'Session not found.'}

    if not resume:
        state = {"stage": "collecting", "answers": {}}
        _save_intake_state(session_id, state)
        return {'success': True, 'answer': INTAKE_QUESTIONS[0]['text']}

    state = _get_intake_state(session)
    stage = state.get("stage")

    if stage == "collecting":
        answers = dict(state.get("answers") or {})
        pending_question = next((q for q in INTAKE_QUESTIONS if q["key"] not in answers), None)
        if pending_question is None:
            return {'success': False, 'error': 'Intake questions already answered; unexpected state.'}

        answers[pending_question["key"]] = user_input
        state["answers"] = answers

        next_question = next((q for q in INTAKE_QUESTIONS if q["key"] not in answers), None)
        if next_question is not None:
            _save_intake_state(session_id, state)
            return {'success': True, 'answer': next_question['text']}

        # All four questions answered - generate the stakeholder
        # questionnaire template.
        result = requirements_agent.generate_requirements_template(
            project_name=session.project_name,
            module=session.module,
            erp_system=session.erp_system,
            context=answers,
            session_id=session_id
        )
        if not result.get("success"):
            return {'success': False, 'error': result.get('error', 'Failed to generate requirements template')}

        state["stage"] = "awaiting_stakeholder_answers"
        _save_intake_state(session_id, state)
        return {
            'success': True,
            'answer': ("Thanks - I've put together a requirements questionnaire based on your answers. "
                       "Download it, work through it with your stakeholders, then come back and paste "
                       "their answers in so I can turn them into a formal requirements document."),
            'document_path': result['document_path'],
        }

    if stage == "awaiting_stakeholder_answers":
        if not user_input or len(user_input.strip()) < MIN_STAKEHOLDER_ANSWER_LENGTH:
            return {
                'success': True,
                'answer': "I don't see enough stakeholder input to work with yet. Please paste the "
                          "completed questionnaire answers as a message, and I'll take it from there.",
            }

        result = requirements_agent.gather_requirements(
            session_id=session_id,
            project_name=session.project_name,
            module=session.module,
            stakeholder_input=user_input,
            erp_system=session.erp_system,
        )
        if not result.get("success"):
            return {'success': False, 'error': result.get('error', 'Failed to structure requirements')}

        agent_memory.advance_phase(session_id, "process_mapping")
        state["stage"] = "complete"
        _save_intake_state(session_id, state)
        summary = result.get('requirements', {}).get('executive_summary', 'Requirements captured.')
        return {
            'success': True,
            'answer': f"Requirements structured and saved: {summary}",
            'document_path': result.get('document_path'),
        }

    return {'success': False, 'error': f"Intake already complete or in an unexpected stage: {stage}"}


def _get_owned_session(session_id: str, current_user: User):
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


@app.get("/api/auth/settings", response_model=UserOut)
def account_settings(current_user: User = Depends(get_current_user)):
    return current_user


@app.patch("/api/auth/settings", response_model=UserOut)
def update_account_settings(req: ProfileUpdateRequest,
                            current_user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    return auth_service.update_profile(db, current_user, req.name, current_user.profile_picture_url)


@app.post("/api/auth/profile-picture", response_model=UserOut)
def upload_profile_picture(file: UploadFile = File(...),
                           current_user: User = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    if file.content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        raise HTTPException(status_code=415, detail="Profile picture must be a supported image")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        raise HTTPException(status_code=415, detail="Profile picture must be a supported image")

    picture_dir = Path(settings.output_dir) / "profile_pictures"
    picture_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid_lib.uuid4().hex}{suffix}"
    picture_path = picture_dir / filename
    with picture_path.open("wb") as destination:
        destination.write(file.file.read())

    return auth_service.update_profile(
        db, current_user, current_user.name, f"/api/auth/profile-picture/{filename}"
    )


@app.get("/api/auth/profile-picture/{filename}")
def get_profile_picture(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="Profile picture not found")
    picture_path = Path(settings.output_dir) / "profile_pictures" / filename
    if not picture_path.is_file():
        raise HTTPException(status_code=404, detail="Profile picture not found")
    return FileResponse(path=str(picture_path))


@app.post("/api/auth/password")
def change_account_password(req: PasswordChangeRequest,
                            current_user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    if not auth_service.change_password(db, current_user, req.current_password, req.new_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    return {"success": True}


@app.delete("/api/auth/account")
def delete_account(current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    owned_session_ids = agent_memory.session_service.list_sessions_for_user(current_user.id, include_archived=True)
    db.query(Feedback).filter(Feedback.user_id == current_user.id).delete(synchronize_session=False)
    db.query(SessionRecord).filter(SessionRecord.user_id == current_user.id).delete(synchronize_session=False)
    db.delete(current_user)
    db.commit()
    for session_id in owned_session_ids:
        agent_memory.session_service.sessions.pop(session_id, None)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
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
    session = agent_memory.session_service.get_session(result['session_id'])
    result['next_action'] = _next_action_for(session) if session else None
    return result


@app.patch("/api/projects/{session_id}")
def rename_project(session_id: str, req: ProjectRename, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    session = agent_memory.session_service.rename_session(session_id, req.project_name)
    return {"session_id": session_id, "project_name": session.project_name}


@app.delete("/api/projects/{session_id}")
def archive_project(session_id: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    archived = agent_memory.session_service.archive_session(session_id)
    if not archived:
        raise HTTPException(status_code=409, detail="Project is already archived")
    return {"session_id": session_id, "archived": True}


@app.delete("/api/projects/{session_id}/permanent")
def delete_project_permanently(session_id: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    deleted = agent_memory.session_service.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "deleted": True}


from src.services import project_intelligence


class ReviewActionRequest(BaseModel):
    object_type: str
    object_id: str
    action: str  # approved, rejected, corrected
    note: Optional[str] = None


@app.get("/api/projects/{session_id}/requirements")
def list_requirements(session_id: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    return {"session_id": session_id, "requirements": project_intelligence.get_requirements(session_id)}


@app.post("/api/projects/{session_id}/review")
def submit_review_action(session_id: str, req: ReviewActionRequest,
                          current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    action_id = project_intelligence.record_review_action(
        session_id, current_user.id, req.object_type, req.object_id, req.action, req.note
    )
    return {"action_id": action_id, "success": True}


@app.get("/api/projects/{session_id}/issues")
def list_issues(session_id: str, status: Optional[str] = "open",
                 current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    return {"session_id": session_id, "issues": project_intelligence.get_issues(session_id, status)}


@app.get("/api/projects/{session_id}/health")
def project_health(session_id: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)
    return project_intelligence.get_project_health(session_id)

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
    """Documents are stored durably in Postgres (GeneratedDocument), not
    local disk - see document_generator.py's _persist_to_db. Local disk
    is wiped on every Render redeploy/idle-restart, so it can never be
    the source of truth for downloads."""
    from src.db.base import SessionLocal
    from src.db.models import GeneratedDocument

    db = SessionLocal()
    try:
        records = db.query(GeneratedDocument).filter(GeneratedDocument.session_id == session_id).all()
        return [{'phase': r.phase, 'label': r.label, 'path': r.filename} for r in records]
    finally:
        db.close()


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

@app.get("/api/projects/{session_id}/messages")
def get_messages(session_id: str, current_user: User = Depends(get_current_user)):
    session = _get_owned_session(session_id, current_user)
    return {"session_id": session_id, "messages": session.conversation_history}

@app.get("/api/projects/{session_id}/documents/{filename}")
def download_document(session_id: str, filename: str, current_user: User = Depends(get_current_user)):
    _get_owned_session(session_id, current_user)

    from src.db.base import SessionLocal
    from src.db.models import GeneratedDocument
    from fastapi.responses import Response

    db = SessionLocal()
    try:
        record = db.query(GeneratedDocument).filter(
            GeneratedDocument.session_id == session_id,
            GeneratedDocument.filename == filename,
        ).first()
    finally:
        db.close()

    if not record:
        raise HTTPException(status_code=404, detail="Document not found for this session")

    return Response(
        content=record.content,
        media_type=record.content_type,
        headers={"Content-Disposition": f'attachment; filename="{record.filename}"'},
    )


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
            generation_config={
                'response_schema': ChatIntentDecision,
                'temperature': 0.0,
                'task': TaskCategory.LIGHTWEIGHT,
            }
        )
        return ChatIntentDecision.model_validate_json(response.text)
    except Exception as e:
        logger.warning(f"Intent classification failed, defaulting to ask_question: {e}")
        return ChatIntentDecision(intent=ChatIntent.ASK_QUESTION)

@app.post("/api/chat")
def chat(req: ChatRequest, current_user: User = Depends(get_current_user)):
    logger.info({"event": "Chat request received", "message": req.message, "session_id": req.session_id})

    if req.session_id:
        _get_owned_session(req.session_id, current_user)

    llm_instance = llm_mod.get_llm()
    llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

    if req.session_id and _intake_is_pending(req.session_id):
        res = _run_intake_step(req.session_id, req.message, resume=True)
        if not res.get('success'):
            return _chat_response(res.get('error', 'Intake failed.'), llm_mode=llm_mode,
                                  success=False, session_id=req.session_id)
        answer = res['answer']
        agent_memory.session_service.add_to_conversation(req.session_id, role="user", content=req.message)
        agent_memory.session_service.add_to_conversation(req.session_id, role="assistant", content=answer)
        return _chat_response(answer, llm_mode=llm_mode, session_id=req.session_id)

    if req.agent_hint and req.session_id:
        session = agent_memory.session_service.get_session(req.session_id)
        if not session:
            return _chat_response("Session not found.", llm_mode=llm_mode, success=False)
        hint = req.agent_hint.lower()

        if hint == 'requirements':
            res = requirements_agent.gather_requirements(
                session_id=req.session_id,
                project_name=session.project_name,
                module=session.module,
                stakeholder_input=req.message,
                erp_system=session.erp_system
            )
            summary = res.get('requirements', {}).get('executive_summary', 'No summary available.')
            return _chat_response(f"Requirements gathered: {summary}", llm_mode=llm_mode, session_id=req.session_id)

        if hint == 'start_intake':
            res = _run_intake_step(req.session_id, None, resume=False)
            if not res.get('success'):
                return _chat_response(res.get('error', 'Intake failed.'), llm_mode=llm_mode,
                                      success=False, session_id=req.session_id)
            answer = res['answer']
            agent_memory.session_service.add_to_conversation(req.session_id, role="user", content=req.message)
            agent_memory.session_service.add_to_conversation(req.session_id, role="assistant", content=answer)
            return _chat_response(answer, llm_mode=llm_mode, session_id=req.session_id)

        agent_hint_phase_map = {
            'process_mapping': orchestrator.execute_process_mapping_phase,
            'solution_design': orchestrator.execute_solution_design_phase,
            'qa_testing': orchestrator.execute_qa_testing_phase,
            'uat_testing': orchestrator.execute_uat_testing_phase,
            'training': orchestrator.execute_training_phase,
        }
        if hint in agent_hint_phase_map:
            result = agent_hint_phase_map[hint](session_id=req.session_id)
            if result.get('success'):
                answer = f"Phase '{hint}' executed successfully."
                agent_memory.session_service.add_to_conversation(req.session_id, role="user", content=req.message)
                agent_memory.session_service.add_to_conversation(req.session_id, role="assistant", content=answer)
                return _chat_response(answer, llm_mode=llm_mode, session_id=req.session_id)
            else:
                return _chat_response(f"Failed to execute phase '{hint}': {result.get('error', 'Unknown error')}",
                                      llm_mode=llm_mode, success=False, session_id=req.session_id)
        # Unrecognized hint falls through to intent classification below.

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

        phase_kwargs = {'session_id': req.session_id}
        if decision.phase == 'requirements':
            phase_kwargs['stakeholder_input'] = req.message

        result = phase_map[decision.phase](**phase_kwargs)
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

    session_id = req.session_id
    if session_id is None:
        title = _derive_chat_title(req.message)
        session_id = agent_memory.create_project(project_name=title, module='FI', user_id=current_user.id, is_casual=True)

    data = info_retriever(req.message, {'summary': ''}, prefer_web=req.prefer_web, session_id=req.session_id)
    generation_config = {
        'temperature': 0.5,
        'max_output_tokens': settings.max_tokens,
        'task': TaskCategory.LIGHTWEIGHT,
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

    agent_memory.session_service.add_to_conversation(session_id, role="user", content=req.message)
    agent_memory.session_service.add_to_conversation(session_id, role="assistant", content=final_answer)

    logger.info({"event": "Chat response ready", "session_id": session_id})
    return _chat_response(final_answer, llm_mode=llm_mode, session_id=session_id)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _stream_chat_events(req: ChatRequest, current_user: User, request_id: Optional[str]):
    def ev(event_type, **data):
        if request_id:
            data['request_id'] = request_id
        return _sse(event_type, data)

    try:
        yield ev('message_start', session_id=req.session_id)

        llm_instance = llm_mod.get_llm()
        llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

        if req.session_id and _intake_is_pending(req.session_id):
            yield ev('agent_started', agent='intake', message='Gathering project context')
            res = _run_intake_step(req.session_id, req.message, resume=True)
            if not res.get('success'):
                yield ev('error', message=res.get('error', 'Intake failed.'))
                return
            answer = res['answer']
            agent_memory.session_service.add_to_conversation(req.session_id, role="user", content=req.message)
            agent_memory.session_service.add_to_conversation(req.session_id, role="assistant", content=answer)
            if res.get('document_path'):
                yield ev('document_created', phase='requirements_template', filename=os.path.basename(res['document_path']))
            yield ev('text_delta', text=answer)
            yield ev('workflow_completed')
            next_action = _next_action_for(agent_memory.session_service.get_session(req.session_id))
            yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=req.session_id,
                      next_action=next_action)
            return

        if req.agent_hint and req.session_id:
            session = agent_memory.session_service.get_session(req.session_id)
            if not session:
                yield ev('error', message='Session not found.')
                return
            hint = req.agent_hint.lower()

            if hint == 'start_intake':
                res = _run_intake_step(req.session_id, None, resume=False)
                if not res.get('success'):
                    yield ev('error', message=res.get('error', 'Intake failed.'))
                    return
                answer = res['answer']
                agent_memory.session_service.add_to_conversation(req.session_id, role="user", content=req.message)
                agent_memory.session_service.add_to_conversation(req.session_id, role="assistant", content=answer)
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(agent_memory.session_service.get_session(req.session_id))
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=req.session_id,
                          next_action=next_action)
                return

            phase_map = {
                'process_mapping': orchestrator.execute_process_mapping_phase,
                'solution_design': orchestrator.execute_solution_design_phase,
                'qa_testing': orchestrator.execute_qa_testing_phase,
                'uat_testing': orchestrator.execute_uat_testing_phase,
                'training': orchestrator.execute_training_phase,
            }
            if hint in phase_map:
                yield ev('agent_started', agent=hint, message=f"Running {hint.replace('_', ' ')} phase")
                result = phase_map[hint](session_id=req.session_id)
                if not result.get('success'):
                    yield ev('error', message=f"Failed to execute phase '{hint}': {result.get('error', 'Unknown error')}")
                    return
                doc_path = result.get('document_path')
                if doc_path:
                    yield ev('document_created', phase=hint, filename=os.path.basename(doc_path))
                for label, path in (result.get('documents') or {}).items():
                    if path:
                        yield ev('document_created', phase=hint, label=label, filename=os.path.basename(path))
                answer = f"Phase '{hint}' executed successfully."
                agent_memory.session_service.add_to_conversation(req.session_id, role="user", content=req.message)
                agent_memory.session_service.add_to_conversation(req.session_id, role="assistant", content=answer)
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(agent_memory.session_service.get_session(req.session_id))
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=req.session_id,
                          next_action=next_action)
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
                new_session = agent_memory.session_service.get_session(res.get('session_id'))
                next_action = _next_action_for(new_session) if new_session else None
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=res.get('session_id'),
                          next_action=next_action)
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
            phase_kwargs = {'session_id': req.session_id}
            if decision.phase == 'requirements':
                phase_kwargs['stakeholder_input'] = req.message
            result = phase_map[decision.phase](**phase_kwargs)
            if result.get('success'):
                doc_path = result.get('document_path')
                if doc_path:
                    yield ev('document_created', phase=decision.phase, filename=os.path.basename(doc_path))
                answer = f"Phase '{decision.phase}' executed successfully."
                agent_memory.session_service.add_to_conversation(req.session_id, role="user", content=req.message)
                agent_memory.session_service.add_to_conversation(req.session_id, role="assistant", content=answer)
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(agent_memory.session_service.get_session(req.session_id))
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=req.session_id,
                          next_action=next_action)
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
                agent_memory.session_service.add_to_conversation(session_id, role="user", content=req.message)
                agent_memory.session_service.add_to_conversation(session_id, role="assistant", content=answer)
                yield ev('text_delta', text=answer)
                yield ev('workflow_completed')
                next_action = _next_action_for(agent_memory.session_service.get_session(session_id))
                yield ev('message_complete', answer=answer, llm_mode=llm_mode, session_id=session_id,
                          next_action=next_action)
            else:
                yield ev('error', message='Failed to generate training materials.')
            return

        session_id = req.session_id
        if session_id is None:
            title = _derive_chat_title(req.message)
            session_id = agent_memory.create_project(project_name=title, module='FI', user_id=current_user.id, is_casual=True)

        yield ev('tool_started', tool='info_retriever', message='Searching knowledge base and web')
        data = info_retriever(req.message, {'summary': ''}, prefer_web=req.prefer_web, session_id=req.session_id)
        yield ev('tool_completed', tool='info_retriever')

        generation_config = {
            'temperature': 0.5,
            'max_output_tokens': settings.max_tokens,
            'task': TaskCategory.LIGHTWEIGHT,
        }
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

        final_answer = "".join(full_answer_parts)
        agent_memory.session_service.add_to_conversation(session_id, role="user", content=req.message)
        agent_memory.session_service.add_to_conversation(session_id, role="assistant", content=final_answer)

        logger.info({"event": "Chat response ready", "session_id": session_id})
        yield ev('workflow_completed')
        next_action = _next_action_for(agent_memory.session_service.get_session(session_id))
        yield ev('message_complete', answer=final_answer, llm_mode=llm_mode, session_id=session_id,
                  next_action=next_action)

    except Exception as e:
        logger.error("Unhandled error in chat stream", error=str(e), exc_info=True)
        yield ev('error', message='Internal server error while processing your message.')


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, request: Request, current_user: User = Depends(get_current_user)):
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
        with open('frontend/dist/index.html', 'r', encoding='utf-8') as f:
            html = f.read()
        return HTMLResponse(content=html, status_code=200)
    except FileNotFoundError:
        return HTMLResponse(
            content='<h3>ERP Orchestrator API</h3>'
                    '<p>Frontend not built yet - run <code>npm run build</code> in frontend/. '
                    'API docs: <a href="/docs">/docs</a>.</p>',
            status_code=200,
        )


def start_server(host: str = '127.0.0.1', port: int = 8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    start_server()