"""
Per-project (session-scoped) agent knowledge store, backed by the
project_memories table (see src/db/models.py for why this replaces the old
global, file-based MemoryBank).

Every public method takes session_id and every query filters by it - there
is deliberately no method that reads across projects. MemoryEntry (the
return type) is reused from memory_bank.py rather than duplicated, since
its shape (to_dict/from_dict, access tracking fields) is still exactly
right - only where the entries live changed, not what an entry is.

Design notes on this revision:

  * Access tracking is now wired up. Previously access_count and
    last_accessed existed in the schema and were sorted on by every
    search, but nothing ever incremented them - the "frequently recalled
    memories rank higher" behavior the schema implies was inert. Now
    get_relevant_memories (the recall path used by every agent) bumps
    access_count and last_accessed for the entries it returns.

  * seed_defaults is idempotent. Calling it twice on the same session no
    longer creates duplicate template rows.

  * Tag matching is case-insensitive. Previously a stored tag "SAP" was
    invisible to a search for "sap" - a common pattern when callers store
    tags from user input or module names.

  * Search result ordering now includes created_at as a final tiebreaker,
    so two equally-important, equally-accessed memories prefer the more
    recent one. Matches what a consultant would expect when both are
    otherwise equivalent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.db.base import SessionLocal
from src.db.models import ProjectMemory
from src.memory.memory_bank import MemoryEntry
from src.utils.logger import AgentLogger

logger = AgentLogger("ProjectMemoryStore")


# Seeded into every new project on creation - the same generic, non-sensitive
# reference content the old global MemoryBank seeded once for everyone.
# Copied per-project (not shared) so a project can still be deleted/archived
# independently without touching a shared global resource, and so nothing
# about scoping has to special-case "the default entries".
_DEFAULT_TEMPLATES = [
    {
        'category': 'requirements_template',
        'content': '''Requirement Document Structure:
1. Executive Summary
2. Business Context and Objectives
3. Functional Requirements (by module)
4. Technical Requirements
5. Integration Requirements
6. Reporting Requirements
7. Dependencies and Constraints
8. Acceptance Criteria''',
        'tags': ['template', 'requirements', 'structure'],
        'importance': 1.0,
    },
    {
        'category': 'best_practice',
        'content': '''ERP Implementation Best Practices:
- Minimize customizations, prefer configuration
- Follow standard ERP processes where possible
- Design for scalability and future growth
- Implement proper change management
- Ensure data quality before migration
- Include comprehensive user training
- Plan for post-go-live support''',
        'tags': ['implementation', 'best-practice', 'general'],
        'importance': 0.9,
    },
    {
        'category': 'test_case_template',
        'content': '''Test Case Structure:
- Test Case ID: Unique identifier
- Test Scenario: Brief description
- Preconditions: Setup required
- Test Steps: Numbered step-by-step instructions
- Test Data: Specific data to use
- Expected Results: Expected outcome
- Priority: Critical/High/Medium/Low''',
        'tags': ['template', 'testing', 'qa'],
        'importance': 0.95,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_entry(row: ProjectMemory) -> MemoryEntry:
    return MemoryEntry(
        entry_id=row.id,
        category=row.category,
        content=row.content,
        metadata=row.entry_metadata or {},
        created_at=row.created_at,
        access_count=row.access_count,
        last_accessed=row.last_accessed,
        tags=row.tags or [],
        importance=row.importance,
    )


def _rank_key(entry: MemoryEntry):
    """Composite sort key for recall results, descending.
    Primary: importance (higher is more valuable).
    Secondary: access_count (higher = more frequently recalled).
    Tertiary: created_at (more recent wins among otherwise-equivalent
    entries). Without this, two memories with identical importance and
    access count ranked arbitrarily - and a fresh pattern from the
    current project could lose to a stale one from months ago.
    """
    created_ts = 0.0
    if entry.created_at is not None:
        try:
            created_ts = entry.created_at.timestamp()
        except (AttributeError, ValueError, OSError):
            # Defensive: some datetime shapes (e.g. aware vs naive mix)
            # can fail .timestamp() on old records. Zero is fine - it just
            # means this entry ranks after any entry with a real timestamp.
            created_ts = 0.0
    return (entry.importance or 0.0, entry.access_count or 0, created_ts)


def _clean_keywords(keywords: Optional[List[str]]) -> List[str]:
    """Strip, lowercase, and drop empty or 1-character keywords. A
    keyword of 'a' would match nearly every memory; a keyword of '' or
    None would match everything via substring.""",
    if not keywords:
        return []
    out: List[str] = []
    for kw in keywords:
        if kw is None:
            continue
        s = str(kw).strip().lower()
        if len(s) >= 2:
            out.append(s)
    return out


def _clean_tags(tags: Optional[List[str]]) -> List[str]:
    """Strip, lowercase, dedupe, drop empties. Callers store tags from
    user input, module names, and agent-generated values - mixed case is
    common and previously made those tags unsearchable from lowercase
    queries."""
    if not tags:
        return []
    seen: set = set()
    out: List[str] = []
    for t in tags:
        if t is None:
            continue
        s = str(t).strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


class ProjectMemoryStore:
    """SQLAlchemy-backed, session-scoped memory store. Safe to share across
    requests and threads: every method opens its own DB session and takes
    session_id as an explicit argument, so the instance itself holds no
    per-request state."""

    def __init__(self):
        self._session_factory = SessionLocal

    # ------------------------------------------------------------------ #
    # Seeding
    # ------------------------------------------------------------------ #
    def seed_defaults(self, session_id: str) -> int:
        """Seed the standard templates for a new session.

        Idempotent: if the templates have already been seeded for this
        session (detected by the presence of any entry with the exact
        content of the first template), returns 0 without inserting
        duplicates. Calling this twice is safe - it was not before, and
        a partial failure during project creation followed by a retry
        could produce duplicate template rows.

        Returns the number of templates inserted (0 if already seeded).
        """
        db = self._session_factory()
        try:
            # Idempotency check - the first template's content is unique to
            # the seeding path, so finding it means we've already run.
            marker_content = _DEFAULT_TEMPLATES[0]['content']
            already = (
                db.query(ProjectMemory.id)
                .filter(
                    ProjectMemory.session_id == session_id,
                    ProjectMemory.content == marker_content,
                )
                .first()
            )
            if already is not None:
                logger.debug(
                    f"seed_defaults skipped: session {session_id} already seeded"
                )
                return 0

            for tmpl in _DEFAULT_TEMPLATES:
                row = ProjectMemory(
                    id=uuid.uuid4().hex,
                    session_id=session_id,
                    category=tmpl['category'],
                    content=tmpl['content'],
                    tags=tmpl['tags'],
                    importance=tmpl['importance'],
                    access_count=0,
                )
                db.add(row)
            db.commit()
            logger.info(
                f"Seeded {len(_DEFAULT_TEMPLATES)} default templates "
                f"for session {session_id}"
            )
            return len(_DEFAULT_TEMPLATES)
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def store_memory(
        self,
        session_id: str,
        entry_id: Optional[str] = None,
        category: str = '',
        content: str = '',
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        importance: float = 1.0,
    ) -> MemoryEntry:
        """Store or update a memory entry.

        Upsert semantics: if `entry_id` is supplied and a row with that id
        already exists for this session, the existing row is updated in
        place rather than a new one being created. This is what
        learn_from_project relies on (it uses a stable key like
        "lesson_<session_id>"), and it's the intended way to update a
        memory that has changed - there is deliberately no separate
        update_memory method, because store_memory with a known entry_id
        already provides that behavior.

        If `entry_id` is supplied and a row with that id exists for a
        DIFFERENT session, this raises ValueError rather than rewriting
        another project's entry. That's the guard against a cross-project
        data leak via a reused identifier.

        If `entry_id` is not supplied, a UUID is generated and a new row
        is always created.
        """
        entry_id = entry_id or uuid.uuid4().hex
        # Normalize tags on write so downstream tag searches match
        # regardless of the casing the caller used.
        clean_tags = _clean_tags(tags)

        db = self._session_factory()
        try:
            row = db.get(ProjectMemory, entry_id)
            if row is None:
                row = ProjectMemory(id=entry_id, session_id=session_id, access_count=0)
                db.add(row)
            elif row.session_id != session_id:
                # Never let an entry_id collision silently rewrite another
                # project's row - fail loudly instead of leaking across
                # projects via a reused ID.
                raise ValueError(
                    f"entry_id {entry_id} belongs to a different session; "
                    "refusing to overwrite"
                )
            row.category = category
            row.content = content
            row.entry_metadata = metadata or {}
            row.tags = clean_tags
            row.importance = importance
            db.commit()
            db.refresh(row)
            return _row_to_entry(row)
        finally:
            db.close()

    def delete_memory(self, session_id: str, entry_id: str) -> bool:
        db = self._session_factory()
        try:
            row = db.get(ProjectMemory, entry_id)
            if row is None or row.session_id != session_id:
                return False
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def retrieve_memory(self, session_id: str, entry_id: str) -> Optional[MemoryEntry]:
        """Fetch a single memory by id and record the access. Prefer
        get_relevant_memories for search-based recall - this method is for
        the case where a caller already knows the entry id and wants to
        both fetch and mark it as accessed in one operation."""
        db = self._session_factory()
        try:
            row = db.get(ProjectMemory, entry_id)
            if row is None or row.session_id != session_id:
                return None
            row.access_count = (row.access_count or 0) + 1
            row.last_accessed = datetime.now(timezone.utc)
            db.commit()
            db.refresh(row)
            return _row_to_entry(row)
        finally:
            db.close()

    def search_by_category(
        self, session_id: str, category: str, limit: Optional[int] = None,
    ) -> List[MemoryEntry]:
        db = self._session_factory()
        try:
            query = (
                db.query(ProjectMemory)
                .filter(
                    ProjectMemory.session_id == session_id,
                    ProjectMemory.category == category,
                )
                .order_by(
                    ProjectMemory.importance.desc(),
                    ProjectMemory.access_count.desc(),
                    # Recency tiebreaker - matches the Python-side ranking
                    # in get_relevant_memories so both orderings agree.
                    ProjectMemory.created_at.desc(),
                )
            )
            if limit and limit > 0:
                query = query.limit(limit)
            return [_row_to_entry(r) for r in query.all()]
        finally:
            db.close()

    def search_by_tags(
        self,
        session_id: str,
        tags: List[str],
        match_all: bool = False,
        limit: Optional[int] = None,
    ) -> List[MemoryEntry]:
        clean = _clean_tags(tags)
        if not clean:
            return []

        db = self._session_factory()
        try:
            rows = db.query(ProjectMemory).filter(
                ProjectMemory.session_id == session_id
            ).all()
            wanted = set(clean)
            matches = []
            for row in rows:
                # Lowercase stored tags on the comparison side so a tag
                # stored as "SAP" is visible to a search for "sap".
                row_tags = {
                    str(t).strip().lower()
                    for t in (row.tags or [])
                    if t is not None and str(t).strip()
                }
                if match_all:
                    if wanted.issubset(row_tags):
                        matches.append((row, row_tags))
                else:
                    if wanted & row_tags:
                        matches.append((row, row_tags))
            matches.sort(
                key=lambda pair: (
                    len(wanted & pair[1]),
                    pair[0].importance or 0.0,
                    pair[0].access_count or 0,
                    pair[0].created_at.timestamp() if pair[0].created_at else 0.0,
                ),
                reverse=True,
            )
            if limit and limit > 0:
                matches = matches[:limit]
            return [_row_to_entry(r) for r, _ in matches]
        finally:
            db.close()

    def search_by_keywords(
        self,
        session_id: str,
        keywords: List[str],
        limit: Optional[int] = None,
    ) -> List[MemoryEntry]:
        clean = _clean_keywords(keywords)
        if not clean:
            return []

        db = self._session_factory()
        try:
            rows = db.query(ProjectMemory).filter(
                ProjectMemory.session_id == session_id
            ).all()
            scored = []
            for row in rows:
                content_lower = (row.content or "").lower()
                match_count = sum(1 for kw in clean if kw in content_lower)
                if match_count > 0:
                    scored.append((row, match_count))
            scored.sort(
                key=lambda x: (
                    x[1],
                    x[0].importance or 0.0,
                    x[0].access_count or 0,
                    x[0].created_at.timestamp() if x[0].created_at else 0.0,
                ),
                reverse=True,
            )
            if limit and limit > 0:
                scored = scored[:limit]
            return [_row_to_entry(r) for r, _ in scored]
        finally:
            db.close()

    def get_relevant_memories(
        self, session_id: str, context: Dict[str, Any], limit: int = 5,
    ) -> List[MemoryEntry]:
        """Recall memories relevant to `context`, scoped to this session.
        `context` may contain any of 'category', 'tags', 'keywords'.
        Results are merged, deduplicated, ranked by importance then access
        count then recency, and capped at `limit`.

        This is the entry point every agent uses via AgentMemory.recall.
        Recall marks the returned entries as accessed, so the access_count
        signal that orders future searches actually reflects usage - it
        was previously inert (see module docstring).
        """
        results: List[MemoryEntry] = []
        if 'category' in context:
            results.extend(
                self.search_by_category(session_id, context['category'], limit=limit)
            )
        if 'tags' in context:
            results.extend(
                self.search_by_tags(session_id, context['tags'], limit=limit)
            )
        if 'keywords' in context:
            results.extend(
                self.search_by_keywords(session_id, context['keywords'], limit=limit)
            )

        unique = {m.entry_id: m for m in results}
        ordered = sorted(unique.values(), key=_rank_key, reverse=True)
        top = ordered[:limit]

        # Record access for the entries we're actually returning. This is
        # what makes access_count meaningful - before this, nothing in the
        # codebase ever incremented it in the recall path, so the
        # access_count ordering below was always sorting on 0.
        if top:
            self._touch_entries(session_id, [m.entry_id for m in top])

        return top

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _touch_entries(self, session_id: str, entry_ids: List[str]) -> None:
        """Bulk-increment access_count and refresh last_accessed for a set
        of entries. Batched into one UPDATE rather than N single-row
        updates. Failure is logged but does not propagate - a bookkeeping
        failure must not lose the recall results the caller asked for."""
        if not entry_ids:
            return
        db = self._session_factory()
        try:
            db.query(ProjectMemory).filter(
                ProjectMemory.session_id == session_id,
                ProjectMemory.id.in_(entry_ids),
            ).update(
                {
                    ProjectMemory.access_count: ProjectMemory.access_count + 1,
                    ProjectMemory.last_accessed: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
            db.commit()
        except Exception as e:  # noqa: BLE001 - bookkeeping is best-effort
            logger.warning(f"Failed to record memory access: {e}")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()


# Global instance - safe to share across requests/threads since it holds no
# per-request state itself (every method opens its own DB session and
# always takes session_id as an explicit argument).
project_memory_store = ProjectMemoryStore()