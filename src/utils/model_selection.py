"""
Task-aware model profile definitions.

Profiles describe the kind of work being requested without choosing a
provider or model yet. Provider fallback remains owned by HybridLLMClient.

A profile is a routing *hint*, not a correctness contract:
  - If a profile specifies a model override for a provider, HybridLLMClient
    uses it for that provider.
  - If a profile has no override for a provider (or no profile is
    available at all), the caller falls back to that provider's default
    model from settings. Empty overrides are therefore a valid, common
    state - they mean "no routing opinion; use the provider default."
  - An invalid or unrecognized task hint degrades to the same default-
    model behavior and logs a warning, rather than raising. Task categories
    are a tuning knob; a bad value must never take down an LLM call.

Valid provider keys are the ones HybridLLMClient supports:
    'gemini', 'groq', 'openai', 'anthropic'
Spelling is enforced at ModelTaskProfile construction time, so a typo in
an override map fails loudly at import (or at the explicit configuration
call) rather than silently returning None from model_for() at call time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
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
# HybridLLMClient uses these exact strings when calling model_for(). Kept
# here so typo'd overrides fail at construction rather than silently
# returning None at call time, and so callers can import a constant rather
# than write a bare string literal.
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
    category: TaskCategory
    model_overrides: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Wrap the mapping so a "frozen" dataclass truly can't have its
        # overrides mutated in place. dict(default_factory) is still a
        # mutable dict on its own; MappingProxyType closes that gap.
        if not isinstance(self.model_overrides, MappingProxyType):
            object.__setattr__(
                self,
                "model_overrides",
                MappingProxyType(dict(self.model_overrides)),
            )

        unknown = set(self.model_overrides) - SUPPORTED_PROVIDERS
        if unknown:
            raise ValueError(
                f"ModelTaskProfile for {self.category.value!r} has overrides "
                f"for unknown provider(s): {sorted(unknown)}. "
                f"Supported providers: {sorted(SUPPORTED_PROVIDERS)}"
            )
        for provider, model in self.model_overrides.items():
            if not isinstance(model, str) or not model.strip():
                raise ValueError(
                    f"ModelTaskProfile for {self.category.value!r}: override "
                    f"for provider {provider!r} must be a non-empty string, "
                    f"got {model!r}"
                )

    def model_for(self, provider: str) -> Optional[str]:
        """Return the model override for `provider`, or None if this
        profile has no opinion (caller should use the provider default)."""
        return self.model_overrides.get(provider)

    @property
    def has_overrides(self) -> bool:
        return bool(self.model_overrides)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        if self.model_overrides:
            return (
                f"ModelTaskProfile(category={self.category.value!r}, "
                f"overrides={dict(self.model_overrides)!r})"
            )
        return f"ModelTaskProfile(category={self.category.value!r}, no overrides)"


# ---------------------------------------------------------------------------
# Default profiles
# ---------------------------------------------------------------------------
# These start empty by design: an empty override map means "use the provider
# default model from settings for this task category." A blank profile is a
# valid, working state, not a bug or a TODO.
#
# To populate, either:
#   (a) edit the overrides below, or
#   (b) call set_task_profile_overrides(...) once at startup (e.g. from
#       settings or environment-driven config).
#
# Populating a category is the right place to encode a deliberate routing
# decision — e.g. "for HIGH_REASONING on OpenAI, always use gpt-4o rather
# than gpt-4o-mini." Without overrides, model selection is entirely
# controlled by settings.<provider>_model defaults, which is a fine setup
# for a single-environment deployment.
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

    Returns None — meaning "no routing opinion; use provider defaults" —
    if `task` is None, unrecognized, or an unsupported type. Never raises
    on bad input: a routing hint failing should degrade to the default
    model, not fail the entire LLM call. Unknown values are logged at
    WARNING so misconfiguration is visible in logs, not silent.
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
    """Replace a category's overrides.

    Intended for startup configuration (e.g. reading from settings or
    environment variables). Validates the override map the same way
    ModelTaskProfile construction does, so an invalid provider name or
    empty model string raises here rather than silently returning None
    from model_for() at call time.

    Returns the new profile. The previous profile object remains valid for
    any code still holding a reference, but new resolve_task_profile calls
    will return the new object.

    Note: this mutates the module-level TASK_PROFILES mapping. It should
    be called during process startup, before concurrent agent work begins.
    """
    if not isinstance(category, TaskCategory):
        raise TypeError(
            f"category must be a TaskCategory, got {type(category).__name__}"
        )
    profile = ModelTaskProfile(category=category, model_overrides=dict(overrides))
    TASK_PROFILES[category] = profile
    logger.info(
        "Task profile updated: %s -> %s",
        category.value,
        dict(profile.model_overrides) or "(no overrides; use provider defaults)",
    )
    return profile


def describe_task_profiles() -> dict[str, dict[str, str]]:
    """Return a log-friendly summary of the current profiles.

    Intended for startup diagnostics, so operators can see which categories
    are actually routed to specific models and which are falling through to
    provider defaults. Example output:

        {"high_reasoning": {}, "standard_agent": {},
         "structured_generation": {}, "lightweight": {}}
    """
    return {
        category.value: dict(TASK_PROFILES[category].model_overrides)
        for category in TaskCategory
    }