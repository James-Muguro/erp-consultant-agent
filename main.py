import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Annotated

# Import the agent's entry point
from src.agent.main import run_agent

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="src/ui/static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="src/ui/templates")

# In-memory conversation history (for demonstration)
conversation_history = []

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    Serves the main chat interface.
    """
    return templates.TemplateResponse("index.html", {"request": request, "conversation": conversation_history})

@app.post("/prompt")
async def process_prompt(request: Request, user_prompt: Annotated[str, Form()]):
    """
    Receives a prompt from the user, gets a response from the agent,
    and updates the conversation.
    """
    conversation_history.append({"role": "user", "content": user_prompt})

    # --- AGENT LOGIC INTEGRATION ---
    agent_response = run_agent(user_prompt, conversation_history)

    conversation_history.append({"role": "agent", "content": agent_response})

    return templates.TemplateResponse("index.html", {"request": request, "conversation": conversation_history})