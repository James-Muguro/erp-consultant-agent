"""
Per-project (session-scoped) agent knowledge store, backed by the
project_memories table (see src/db/models.py for why this replaces the old
global, file-based MemoryBank).

Every public method takes session_id and every query filters by it - there
is deliberately no method that reads across projects. MemoryEntry (the
return type) is reused from memory_bank.py rather than duplicated, since
its shape (to_dict/from_dict, access tracking fields) is still exactly
right - only where the entries live changed, not what an entry is.
"""
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

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


class ProjectMemoryStore:
    def __init__(self):
        self._session_factory = SessionLocal

    def seed_defaults(self, session_id: str) -> None:
        """Called once when a project is created - gives every project the
        same starting reference templates the old global store gave
        everyone, without sharing a single mutable copy across projects."""
        db = self._session_factory()
        try:
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
        finally:
            db.close()

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
        entry_id = entry_id or uuid.uuid4().hex
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
                    f"entry_id {entry_id} belongs to a different session; refusing to overwrite"
                )
            row.category = category
            row.content = content
            row.entry_metadata = metadata or {}
            row.tags = tags or []
            row.importance = importance
            db.commit()
            db.refresh(row)
            return _row_to_entry(row)
        finally:
            db.close()

    def retrieve_memory(self, session_id: str, entry_id: str) -> Optional[MemoryEntry]:
        db = self._session_factory()
        try:
            row = db.get(ProjectMemory, entry_id)
            if row is None or row.session_id != session_id:
                return None
            row.access_count += 1
            row.last_accessed = datetime.now(timezone.utc)
            db.commit()
            db.refresh(row)
            return _row_to_entry(row)
        finally:
            db.close()

    def search_by_category(self, session_id: str, category: str, limit: Optional[int] = None) -> List[MemoryEntry]:
        db = self._session_factory()
        try:
            query = (
                db.query(ProjectMemory)
                .filter(ProjectMemory.session_id == session_id, ProjectMemory.category == category)
                .order_by(ProjectMemory.importance.desc(), ProjectMemory.access_count.desc())
            )
            if limit:
                query = query.limit(limit)
            return [_row_to_entry(r) for r in query.all()]
        finally:
            db.close()

    def search_by_tags(
        self, session_id: str, tags: List[str], match_all: bool = False, limit: Optional[int] = None
    ) -> List[MemoryEntry]:
        db = self._session_factory()
        try:
            rows = db.query(ProjectMemory).filter(ProjectMemory.session_id == session_id).all()
            wanted = set(tags)
            matches = []
            for row in rows:
                row_tags = set(row.tags or [])
                if match_all:
                    if wanted.issubset(row_tags):
                        matches.append((row, row_tags))
                else:
                    if wanted & row_tags:
                        matches.append((row, row_tags))
            matches.sort(
                key=lambda pair: (len(wanted & pair[1]), pair[0].importance, pair[0].access_count),
                reverse=True,
            )
            if limit:
                matches = matches[:limit]
            return [_row_to_entry(r) for r, _ in matches]
        finally:
            db.close()

    def search_by_keywords(self, session_id: str, keywords: List[str], limit: Optional[int] = None) -> List[MemoryEntry]:
        db = self._session_factory()
        try:
            rows = db.query(ProjectMemory).filter(ProjectMemory.session_id == session_id).all()
            scored = []
            for row in rows:
                content_lower = row.content.lower()
                match_count = sum(1 for kw in keywords if kw.lower() in content_lower)
                if match_count > 0:
                    scored.append((row, match_count))
            scored.sort(key=lambda x: (x[1], x[0].importance, x[0].access_count), reverse=True)
            if limit:
                scored = scored[:limit]
            return [_row_to_entry(r) for r, _ in scored]
        finally:
            db.close()

    def get_relevant_memories(self, session_id: str, context: Dict[str, Any], limit: int = 5) -> List[MemoryEntry]:
        results: List[MemoryEntry] = []
        if 'category' in context:
            results.extend(self.search_by_category(session_id, context['category'], limit=limit))
        if 'tags' in context:
            results.extend(self.search_by_tags(session_id, context['tags'], limit=limit))
        if 'keywords' in context:
            results.extend(self.search_by_keywords(session_id, context['keywords'], limit=limit))

        unique = {m.entry_id: m for m in results}
        ordered = sorted(unique.values(), key=lambda m: (m.importance, m.access_count), reverse=True)
        return ordered[:limit]

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


# Global instance - safe to share across requests/threads since it holds no
# per-request state itself (every method opens its own DB session and
# always takes session_id as an explicit argument).
project_memory_store = ProjectMemoryStore()
