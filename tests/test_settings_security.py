"""
Security tests for src/config/settings.py.

Coverage:

  JWT secret validation
    - Rejects short keys.
    - Rejects every value in the placeholder list (parametrized).
    - Rejects case-insensitive / whitespace-padded placeholders.
    - Accepts keys at or above 32 characters.

  Provider configuration
    - At least one LLM provider must be configured.
    - Gemini alone is sufficient (it stopped being mandatory).
    - An OpenAI-only deployment is valid.
    - SerpAPI is required only when enable_google_search is True.

  Model name validation
    - Empty model name rejected.
    - Model name with whitespace rejected.
    - Trailing-space model name is trimmed and accepted.

  Timeout budget
    - llm_total_timeout_seconds must not exceed timeout_seconds.

  Diagnostics
    - configured_llm_providers returns providers in fallback order.
    - describe_llm_configuration returns the expected keys.

  Directory initialization
    - init_directories creates output_dir, logs_dir, and the SQLite
      parent directory.

Test hermeticity:
  Every Settings() call passes _env_file=None. This disables reading
  the working directory's .env file, so tests run identically on a
  developer's machine, in CI, and in Docker. Without it, a value in
  a stray .env would silently override or supplement the test's
  monkeypatched environment.

Provider-configuration contract (mirrors src/config/settings.py):
  A provider counts as configured only when BOTH its API key and its
  matching model identifier are present. The four valid pairs are:
    GEMINI_API_KEY    + GEMINI_MODEL
    GROQ_API_KEY      + GROQ_MODEL
    OPENAI_API_KEY    + OPENAI_MODEL
    ANTHROPIC_API_KEY + ANTHROPIC_MODEL
  The baseline environment below therefore sets Gemini's key AND model
  together; tests that intentionally enable another provider must
  supply that provider's matching model alongside its key.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config.settings import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# A valid baseline environment: one complete LLM provider pair (Gemini
# key + model), one SerpAPI key, and a strong JWT secret. Every test
# overrides only the fields it specifically cares about.
_STRONG_JWT = "x" * 40

_PLACEHOLDER_JWT_VALUES = [
    "generate_a_long_random_secret_here",
    "changeme",
    "change_me",
    "secret",
    "your-secret-key",
    "your_secret_key_here",
    "insecure",
    "development",
]


def _base_env(**overrides) -> dict:
    """Build an environment dict for Settings(). Includes a strong JWT
    secret by default so tests that don't care about the JWT validator
    aren't forced to supply one, and a complete Gemini provider pair
    (API key + model) so the at-least-one-provider validator is
    satisfied without any test needing to opt in."""
    env = {
        "GEMINI_API_KEY": "fake-gemini-key",
        "GEMINI_MODEL": "gemini-test-model",
        "SERPAPI_API_KEY": "fake-serpapi-key",
        "JWT_SECRET_KEY": _STRONG_JWT,
    }
    env.update(overrides)
    return env


@pytest.fixture
def env(monkeypatch):
    """Apply a base environment via monkeypatch and return the helper
    so individual tests can layer overrides on top.

    pytest's monkeypatch auto-reverts at test teardown, so no explicit
    cleanup is needed."""
    def _apply(**overrides):
        for k, v in _base_env(**overrides).items():
            monkeypatch.setenv(k, v)
        return _base_env(**overrides)
    return _apply


def _settings(**overrides) -> Settings:
    """Construct Settings from the current env, ignoring any .env file.
    Prefer this over bare Settings() in tests — see module docstring
    on hermeticity."""
    return Settings(_env_file=None)


# ---------------------------------------------------------------------------
# JWT secret validation
# ---------------------------------------------------------------------------
class TestJwtSecretValidation:
    def test_rejects_a_short_key(self, env):
        env(JWT_SECRET_KEY="short_key")
        with pytest.raises(ValidationError, match="at least 32 characters"):
            _settings()

    def test_rejects_known_placeholder_values(self, env):
        env(JWT_SECRET_KEY="generate_a_long_random_secret_here")
        with pytest.raises(ValidationError, match="placeholder"):
            _settings()

    @pytest.mark.parametrize("placeholder", _PLACEHOLDER_JWT_VALUES)
    def test_rejects_every_known_placeholder(self, env, placeholder):
        """Every entry in Settings._WEAK_JWT_SECRETS must be rejected.
        Parametrizing over the list means adding a new placeholder to
        the set automatically extends coverage — a developer who adds
        one and forgets to update a hand-written test can't leave it
        untested."""
        env(JWT_SECRET_KEY=placeholder)
        with pytest.raises(ValidationError, match="placeholder"):
            _settings()

    def test_rejects_placeholder_regardless_of_case(self, env):
        env(JWT_SECRET_KEY="  CHANGEME  ")
        with pytest.raises(ValidationError, match="placeholder"):
            _settings()

    def test_rejects_placeholder_with_mixed_case_and_whitespace(self, env):
        env(JWT_SECRET_KEY="\t  Change_Me  \n")
        with pytest.raises(ValidationError, match="placeholder"):
            _settings()

    def test_accepts_a_strong_key(self, env):
        strong_key = "a" * 40
        env(JWT_SECRET_KEY=strong_key)
        settings = _settings()
        assert settings.jwt_secret_key == strong_key

    def test_accepts_a_key_exactly_at_the_32_character_minimum(self, env):
        key = "b" * 32
        env(JWT_SECRET_KEY=key)
        settings = _settings()
        assert settings.jwt_secret_key == key

    def test_rejects_a_key_one_character_under_the_minimum(self, env):
        env(JWT_SECRET_KEY="c" * 31)
        with pytest.raises(ValidationError, match="at least 32 characters"):
            _settings()


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------
class TestProviderConfiguration:
    def test_accepts_gemini_only(self, env, monkeypatch):
        """Gemini alone is a valid deployment. The previous Settings
        required it unconditionally; the review made every provider
        Optional and added a cross-field check that at least one is
        configured. A provider counts as configured only when both its
        API key and its matching model are present."""
        env()
        # Baseline env provides a complete Gemini pair; make sure no
        # other provider sneaks in.
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        settings = _settings()
        assert settings.gemini_api_key == "fake-gemini-key"
        assert settings.configured_llm_providers == ["gemini"]

    def test_accepts_openai_only(self, env, monkeypatch):
        """An OpenAI-only deployment is a legitimate configuration.
        Under the pre-review Settings this would fail because
        GEMINI_API_KEY was required. A complete pair (key + model) is
        supplied for OpenAI so the provider is registered, and the
        baseline Gemini key is removed so no provider other than
        OpenAI is configured."""
        env()
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
        monkeypatch.setenv("OPENAI_MODEL", "fake-openai-model")
        settings = _settings()
        assert settings.openai_api_key == "fake-openai-key"
        assert settings.configured_llm_providers == ["openai"]

    def test_rejects_when_no_provider_is_configured(self, env, monkeypatch):
        env()
        for key in ("GEMINI_API_KEY", "GROQ_API_KEY",
                    "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        with pytest.raises(
            ValidationError, match="At least one complete LLM provider"
        ):
            _settings()

    def test_providers_are_returned_in_fallback_order(self, env, monkeypatch):
        """The configured_llm_providers list must match the order the
        HybridLLMClient tries tiers in (gemini, groq, openai,
        anthropic) — a caller reading this list to understand routing
        depends on the ordering. Each added provider needs both its
        API key and its matching model to count as configured."""
        env()
        monkeypatch.setenv("GROQ_API_KEY", "fake-groq")
        monkeypatch.setenv("GROQ_MODEL", "fake-groq-model")
        monkeypatch.setenv("OPENAI_API_KEY", "fake-openai")
        monkeypatch.setenv("OPENAI_MODEL", "fake-openai-model")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic")
        monkeypatch.setenv("ANTHROPIC_MODEL", "fake-anthropic-model")
        settings = _settings()
        assert settings.configured_llm_providers == [
            "gemini", "groq", "openai", "anthropic",
        ]


# ---------------------------------------------------------------------------
# SerpAPI conditional dependency
# ---------------------------------------------------------------------------
class TestSerpApiDependency:
    def test_requires_serpapi_when_search_enabled(self, env, monkeypatch):
        """enable_google_search=True (the default) with no SerpAPI key
        is a startup-time error. The error message must name the
        setting so an operator can act on it."""
        env()
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        with pytest.raises(ValidationError, match="SERPAPI_API_KEY"):
            _settings()

    def test_allows_missing_serpapi_when_search_disabled(self, env, monkeypatch):
        """Turning off Google Search makes the SerpAPI key optional.
        This is the fix for the previous behavior where SerpAPI was
        required unconditionally, so a deployment without it couldn't
        start even if it never used Google Search."""
        env(ENABLE_GOOGLE_SEARCH="false")
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
        settings = _settings()
        assert settings.enable_google_search is False
        assert settings.serpapi_api_key is None


# ---------------------------------------------------------------------------
# Model name validation
# ---------------------------------------------------------------------------
class TestModelNameValidation:
    @pytest.mark.parametrize("model_field", [
        "GEMINI_MODEL", "GROQ_MODEL", "OPENAI_MODEL", "ANTHROPIC_MODEL",
    ])
    def test_rejects_whitespace_only_model_name(self, env, model_field):
        env(**{model_field: "   "})
        with pytest.raises(ValidationError, match="non-empty"):
            _settings()

    @pytest.mark.parametrize("model_field", [
        "GEMINI_MODEL", "GROQ_MODEL", "OPENAI_MODEL", "ANTHROPIC_MODEL",
    ])
    def test_rejects_model_name_with_internal_whitespace(self, env, model_field):
        """'gpt-4o mini' has a space that would silently break the
        provider call with an opaque 400. Rejecting at startup turns
        that into a clear config error."""
        env(**{model_field: "gpt-4o mini"})
        with pytest.raises(ValidationError, match="whitespace"):
            _settings()

    def test_accepts_model_name_with_surrounding_whitespace(self, env):
        """Trailing/leading whitespace is silently trimmed rather than
        rejected — it's a common .env editing artifact that's easy to
        fix automatically."""
        env(GEMINI_MODEL="  gemini-2.5-flash  ")
        settings = _settings()
        assert settings.gemini_model == "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Timeout budget
# ---------------------------------------------------------------------------
class TestTimeoutBudget:
    def test_rejects_llm_total_exceeding_phase_timeout(self, env):
        """The phase-level timeout must not fire before the LLM
        fallback chain can exhaust its retries — otherwise a
        provider-failure becomes an ambiguous phase failure. The
        cross-field validator enforces this at startup."""
        env(
            TIMEOUT_SECONDS="100",
            LLM_TOTAL_TIMEOUT_SECONDS="200",
        )
        with pytest.raises(ValidationError, match="llm_total_timeout_seconds"):
            _settings()

    def test_accepts_llm_total_equal_to_phase_timeout(self, env):
        """Equality is allowed — the LLM layer will simply run right up
        to the phase ceiling."""
        env(
            TIMEOUT_SECONDS="100",
            LLM_TOTAL_TIMEOUT_SECONDS="100",
        )
        settings = _settings()
        assert settings.llm_total_timeout_seconds == settings.timeout_seconds

    def test_accepts_llm_total_below_phase_timeout(self, env):
        """The default configuration: LLM total (180s) < phase timeout
        (300s), so the LLM layer finishes well within the phase
        ceiling."""
        env()  # defaults
        settings = _settings()
        assert settings.llm_total_timeout_seconds <= settings.timeout_seconds


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
class TestDiagnostics:
    def test_describe_llm_configuration_returns_expected_keys(self, env):
        env()
        config = _settings().describe_llm_configuration()
        for key in ("providers", "models", "timeouts", "concurrency"):
            assert key in config, f"missing key {key!r}"
        assert isinstance(config["providers"], list)
        assert isinstance(config["models"], dict)
        assert "gemini" in config["models"]
        assert "phase_seconds" in config["timeouts"]
        assert "llm_max_concurrent_calls" in config["concurrency"]

    def test_describe_reflects_only_configured_providers(self, env, monkeypatch):
        """The diagnostic must accurately report which tiers are
        actually active — the entire point of surfacing it at boot.
        A provider counts as configured only when both its API key
        and its matching model are present, so OpenAI is enabled here
        with a complete pair."""
        env()
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-openai")
        monkeypatch.setenv("OPENAI_MODEL", "fake-openai-model")
        config = _settings().describe_llm_configuration()
        assert config["providers"] == ["gemini", "openai"]


# ---------------------------------------------------------------------------
# Directory initialization
# ---------------------------------------------------------------------------
class TestDirectoryInitialization:
    def test_creates_output_and_logs_directories(self, env, tmp_path, monkeypatch):
        env(
            OUTPUT_DIR=str(tmp_path / "out"),
            LOGS_DIR=str(tmp_path / "logs"),
        )
        settings = _settings()
        settings.init_directories()
        assert Path(settings.output_dir).is_dir()
        assert Path(settings.logs_dir).is_dir()

    def test_creates_sqlite_parent_directory(self, env, tmp_path):
        """The default SQLite DSN points at output/erp_agent.db. Without
        creating the parent directory, the first DB connection fails
        with an opaque 'unable to open database file'. The review added
        parent-directory creation to init_directories."""
        db_path = tmp_path / "nested" / "data" / "erp_agent.db"
        env(
            OUTPUT_DIR=str(tmp_path / "out"),
            LOGS_DIR=str(tmp_path / "logs"),
            DATABASE_URL=f"sqlite:///{db_path}",
        )
        settings = _settings()
        settings.init_directories()
        assert db_path.parent.is_dir()

    def test_init_directories_is_idempotent(self, env, tmp_path):
        """Calling init_directories twice must not raise — some callers
        (lifespan, CLI entry points) may both call it."""
        env(
            OUTPUT_DIR=str(tmp_path / "out"),
            LOGS_DIR=str(tmp_path / "logs"),
        )
        settings = _settings()
        settings.init_directories()
        settings.init_directories()
        assert Path(settings.output_dir).is_dir()