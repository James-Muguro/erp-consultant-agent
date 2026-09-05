"""
FastAPI wrapper for ERP Orchestrator with hybrid LLM support (Gemini + GPT-4 fallback)
"""
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict
from pathlib import Path
import os
import uvicorn

from src.orchestrator import orchestrator
from src.config.settings import settings
import src.utils.llm as llm_mod
from src.agents import requirements_agent, training_agent
from src.memory import agent_memory
from src.tools.info_retriever import info_retriever
from src.utils.logger import get_logger
from src.utils.prompts import get_synthesis_prompt
from src.models.chat_intent_schema import ChatIntent, ChatIntentDecision

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.init_directories()
    yield

app = FastAPI(title="ERP Orchestrator API", lifespan=lifespan)

logger = get_logger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ui", StaticFiles(directory="ui"), name="ui")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_auth_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key

class ProjectStart(BaseModel):
    project_name: str
    module: str
    erp_system: Optional[str] = "SAP S/4HANA"
    initial_input: Optional[str] = None


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


@app.post("/api/projects/start")
def start_project(req: ProjectStart, _: str = Depends(verify_api_key)):
    result = orchestrator.start_project(
        project_name=req.project_name,
        module=req.module,
        erp_system=req.erp_system,
        initial_input=req.initial_input
    )
    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error', 'Unknown error'))
    return result


@app.post("/api/projects/{session_id}/phase/{phase_name}/execute")
def execute_phase(session_id: str, phase_name: str, _: str = Depends(verify_api_key)):
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
def project_status(session_id: str, _: str = Depends(verify_api_key)):
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
def list_documents(session_id: str, _: str = Depends(verify_api_key)):
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    docs = _collect_session_documents(session_id)
    return {
        'session_id': session_id,
        'documents': [
            {'phase': d['phase'], 'label': d['label'], 'filename': os.path.basename(d['path'])}
            for d in docs
        ]
    }


@app.get("/api/projects/{session_id}/documents/{filename}")
def download_document(session_id: str, filename: str, _: str = Depends(verify_api_key)):
    session = agent_memory.session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

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
def chat(req: ChatRequest, _: str = Depends(verify_api_key)):
    logger.info({"event": "Chat request received", "message": req.message, "session_id": req.session_id})

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
        res = orchestrator.start_project(project_name, module, erp_system=erp_system, initial_input=None)
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
        session_id = agent_memory.create_project(project_name='AP Invoice Posting', module='FI')
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