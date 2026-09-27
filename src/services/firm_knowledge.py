"""Firm-wide reusable knowledge store.

Sibling to erp_kb, not an extension of it. erp_kb is a static,
in-memory, module-keyed vendor knowledge base; this store is
organization-scoped, DB-backed, and populated from past finalized
responses. Extending erp_kb was rejected in Q2.

Retrieval strategy (Q1, approved):
  1. Keyword overlap over firm_knowledge_entries scoped to the caller's
     organization. Top-N candidates by token overlap.
  2. LLM rerank over the top-N candidates. The LLM selects the top-K
     most relevant for the new requirement. Never auto-selects a
     response; only orders context for the draft step.

Conflict handling is locked:
  * Historical responses inform the draft.
  * Historical responses never auto-override each other.
  * Conflicting responses are surfaced as context; the Business Development decides.
  * No 'most recent wins'.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.models import FirmKnowledgeEntry
from src.models.tender_response_schema import (
    LLMRerankSelection,
    PriorResponse,
)
from src.utils.llm import get_llm
from src.utils.model_selection import TaskCategory


logger = logging.getLogger(__name__)


SOURCE_TYPE_TOR_RESPONSE = "tor_requirement_response"


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def ingest_response(
    db: Session,
    *,
    organization_id: str,
    requirement_text: str,
    response_text: str,
    response_kind: Optional[str],
    source_session_id: Optional[str] = None,
    source_opportunity_id: Optional[str] = None,
    source_external_code: Optional[str] = None,
    category: Optional[str] = None,
    importance: Optional[str] = None,
    erp_system: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> FirmKnowledgeEntry:
    """Record one finalized response as reusable knowledge.

    Idempotent on (source_opportunity_id, source_external_code). If a
    row already exists for that tuple, it is returned unchanged. This
    makes the call safe inside the Business Development-finalize transaction, even
    on retries.

    Does not commit. Caller owns the transaction.
    """
    if source_opportunity_id and source_external_code:
        existing = (
            db.query(FirmKnowledgeEntry)
            .filter(
                FirmKnowledgeEntry.source_opportunity_id == source_opportunity_id,
                FirmKnowledgeEntry.source_external_code == source_external_code,
            )
            .first()
        )
        if existing is not None:
            return existing

    entry = FirmKnowledgeEntry(
        id=uuid.uuid4().hex,
        organization_id=organization_id,
        source_type=SOURCE_TYPE_TOR_RESPONSE,
        source_session_id=source_session_id,
        source_opportunity_id=source_opportunity_id,
        source_external_code=source_external_code,
        category=category,
        requirement_text=requirement_text,
        response_text=response_text,
        response_kind=response_kind,
        importance=importance,
        erp_system=erp_system,
        tags=tags or [],
    )
    db.add(entry)
    db.flush()
    return entry


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, drop short tokens."""
    out: List[str] = []
    for raw in (text or "").lower().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum())
        if len(cleaned) >= 4:
            out.append(cleaned)
    return out


def _keyword_candidates(
    db: Session,
    *,
    organization_id: str,
    requirement_text: str,
    erp_system: Optional[str],
    limit: int,
) -> List[PriorResponse]:
    """Top-N candidates by token overlap. N is deliberately generous
    (default 20) because the LLM rerank step is the precision filter."""
    q = db.query(FirmKnowledgeEntry).filter(
        FirmKnowledgeEntry.organization_id == organization_id,
        FirmKnowledgeEntry.source_type == SOURCE_TYPE_TOR_RESPONSE,
    )
    if erp_system:
        q = q.filter(
            (FirmKnowledgeEntry.erp_system == erp_system)
            | (FirmKnowledgeEntry.erp_system.is_(None))
        )
    rows = q.order_by(FirmKnowledgeEntry.created_at.desc()).limit(200).all()

    tokens = set(_tokenize(requirement_text))
    if not tokens:
        # Nothing to score; fall back to most recent.
        rows = rows[:limit]
    else:
        scored = []
        for r in rows:
            haystack = f"{r.requirement_text} {r.response_text} {r.category or ''}"
            row_tokens = set(_tokenize(haystack))
            overlap = len(tokens & row_tokens)
            if overlap > 0:
                scored.append((overlap, r.created_at, r))
        scored.sort(key=lambda x: (x[0], x[1] or 0), reverse=True)
        rows = [s[2] for s in scored[:limit]]

    return [
        PriorResponse(
            requirement_text=r.requirement_text,
            response_text=r.response_text,
            response_kind=r.response_kind,
            source_external_code=r.source_external_code,
            category=r.category,
            created_at_iso=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]


def _rerank_with_llm(
    requirement_text: str, candidates: List[PriorResponse], limit: int,
) -> List[PriorResponse]:
    """Ask the LLM to select the most relevant candidates for the new
    requirement. On any failure, falls back to the keyword-ordered list
    truncated to `limit`. Never raises."""
    if not candidates:
        return []
    if len(candidates) <= limit:
        return candidates

    payload = [
        {
            "index": i,
            "requirement": c.requirement_text[:500],
            "response": c.response_text[:500],
            "kind": c.response_kind,
        }
        for i, c in enumerate(candidates)
    ]
    prompt = (
        "You are helping a Functional Consultant draft a fit response for "
        "a new tender requirement. Below is the new requirement and a list "
        "of candidate prior responses from past projects.\n\n"
        f"NEW REQUIREMENT:\n{requirement_text[:1000]}\n\n"
        "CANDIDATE PRIOR RESPONSES:\n"
        + "\n".join(
            f"[{c['index']}] req: {c['requirement']}\n    resp ({c['kind']}): {c['response']}"
            for c in payload
        )
        + f"\n\nSelect the {limit} most relevant prior responses for the "
        "new requirement, ordered from most to least relevant. Return JSON "
        "matching the schema."
    )
    try:
        resp = get_llm().generate_content(
            prompt,
            generation_config={
                "response_schema": LLMRerankSelection,
                "temperature": 0.0,
                "task": TaskCategory.LIGHTWEIGHT,
            },
        )
        selection = LLMRerankSelection.model_validate_json(resp.text)
    except Exception as e:  # noqa: BLE001 - must not break the draft path
        logger.warning(
            "Firm-knowledge rerank failed; falling back to keyword order: %s",
            e,
        )
        return candidates[:limit]

    picked = []
    seen = set()
    for idx in selection.selected_indices:
        if 0 <= idx < len(candidates) and idx not in seen:
            seen.add(idx)
            picked.append(candidates[idx])
    if not picked:
        return candidates[:limit]
    return picked


def retrieve_prior_responses(
    db: Session,
    *,
    organization_id: str,
    requirement_text: str,
    erp_system: Optional[str] = None,
    candidate_limit: int = 20,
    final_limit: int = 5,
) -> List[PriorResponse]:
    """Retrieve prior responses relevant to a new requirement.

    `erp_system` is optional. When provided, candidates whose stored
    `erp_system` matches OR is NULL are considered; NULL means the entry
    was finalized without an ERP context and is treated as universal.

    Never raises; on any failure the keyword result is truncated. The
    caller passes the returned list to the AI draft step as context.
    """
    try:
        candidates = _keyword_candidates(
            db,
            organization_id=organization_id,
            requirement_text=requirement_text,
            erp_system=erp_system,
            limit=candidate_limit,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Firm-knowledge keyword retrieval failed: %s", e)
        return []

    try:
        return _rerank_with_llm(requirement_text, candidates, final_limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("Firm-knowledge rerank dispatch failed: %s", e)
        return candidates[:final_limit]