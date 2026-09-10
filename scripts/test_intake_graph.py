"""
Standalone smoke test for the intake graph - run this BEFORE wiring
anything into orchestrator_api.py, to confirm invoke/resume mechanics
work correctly against the installed langgraph version.

Run: python scripts/test_intake_graph.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.types import Command
from src.graphs.intake_graph import build_intake_graph, make_checkpointer
from src.config.settings import settings
from src.memory import agent_memory

real_session_id = agent_memory.create_project(
    project_name="Test Co", module="General",
    erp_system="Microsoft Dynamics 365 Business Central"
)
checkpointer = make_checkpointer(settings.database_url)
graph = build_intake_graph(checkpointer)

config = {"configurable": {"thread_id": real_session_id}}

initial_state = {
    "session_id": real_session_id,
    "project_name": "Test Co",
    "module": "General",
    "erp_system": "Microsoft Dynamics 365 Business Central",
}

print("--- Starting graph ---")
result = graph.invoke(initial_state, config=config)
print("Result keys:", list(result.keys()))
print("Interrupt payload:", result.get("__interrupt__"))

# Simulate answering each question
answers = ["Healthcare", "1000+ employees", "Standardize finance and HR", "Finance, HR, Grants"]
for ans in answers:
    print(f"--- Resuming with: {ans} ---")
    result = graph.invoke(Command(resume=ans), config=config)
    print("Interrupt payload:", result.get("__interrupt__"))
    print("Final answer so far:", result.get("final_answer"))

print("--- Checking state ---")
snapshot = graph.get_state(config)
print("Next node(s):", snapshot.next)

print("--- Resuming with fake stakeholder answers ---")
fake_answers = (
    "Finance needs GL, AP/AR, budgeting. HR needs employee records and leave management. "
    "Grants needs budget tracking and donor reporting."
)
result = graph.invoke(Command(resume=fake_answers), config=config)
print("Final answer:", result.get("final_answer"))
print("Document path:", result.get("document_path"))

print("--- Final state check ---")
snapshot = graph.get_state(config)
print("Next node(s):", snapshot.next)