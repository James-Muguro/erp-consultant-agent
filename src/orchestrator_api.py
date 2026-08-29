"""
FastAPI wrapper for ERP Orchestrator with hybrid LLM support (Gemini + GPT-4 fallback)
"""
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uvicorn

from src.orchestrator import orchestrator
from src.config.settings import settings
import src.utils.llm as llm_mod
from src.agents import requirements_agent, training_agent
from src.memory import agent_memory
from src.tools.info_retriever import info_retriever
from src.utils.logger import get_logger
from src.utils.prompts import get_synthesis_prompt

logger = get_logger(__name__)

app = FastAPI(title="ERP Orchestrator API")

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


def _chat_response(answer: str, llm_mode: str, success: bool = True):
    return {
        'success': success,
        'answer': answer,
        'llm_mode': llm_mode,
    }


@app.post("/api/chat")
def chat(req: ChatRequest, _: str = Depends(verify_api_key)):
    logger.info({"event": "Chat request received", "message": req.message, "session_id": req.session_id})

    m_lower = req.message.lower()
    llm_instance = llm_mod.get_llm()
    llm_mode = "gemini" if getattr(llm_instance, "use_gemini", True) else "gpt-4"

    # Special commands
    if 'start project' in m_lower or 'start workflow' in m_lower:
        parts = req.message.split(':')
        project_name = parts[1].strip() if len(parts) > 1 else 'Chat Project'
        res = orchestrator.start_project(project_name, 'FI', initial_input=None)
        if res.get('success'):
            return _chat_response(f"Project '{project_name}' started successfully with session ID: {res.get('session_id')}.",
                                  llm_mode=llm_mode)
        else:
            return _chat_response(f"Failed to start project: {res.get('error', 'Unknown error')}",
                                  llm_mode=llm_mode, success=False)

    if 'run phase' in m_lower or 'execute phase' in m_lower:
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
        for p, func in phase_map.items():
            if p in m_lower:
                result = func(session_id=req.session_id)
                if result.get('success'):
                    return _chat_response(f"Phase '{p}' executed successfully.", llm_mode=llm_mode)
                else:
                    return _chat_response(f"Failed to execute phase '{p}': {result.get('error', 'Unknown error')}",
                                          llm_mode=llm_mode, success=False)
        return _chat_response("Could not determine which phase to run.", llm_mode=llm_mode, success=False)

    # Agent hint
    if req.agent_hint and req.session_id:
        if req.agent_hint.lower() == 'requirements':
            res = requirements_agent.gather_requirements(
                session_id=req.session_id,
                project_name='Chat Project',
                module='FI',
                stakeholder_input=req.message
            )
            summary = res.get('requirements', {}).get('executive_summary', 'No summary available.')
            return _chat_response(f"Requirements gathered: {summary}",
                                  llm_mode=llm_mode)

    # Training materials - requires an explicit generation command, not just
    # any message that happens to mention "training" (e.g. a question like
    # "what does UAT training cover?" must NOT trigger document generation)
    training_triggers = ('generate training', 'create training materials', 'generate user guide', 'create user manual', 'generate training guide', 'create training documentation')
    if any(t in m_lower for t in training_triggers) and req.session_id is None:
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

    # Info retrieval + LLM synthesis
    data = info_retriever(req.message, {'summary': ''}, prefer_web=req.prefer_web)
    final_answer = "No information found."

    if data and (data.get('kb_results') or data.get('web_results') or data.get('sources')):
        prompt = get_synthesis_prompt(req.message, data)
        generation_config = {
            'temperature': 0.5,
            'max_output_tokens': 2048,
        }
        try:
            response = llm_instance.generate_content(prompt, generation_config=generation_config)
            final_answer = extract_text(response)
        except Exception as e:
            logger.error(f"Error during final answer synthesis: {e}")
            final_answer = "I found some information, but I had trouble summarizing it."

    logger.info({"event": "Chat response ready", "session_id": req.session_id})
    return _chat_response(final_answer, llm_mode=llm_mode)


@app.get("/")
def get_ui():
    try:
        with open('ui/index.html', 'r', encoding='utf-8') as f:
            html = f.read()
        # Inject the API key so the browser-served JS can authenticate its
        # own requests. This is safe because whoever can load this page is
        # already served by the same trusted process holding the key.
        injected = f'<script>window.API_KEY = "{settings.api_auth_key}";</script></head>'
        html = html.replace('</head>', injected)
        return HTMLResponse(content=html, status_code=200)
    except Exception:
        return HTMLResponse(content='<h3>ERP Orchestrator API</h3><p>Visit /docs for API.</p>', status_code=200)


def start_server(host: str = '127.0.0.1', port: int = 8000):
    uvicorn.run(app, host=host, port=port)


if __name__ == '__main__':
    start_server()

