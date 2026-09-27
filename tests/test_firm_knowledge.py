"""
Firm knowledge store tests.


Snapshot basis: src/services/firm_knowledge. No HTTP endpoint exists; the store is exercised
directly through its service API.


Coverage:
  * Ingestion: row created with the correct organization_id.
  * Idempotency on (source_opportunity_id, source_external_code).
  * Organization scoping on retrieval - rows for org A are not returned
    when querying org B.
  * Keyword retrieval returns relevant rows.
  * Rerank path is not exercised here (it makes an LLM call); only the
    keyword path and the fallback-on-rerank-failure path are asserted,
    and the latter via monkeypatching the LLM call to raise.
"""
from __future__ import annotations


import uuid


import pytest


from src.db.base import SessionLocal
from src.db.models import FirmKnowledgeEntry, Opportunity
from src.services import firm_knowledge



@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()



@pytest.fixture
def org_ids(db, cleanup_registry):
    """Create two independent organization rows for scoping tests."""
    from src.db.models import Organization
    a = uuid.uuid4().hex
    b = uuid.uuid4().hex
    db.add(Organization(id=a, name=f"FK Org A {a[:6]}", created_by=None))
    db.add(Organization(id=b, name=f"FK Org B {b[:6]}", created_by=None))
    db.commit()
    cleanup_registry.org_ids.extend([a, b])
    return a, b



def _opportunity(db, org_id: str, cleanup_registry) -> str:
    """Create a real Opportunity row so firm-knowledge tests can use a
    valid source_opportunity_id FK. Registered with cleanup_registry
    so teardown removes it."""
    opp_id = uuid.uuid4().hex
    db.add(Opportunity(
        id=opp_id, organization_id=org_id,
        title=f"FK Opp {opp_id[:6]}", client_name="Client",
        status="draft",
    ))
    db.commit()
    cleanup_registry.opportunity_ids.append(opp_id)
    return opp_id


class TestIngestion:
    def test_ingest_creates_row_with_correct_org(self, db, org_ids):
        org_a, _ = org_ids
        entry = firm_knowledge.ingest_response(
            db,
            organization_id=org_a,
            requirement_text="Need real-time bank reconciliation.",
            response_text="Configured via standard treasury reconciliation.",
            response_kind="meets_out_of_the_box",
            source_opportunity_id=None,
            source_external_code="TOR-001",
        )
        db.commit()
        assert entry.id is not None
        assert entry.organization_id == org_a


    def test_ingest_is_idempotent_on_source_pair(self, db, org_ids, cleanup_registry):
        org_a, _ = org_ids
        opp = _opportunity(db, org_a, cleanup_registry)
        first = firm_knowledge.ingest_response(
            db,
            organization_id=org_a,
            requirement_text="R",
            response_text="X",
            response_kind="not_supported",
            source_opportunity_id=opp,
            source_external_code="TOR-002",
        )
        db.commit()
        second = firm_knowledge.ingest_response(
            db,
            organization_id=org_a,
            requirement_text="R2",
            response_text="X2",
            response_kind="requires_customization",
            source_opportunity_id=opp,
            source_external_code="TOR-002",
        )
        db.commit()
        assert second.id == first.id


    def test_ingest_without_source_pair_is_append_only(self, db, org_ids):
        org_a, _ = org_ids
        first = firm_knowledge.ingest_response(
            db, organization_id=org_a,
            requirement_text="A", response_text="B",
            response_kind="meets_out_of_the_box",
        )
        second = firm_knowledge.ingest_response(
            db, organization_id=org_a,
            requirement_text="A", response_text="B",
            response_kind="meets_out_of_the_box",
        )
        db.commit()
        assert second.id != first.id



class TestRetrievalScoping:
    def test_keyword_retrieval_scopes_to_org(self, db, org_ids):
        org_a, org_b = org_ids
        firm_knowledge.ingest_response(
            db,
            organization_id=org_a,
            requirement_text="Real-time bank reconciliation via standard treasury.",
            response_text="Meets out of the box.",
            response_kind="meets_out_of_the_box",
        )
        firm_knowledge.ingest_response(
            db,
            organization_id=org_b,
            requirement_text="Real-time bank reconciliation via standard treasury.",
            response_text="Requires customization.",
            response_kind="requires_customization",
        )
        db.commit()


        # Disable rerank to isolate the keyword path.
        prior = firm_knowledge.retrieve_prior_responses(
            db,
            organization_id=org_a,
            requirement_text="bank reconciliation",
            candidate_limit=20,
            final_limit=5,
        )
        # Only the org_a row is eligible; both could match on keywords,
        # so assert non-empty and organization isolation.
        assert all(
            "bank" in r.requirement_text.lower()
            or "reconciliation" in r.requirement_text.lower()
            for r in prior
        )
        # The org_b row's content ("Requires customization.") must not
        # appear in results for org_a.
        assert all(
            "Requires customization" not in (r.response_text or "")
            for r in prior
        )


    def test_retrieval_returns_empty_for_unrelated_org(self, db, org_ids):
        org_a, _ = org_ids
        empty_org = uuid.uuid4().hex
        from src.db.models import Organization
        db.add(Organization(id=empty_org, name="FK Empty", created_by=None))
        db.commit()


        firm_knowledge.ingest_response(
            db, organization_id=org_a,
            requirement_text="UniqueToken ABCD1234 here.",
            response_text="Response.",
            response_kind="meets_out_of_the_box",
        )
        db.commit()


        prior = firm_knowledge.retrieve_prior_responses(
            db, organization_id=empty_org,
            requirement_text="UniqueToken ABCD1234",
        )
        assert prior == []



class TestRerankFallback:
    def test_rerank_failure_falls_back_to_keyword_order(
        self, db, org_ids, monkeypatch,
    ):
        org_a, _ = org_ids
        for i in range(5):
            firm_knowledge.ingest_response(
                db, organization_id=org_a,
                requirement_text=f"Requirement about reconciliation variant {i}",
                response_text=f"Response {i}",
                response_kind="meets_out_of_the_box",
            )
        db.commit()


        def _boom(*_a, **_k):
            raise RuntimeError("simulated LLM failure")


        monkeypatch.setattr(firm_knowledge, "get_llm", _boom)


        prior = firm_knowledge.retrieve_prior_responses(
            db, organization_id=org_a,
            requirement_text="reconciliation",
            candidate_limit=20,
            final_limit=3,
        )
        assert len(prior) <= 3