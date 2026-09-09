"""Task-aware model profile definitions.

Profiles describe the kind of work being requested without choosing a
provider or model yet. Provider fallback remains owned by HybridLLMClient.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional


class TaskCategory(str, Enum):
    HIGH_REASONING = "high_reasoning"
    STANDARD_AGENT = "standard_agent"
    STRUCTURED_GENERATION = "structured_generation"
    LIGHTWEIGHT = "lightweight"


@dataclass(frozen=True)
class ModelTaskProfile:
    category: TaskCategory
    model_overrides: Mapping[str, str] = field(default_factory=dict)

    def model_for(self, provider: str) -> Optional[str]:
        return self.model_overrides.get(provider)


TASK_PROFILES = {
    category: ModelTaskProfile(category=category)
    for category in TaskCategory
}


def resolve_task_profile(task: Optional[TaskCategory | str]) -> Optional[ModelTaskProfile]:
    if task is None:
        return None
    category = task if isinstance(task, TaskCategory) else TaskCategory(task)
    return TASK_PROFILES[category]
