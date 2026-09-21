"""
Task-aware model profile definitions.

Profiles describe the kind of work being requested. They intentionally do
NOT choose a provider or a model: provider fallback and provider model
identifiers are owned entirely by HybridLLMClient, which reads them from
environment-backed settings (settings.gemini_model, settings.groq_model,
settings.openai_model, settings.anthropic_model).

Task categories remain a pure classification: they label the kind of work
being requested, but they no longer carry any model identifiers and cannot
override the model any provider uses.

Valid provider keys (kept for callers that import them):
    'gemini', 'groq', 'openai', 'anthropic'
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional

logger = logging.getLogger(__name__)


class TaskCategory(str, Enum):
    HIGH_REASONING = "high_reasoning"
    STANDARD_AGENT = "standard_agent"
    STRUCTURED_GENERATION = "structured_generation"
    LIGHTWEIGHT = "lightweight"


# ---------------------------------------------------------------------------
# Provider keys — single source of truth
# ---------------------------------------------------------------------------
# HybridLLMClient uses these exact strings. Kept here so callers can import
# a constant rather than write a bare string literal. These are provider
# identifiers, not model identifiers - model identifiers come exclusively
# from environment-backed settings.
PROVIDER_GEMINI = "gemini"
PROVIDER_GROQ = "groq"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"

SUPPORTED_PROVIDERS = frozenset({
    PROVIDER_GEMINI,
    PROVIDER_GROQ,
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
})


@dataclass(frozen=True)
class ModelTaskProfile:
    """A task profile is a classification only.

    It carries no provider model identifiers and cannot override any
    provider's configured model. Providers choose their model exclusively
    from environment-backed settings (settings.<provider>_model).
    """

    category: TaskCategory

    def model_for(self, provider: str) -> Optional[str]:
        """Compatibility shim.

        Provider model identifiers must come exclusively from
        environment-backed settings; task profiles must not override them.
        This method therefore always returns None, which instructs callers
        to use the provider's configured model.
        """
        return None

    @property
    def has_overrides(self) -> bool:
        return False

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ModelTaskProfile(category={self.category.value!r}, no overrides)"


# ---------------------------------------------------------------------------
# Default profiles
# ---------------------------------------------------------------------------
# Profiles are intentionally empty of any model information. Every provider
# model is chosen from environment-backed settings only.
TASK_PROFILES: dict[TaskCategory, ModelTaskProfile] = {
    category: ModelTaskProfile(category=category)
    for category in TaskCategory
}


def resolve_task_profile(
    task: Optional[TaskCategory | str],
) -> Optional[ModelTaskProfile]:
    """Resolve a task hint into a profile.

    Accepts a TaskCategory, its string value ('high_reasoning', ...), its
    enum name ('HIGH_REASONING', ...), or None.

    Returns None — meaning "no routing opinion; use provider-configured
    models from settings" — if `task` is None, unrecognized, or an
    unsupported type. Never raises on bad input: a routing hint failing
    should degrade gracefully, not fail the entire LLM call. Unknown
    values are logged at WARNING so misconfiguration is visible in logs.
    """
    if task is None:
        return None

    if isinstance(task, TaskCategory):
        return TASK_PROFILES.get(task)

    if isinstance(task, str):
        # Accept the enum *value* first; that's the documented form and
        # the one that round-trips through config files. As a fallback,
        # also accept the enum *name* in any case, since environment
        # variables and YAML configs frequently carry the uppercase form.
        try:
            category = TaskCategory(task)
        except ValueError:
            try:
                category = TaskCategory[task.strip().upper()]
            except KeyError:
                logger.warning(
                    "Unknown task category %r; falling back to provider "
                    "default models. Valid categories: %s",
                    task,
                    ", ".join(c.value for c in TaskCategory),
                )
                return None
        return TASK_PROFILES.get(category)

    logger.warning(
        "resolve_task_profile received unsupported type %s (%r); ignoring.",
        type(task).__name__,
        task,
    )
    return None


def set_task_profile_overrides(
    category: TaskCategory,
    overrides: Mapping[str, str],
) -> ModelTaskProfile:
    """Deprecated no-op retained for backward compatibility.

    Provider model identifiers are now controlled exclusively through
    environment-backed settings (GEMINI_MODEL / GROQ_MODEL / OPENAI_MODEL /
    ANTHROPIC_MODEL). Task profiles must not override them, so any
    overrides passed here are ignored and logged at WARNING.

    Returns the (unchanged) profile for the given category.
    """
    if not isinstance(category, TaskCategory):
        raise TypeError(
            f"category must be a TaskCategory, got {type(category).__name__}"
        )
    if overrides:
        logger.warning(
            "set_task_profile_overrides called for %s with overrides %r - "
            "ignored. Provider model identifiers are now controlled only by "
            "environment-backed settings (settings.<provider>_model).",
            category.value,
            dict(overrides),
        )
    return TASK_PROFILES[category]


def describe_task_profiles() -> dict[str, dict[str, str]]:
    """Return a log-friendly summary of the current profiles.

    Every category is always empty now, since task profiles no longer
    carry model identifiers. The shape is preserved for callers that
    expect ``{category: {provider: model}}``.

    Example output:

        {"high_reasoning": {}, "standard_agent": {},
         "structured_generation": {}, "lightweight": {}}
    """
    return {category.value: {} for category in TaskCategory}