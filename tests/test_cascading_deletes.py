"""
Regression test for the cascading-delete bug: deleting a session must
not raise ForeignKeyViolation even when it has requirements, process
steps, solution decisions, test cases, training steps, issues, and
review actions attached. Requires FK enforcement to actually be active
to be meaningful - see db/base.py's SQLite PRAGMA fix.
"""
from src.memory import agent_memory
from src.services import project_intelligence


def test_deleting_session_cascades_to_project_intelligence_tables():
    session_id = agent_memory.create_project(project_name="Cascade Test", module="General")

    req_ids = project_intelligence.sync_requirements_from_structured(session_id, {
        "functional_requirements": {"Finance": [{"id": "REQ-001", "description": "Test req"}]}
    })
    project_intelligence.create_issue(session_id, "missing_info", "Test issue")
    project_intelligence.add_trace_link(session_id, "process_step", "fake-id", "requirement", req_ids[0])

    deleted = agent_memory.session_service.delete_session(session_id)
    assert deleted is True

    assert project_intelligence.get_requirements(session_id) == []
    assert project_intelligence.get_issues(session_id, status=None) == []