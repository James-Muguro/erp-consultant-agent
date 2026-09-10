"""
LangGraph-based requirements intake flow - Phase 1 of the orchestration
migration. Replaces the ad hoc session.metadata flags (intake.active,
awaiting_stakeholder_answers, stakeholder_answers_provided) with a real,
checkpointed state machine using LangGraph's interrupt()/resume pattern.

Deliberately narrow scope: only the intake -> template -> structure
requirements flow lives here. The five downstream phases (process_mapping
through training) are NOT yet migrated - see prompts/orchestrator.py for
those, unchanged.

Node functions call the SAME existing agent methods
(requirements_agent.generate_requirements_template,
requirements_agent.gather_requirements) unchanged - this graph only
replaces the state-machine/control-flow layer, not the agent logic itself.
"""
from typing import TypedDict, Optional, Dict

from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from src.agents import requirements_agent
from src.memory import agent_memory
from src.config.settings import settings

INTAKE_QUESTIONS = [
    {"key": "industry", "text": "What industry is the client in?"},
    {"key": "company_size", "text": "Roughly how large is the organization (employee count or revenue range)?"},
    {"key": "primary_goal", "text": "What's the primary business problem or goal driving this ERP initiative?"},
    {"key": "scope_areas", "text": "Which business areas are in scope for this phase (e.g. Finance, Supply Chain, HR)?"},
]


class IntakeState(TypedDict, total=False):
    session_id: str
    project_name: str
    module: str
    erp_system: str
    answers: Dict[str, str]
    template_path: Optional[str]
    stakeholder_input: Optional[str]
    final_answer: Optional[str]
    document_path: Optional[str]


def collect_intake(state: IntakeState) -> dict:
    """Asks each intake question in order, one interrupt() per question.
    On resume, LangGraph re-executes this function from the top - already
    -answered questions replay their cached resume value instead of
    pausing again, so the loop naturally advances one question per
    invocation. See LangGraph's interrupt() docs for this replay model."""
    answers = dict(state.get("answers") or {})
    for q in INTAKE_QUESTIONS:
        if q["key"] in answers:
            continue
        response = interrupt(q["text"])
        answers[q["key"]] = response
    return {"answers": answers}


def generate_template(state: IntakeState) -> dict:
    result = requirements_agent.generate_requirements_template(
        project_name=state["project_name"],
        module=state["module"],
        erp_system=state["erp_system"],
        context=state["answers"],
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "Failed to generate requirements template"))
    return {
        "template_path": result["document_path"],
        "document_path": result["document_path"],
        "final_answer": (
            "Thanks - I've put together a requirements questionnaire based on your answers. "
            "Download it, work through it with your stakeholders, then come back and paste "
            "their answers in so I can turn them into a formal requirements document."
        ),
    }


def await_stakeholder_answers(state: IntakeState) -> dict:
    answer = interrupt("Paste your stakeholders' completed answers when ready.")
    return {"stakeholder_input": answer}


def structure_requirements(state: IntakeState) -> dict:
    result = requirements_agent.gather_requirements(
        session_id=state["session_id"],
        project_name=state["project_name"],
        module=state["module"],
        stakeholder_input=state["stakeholder_input"],
        erp_system=state["erp_system"],
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "Failed to structure requirements"))
    agent_memory.advance_phase(state["session_id"], "process_mapping")
    summary = result.get("requirements", {}).get("executive_summary", "Requirements captured.")
    return {
        "final_answer": f"Requirements structured and saved: {summary}",
        "document_path": result.get("document_path"),
    }


def build_intake_graph(checkpointer):
    builder = StateGraph(IntakeState)
    builder.add_node("collect_intake", collect_intake)
    builder.add_node("generate_template", generate_template)
    builder.add_node("await_stakeholder_answers", await_stakeholder_answers)
    builder.add_node("structure_requirements", structure_requirements)

    builder.add_edge(START, "collect_intake")
    builder.add_edge("collect_intake", "generate_template")
    builder.add_edge("generate_template", "await_stakeholder_answers")
    builder.add_edge("await_stakeholder_answers", "structure_requirements")
    builder.add_edge("structure_requirements", END)

    return builder.compile(checkpointer=checkpointer)


def make_checkpointer(database_url: str):
    """Creates a pooled Postgres connection for LangGraph's checkpointer.
    A single shared connection is NOT safe under concurrent requests -
    FastAPI runs sync routes in a threadpool, and simultaneous use of one
    psycopg connection object across threads can silently return
    incorrect results (confirmed root cause of a real production bug:
    the intake flow intermittently 'forgot' it was mid-question and fell
    through to normal chat routing). A ConnectionPool gives each
    concurrent caller its own connection, checked out and returned
    safely. autocommit=True and row_factory=dict_row are still required
    per-connection - the checkpointer raises a confusing TypeError deep
    inside its own code without them."""
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row
    from langgraph.checkpoint.postgres import PostgresSaver

    pool = ConnectionPool(
        conninfo=database_url,
        max_size=10,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    return checkpointer

_GRAPH_INSTANCE = None


def get_intake_graph():
    """Lazily-built singleton, same pattern as llm.get_llm() and the
    orchestrator/agent_memory module-level instances elsewhere in this
    codebase. Keeps one long-lived psycopg connection for the app's
    lifetime rather than opening/closing per request.

    Known limitation: this single connection is not proven safe under
    concurrent requests from multiple worker threads (Starlette runs sync
    routes in a threadpool). Fine for today's low-traffic usage; revisit
    with a connection pool (psycopg_pool) if concurrent intake traffic
    becomes real."""
    global _GRAPH_INSTANCE
    if _GRAPH_INSTANCE is None:
        checkpointer = make_checkpointer(settings.database_url)
        _GRAPH_INSTANCE = build_intake_graph(checkpointer)
    return _GRAPH_INSTANCE