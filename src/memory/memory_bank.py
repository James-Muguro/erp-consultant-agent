"""
Memory Bank for long-term knowledge storage and retrieval
"""
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
import json
from pathlib import Path
from collections import defaultdict

from src.config.settings import settings
from src.utils.logger import AgentLogger


@dataclass
class MemoryEntry:
    """Represents a single memory entry"""
    entry_id: str
    category: str
    content: str
    metadata: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    importance: float = 1.0  # 0-1 scale
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'entry_id': self.entry_id,
            'category': self.category,
            'content': self.content,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'access_count': self.access_count,
            'last_accessed': self.last_accessed.isoformat() if self.last_accessed else None,
            'tags': self.tags,
            'importance': self.importance
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryEntry':
        """Create from dictionary"""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        if data.get('last_accessed'):
            data['last_accessed'] = datetime.fromisoformat(data['last_accessed'])
        return cls(**data)


class MemoryBank:
    """Long-term memory storage for agent learning and best practices"""
    
    # Memory categories
    CATEGORIES = {
        'requirements_template': 'Templates for requirement documents',
        'process_pattern': 'Common business process patterns',
        'solution_pattern': 'Solution design patterns',
        'test_case_template': 'Test case templates',
        'best_practice': 'ERP best practices and guidelines',
        'lesson_learned': 'Lessons learned from past projects',
        'common_issue': 'Common issues and resolutions',
        'erp_knowledge': 'ERP-specific knowledge and configurations'
    }
    
    def __init__(self):
        self.memories: Dict[str, MemoryEntry] = {}
        self.category_index: Dict[str, List[str]] = defaultdict(list)
        self.tag_index: Dict[str, List[str]] = defaultdict(list)
        self.logger = AgentLogger("MemoryBank")
        
        self.memory_dir = Path(settings.output_dir) / "memory_bank"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self._load_all_memories()
        self._initialize_default_memories()
    
    def store_memory(
        self,
        entry_id: str,
        category: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        importance: float = 1.0
    ) -> MemoryEntry:
        """Store a new memory entry"""
        if category not in self.CATEGORIES:
            self.logger.warning(f"Unknown category: {category}")
        
        entry = MemoryEntry(
            entry_id=entry_id,
            category=category,
            content=content,
            metadata=metadata or {},
            tags=tags or [],
            importance=importance
        )
        
        self.memories[entry_id] = entry
        self.category_index[category].append(entry_id)
        
        for tag in tags or []:
            self.tag_index[tag].append(entry_id)
        
        self.logger.log_memory_operation(
            "memory_stored",
            {
                'entry_id': entry_id,
                'category': category,
                'tags': tags
            }
        )
        
        self._save_memory(entry)
        return entry
    
    def retrieve_memory(self, entry_id: str) -> Optional[MemoryEntry]:
        """Retrieve a specific memory entry"""
        if entry_id not in self.memories:
            return None
        
        entry = self.memories[entry_id]
        entry.access_count += 1
        entry.last_accessed = datetime.now()
        
        self.logger.log_memory_operation(
            "memory_retrieved",
            {'entry_id': entry_id, 'access_count': entry.access_count}
        )
        
        return entry
    
    def search_by_category(
        self,
        category: str,
        limit: Optional[int] = None
    ) -> List[MemoryEntry]:
        """Search memories by category"""
        entry_ids = self.category_index.get(category, [])
        
        memories = [self.memories[eid] for eid in entry_ids if eid in self.memories]
        
        # Sort by importance and access count
        memories.sort(
            key=lambda x: (x.importance, x.access_count),
            reverse=True
        )
        
        if limit:
            memories = memories[:limit]
        
        return memories
    
    def search_by_tags(
        self,
        tags: List[str],
        match_all: bool = False,
        limit: Optional[int] = None
    ) -> List[MemoryEntry]:
        """Search memories by tags"""
        if match_all:
            # Find entries that have ALL tags
            entry_sets = [set(self.tag_index.get(tag, [])) for tag in tags]
            if entry_sets:
                matching_ids = set.intersection(*entry_sets)
            else:
                matching_ids = set()
        else:
            # Find entries that have ANY tag
            matching_ids = set()
            for tag in tags:
                matching_ids.update(self.tag_index.get(tag, []))
        
        memories = [
            self.memories[eid] for eid in matching_ids 
            if eid in self.memories
        ]
        
        # Sort by relevance (number of matching tags) and importance
        memories.sort(
            key=lambda x: (
                len(set(x.tags) & set(tags)),
                x.importance,
                x.access_count
            ),
            reverse=True
        )
        
        if limit:
            memories = memories[:limit]
        
        return memories
    
    def search_by_keywords(
        self,
        keywords: List[str],
        limit: Optional[int] = None
    ) -> List[MemoryEntry]:
        """Search memories by keywords in content"""
        matching_memories = []
        
        for entry in self.memories.values():
            content_lower = entry.content.lower()
            matches = sum(
                1 for keyword in keywords 
                if keyword.lower() in content_lower
            )
            
            if matches > 0:
                matching_memories.append((entry, matches))
        
        # Sort by number of matches, importance, and access count
        matching_memories.sort(
            key=lambda x: (x[1], x[0].importance, x[0].access_count),
            reverse=True
        )
        
        memories = [entry for entry, _ in matching_memories]
        
        if limit:
            memories = memories[:limit]
        
        return memories
    
    def get_relevant_memories(
        self,
        context: Dict[str, Any],
        limit: int = 5
    ) -> List[MemoryEntry]:
        """Get most relevant memories for given context"""
        relevant_memories = []
        
        # Search by category if provided
        if 'category' in context:
            relevant_memories.extend(
                self.search_by_category(context['category'], limit=limit)
            )
        
        # Search by tags if provided
        if 'tags' in context:
            relevant_memories.extend(
                self.search_by_tags(context['tags'], limit=limit)
            )
        
        # Search by keywords if provided
        if 'keywords' in context:
            relevant_memories.extend(
                self.search_by_keywords(context['keywords'], limit=limit)
            )
        
        # Remove duplicates and sort by importance
        unique_memories = {m.entry_id: m for m in relevant_memories}
        sorted_memories = sorted(
            unique_memories.values(),
            key=lambda x: (x.importance, x.access_count),
            reverse=True
        )
        
        return sorted_memories[:limit]
    
    def update_memory(
        self,
        entry_id: str,
        updates: Dict[str, Any]
    ) -> Optional[MemoryEntry]:
        """Update an existing memory entry"""
        if entry_id not in self.memories:
            return None
        
        entry = self.memories[entry_id]
        
        for key, value in updates.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        
        self.logger.log_memory_operation(
            "memory_updated",
            {'entry_id': entry_id, 'updated_fields': list(updates.keys())}
        )
        
        self._save_memory(entry)
        return entry
    
    def delete_memory(self, entry_id: str) -> bool:
        """Delete a memory entry"""
        if entry_id not in self.memories:
            return False
        
        entry = self.memories[entry_id]
        
        # Remove from indices
        self.category_index[entry.category].remove(entry_id)
        for tag in entry.tags:
            self.tag_index[tag].remove(entry_id)
        
        # Remove from storage
        del self.memories[entry_id]
        
        # Delete file
        memory_file = self.memory_dir / f"{entry_id}.json"
        if memory_file.exists():
            memory_file.unlink()
        
        self.logger.log_memory_operation("memory_deleted", {'entry_id': entry_id})
        return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get memory bank statistics"""
        return {
            'total_memories': len(self.memories),
            'categories': {
                cat: len(entries) 
                for cat, entries in self.category_index.items()
            },
            'top_tags': sorted(
                [(tag, len(entries)) for tag, entries in self.tag_index.items()],
                key=lambda x: x[1],
                reverse=True
            )[:10],
            'most_accessed': sorted(
                self.memories.values(),
                key=lambda x: x.access_count,
                reverse=True
            )[:5]
        }
    
    def _save_memory(self, entry: MemoryEntry):
        """Save memory to disk"""
        memory_file = self.memory_dir / f"{entry.entry_id}.json"
        with open(memory_file, 'w') as f:
            json.dump(entry.to_dict(), f, indent=2, default=str)
    
    def _load_all_memories(self):
        """Load all memories from disk"""
        for memory_file in self.memory_dir.glob("*.json"):
            try:
                with open(memory_file, 'r') as f:
                    data = json.load(f)
                
                entry = MemoryEntry.from_dict(data)
                self.memories[entry.entry_id] = entry
                self.category_index[entry.category].append(entry.entry_id)
                
                for tag in entry.tags:
                    self.tag_index[tag].append(entry.entry_id)
            except Exception as e:
                self.logger.error(f"Failed to load memory {memory_file}: {e}")
    
    def _initialize_default_memories(self):
        """Initialize with default ERP best practices"""
        default_memories = [
            {
                'entry_id': 'req_template_001',
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
                'importance': 1.0
            },
            {
                'entry_id': 'best_practice_001',
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
                'importance': 0.9
            },
            {
                'entry_id': 'test_template_001',
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
                'importance': 0.95
            }
        ]
        
        for mem_data in default_memories:
            entry_id = mem_data['entry_id']
            if entry_id not in self.memories:
                self.store_memory(**mem_data)


# Global memory bank instance
memory_bank = MemoryBank()