
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from termcolor import cprint

from src.orchestrator import Orchestrator
from src.config.settings import settings, AgentConfig
from src.utils.logger import get_logger

# Initialize logger
logger = get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title=settings.project_name,
    description="An AI agent for ERP functional consultants",
    version="0.1.0"
)

# In-memory storage for conversation history
conversation_history = {}

class UserRequest(BaseModel):
    """Request model for user interaction"""
    user_id: str
    query: str
    task: str  # e.g., "requirements_gathering", "solution_design"

@app.on_event("startup")
async def startup_event():
    """Log application startup"""
    logger.info(f"{settings.project_name} is starting up in {settings.environment} mode")
    cprint(f"[{settings.project_name}] Server is running at http://127.0.0.1:8000", "green")
    cprint(f"[{settings.project_name}] API documentation is available at http://127.0.0.1:8000/docs", "blue")

@app.post("/interact", summary="Interact with the ERP Consultant Agent")
async def interact_with_agent(request: UserRequest):
    """
    Main endpoint to interact with the agent.
    - **user_id**: A unique identifier for the user.
    - **query**: The user's query or message.
    - **task**: The specific task for the agent to perform.
    """
    try:
        # Get or create an orchestrator for the user
        orchestrator = await get_orchestrator(request.user_id)
        
        # Get the appropriate agent config
        agent_config = get_agent_config(request.task)
        
        # Let the orchestrator handle the request
        response = await orchestrator.run(request.query, agent_config)
        
        return {"response": response}
        
    except Exception as e:
        logger.error(f"Error during interaction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred.")

async def get_orchestrator(user_id: str) -> Orchestrator:
    """
    Retrieves or creates an orchestrator for a given user.
    This simple implementation uses an in-memory dictionary.
    For production, this should be replaced with a more robust solution.
    """
    if user_id not in conversation_history:
        cprint(f"Creating new orchestrator for user: {user_id}", "yellow")
        conversation_history[user_id] = Orchestrator(user_id=user_id)
    return conversation_history[user_id]

def get_agent_config(task: str) -> AgentConfig:
    """
    Returns the agent configuration for a given task.
    """
    task_to_config_map = {
        "requirements_gathering": "REQUIREMENTS_AGENT_CONFIG",
        "process_mapping": "PROCESS_MAPPING_AGENT_CONFIG",
        "solution_design": "SOLUTION_DESIGN_AGENT_CONFIG",
        "qa_testing": "QA_TESTING_AGENT_CONFIG",
        "uat_testing": "UAT_TESTING_AGENT_CONFIG",
        "training_and_documentation": "TRAINING_AGENT_CONFIG",
    }
    
    config_name = task_to_config_map.get(task)
    if not config_name:
        raise HTTPException(status_code=400, detail=f"Invalid task: {task}")
        
    # Dynamically get the config object from settings
    from src.config import settings as app_settings
    return getattr(app_settings, config_name)

@app.get("/health", summary="Health check endpoint")
async def health_check():
    """Returns the status of the application"""
    return {"status": "ok"}

if __name__ == "__main__":
    # This block is for local development and debugging
    # In production, use a Gunicorn or Uvicorn server directly
    uvicorn.run(app, host="127.0.0.1", port=8000)
    
