"""
Configuration settings for ERP Consultant Agent.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar, List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Repository root, resolved from this file's location
# ---------------------------------------------------------------------------
# `src/config/settings.py` → parent `src/config` → parent `src` → parent root.
# Computed from `__file__` (an absolute path once imported) rather than from
# the process's current working directory, so the value is stable no matter
# where the process was launched from. Every relative path in the settings
# below is anchored to this constant, which eliminates the class of bug
# where the server and an ad-hoc script agree on the *setting* but
# disagree on the *physical directory* because their CWDs differ. This is
# what made profile-picture uploads appear to vanish: the file was written
# to the server's CWD-relative output/profile_pictures/, and a later read
# from a different CWD-relative path resolved to a different directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Cross-field invariants (enforced by validators below):
      * At least one LLM provider must be fully configured. A provider is
        configured only when BOTH its API key AND its model identifier are
        present and valid; an API key with no model (or vice versa) does
        not count. The hybrid LLM wrapper supports four providers, and
        it's a legitimate deployment to run with only one.
      * SerpApi key is required only when `enable_google_search` is on.
        It's a feature flag, not a global prerequisite.
      * The per-phase timeout must be at least as long as the worst-case
        LLM fallback chain, so the phase doesn't get killed before the
        LLM layer has a chance to exhaust its retries and fall back. The
        exact tier count isn't knowable here (dependencies on which keys
        are set), so this checks the conservative bound.

    Provider model identifiers are environment-driven only. There are no
    hardcoded production model names or defaults anywhere in this file.
    Changing a model requires only an environment-variable change
    (GEMINI_MODEL / GROQ_MODEL / OPENAI_MODEL / ANTHROPIC_MODEL), with no
    Python code change.

    Path anchoring: output_dir, logs_dir, and the .env file location are
    all resolved against _REPO_ROOT (this file's grandparent directory),
    not the process's current working directory. See _make_paths_absolute
    below for the validator that enforces this.
    """

    model_config = SettingsConfigDict(
        # Anchored to the repository root, not the process CWD. A server
        # started from a subdirectory would otherwise load a different
        # .env than the one the developer edits.
        env_file=str(_REPO_ROOT / '.env'),
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    # ------------------------------------------------------------------ #
    # LLM provider credentials
    # ------------------------------------------------------------------ #
    # All four are Optional at the type level. Each provider is considered
    # configured only when BOTH its API key AND its matching model are
    # present; enforced by _require_at_least_one_llm_provider below. The
    # hybrid wrapper skips any tier that is not fully configured, so an
    # unset key (or unset model) just means that tier is inactive, not a
    # startup failure.
    gemini_api_key: Optional[str] = Field(
        None, description="Gemini API Key (primary, free tier)"
    )
    groq_api_key: Optional[str] = Field(
        None, description="Groq API Key (secondary, free tier)"
    )
    openai_api_key: Optional[str] = Field(
        None, description="OpenAI API Key (tertiary, paid)"
    )
    anthropic_api_key: Optional[str] = Field(
        None, description="Anthropic API Key (quaternary, paid)"
    )

    # ------------------------------------------------------------------ #
    # Model identifiers
    # ------------------------------------------------------------------ #
    # These are environment-driven only - there are no hardcoded defaults.
    # Set via GEMINI_MODEL, GROQ_MODEL, OPENAI_MODEL, ANTHROPIC_MODEL.
    # A missing (None) value is valid at Settings-construction time; the
    # provider is simply treated as not configured. An empty string,
    # whitespace-only value, or a value with internal whitespace is
    # rejected by validation - never silently substituted.
    gemini_model: Optional[str] = Field(
        None,
        description="Gemini model ID (from GEMINI_MODEL; no built-in default)",
    )
    groq_model: Optional[str] = Field(
        None,
        description="Groq model ID (from GROQ_MODEL; no built-in default)",
    )
    openai_model: Optional[str] = Field(
        None,
        description="OpenAI model ID (from OPENAI_MODEL; no built-in default)",
    )
    anthropic_model: Optional[str] = Field(
        None,
        description="Anthropic model ID (from ANTHROPIC_MODEL; no built-in default)",
    )

    # ------------------------------------------------------------------ #
    # SerpApi (optional feature)
    # ------------------------------------------------------------------ #
    enable_google_search: bool = Field(
        default=True,
        description="Enables Google Search tool; requires serpapi_api_key when true",
    )
    serpapi_api_key: Optional[str] = Field(
        None, description="SerpApi API Key; required only when enable_google_search=True"
    )

    # ------------------------------------------------------------------ #
    # LLM generation defaults
    # ------------------------------------------------------------------ #
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(
        default=8192, gt=0,
        description="Default max output tokens. Agents may request more for "
                    "long structured outputs (requirements, process maps, "
                    "solution designs, test suites) via max(settings.max_tokens, N).",
    )

    # ------------------------------------------------------------------ #
    # Phase / LLM call timeouts
    # ------------------------------------------------------------------ #
    # Phase-level ceiling: bounds one whole agent phase call (tool use +
    # LLM calls + document generation), wired into
    # ERPOrchestratorAgent._call_agent_safely via run_with_timeout.
    timeout_seconds: int = Field(default=300, gt=0)

    # LLM-call-level settings: bound and harden individual provider calls,
    # wired into HybridLLMClient. Deliberately smaller than timeout_seconds
    # so several of these (retries, provider fallback) can happen inside
    # one phase. See llm_total_timeout_seconds for the aggregate bound.
    llm_call_timeout_seconds: int = Field(
        default=60, gt=0,
        description="Per-attempt timeout for a single provider call",
    )
    llm_retry_attempts: int = Field(
        default=2, gt=0,
        description="Retry attempts per provider before falling to the next tier",
    )
    llm_total_timeout_seconds: int = Field(
        default=180, gt=0,
        description="Aggregate budget for the entire provider fallback chain "
                    "(all retries across all tiers). Must be <= timeout_seconds "
                    "so the LLM layer returns a clean 'all providers failed' "
                    "error before the phase timeout fires.",
    )
    llm_max_concurrent_calls: int = Field(
        default=16, gt=0,
        description="Bounded size of the shared thread pool used for "
                    "timeout-wrapped LLM calls. When saturated, new calls fail "
                    "fast with OperationTimeoutError rather than blocking; raise "
                    "this if you see saturation in production.",
    )

    # ------------------------------------------------------------------ #
    # Agent / runtime
    # ------------------------------------------------------------------ #
    max_iterations: int = Field(default=10, gt=0)

    # ------------------------------------------------------------------ #
    # Logging
    # ------------------------------------------------------------------ #
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")

    # ------------------------------------------------------------------ #
    # Memory
    # ------------------------------------------------------------------ #
    memory_enabled: bool = Field(default=True)
    max_memory_items: int = Field(default=100, gt=0)
    max_conversation_history_items: int = Field(
        default=200, gt=0,
        description="Maximum conversation turns kept per session before oldest entries are trimmed",
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    project_name: str = Field(default="ERP Consultant Agent")
    environment: str = Field(default="development")

    # ------------------------------------------------------------------ #
    # Directories
    # ------------------------------------------------------------------ #
    # Both are anchored to _REPO_ROOT by _make_paths_absolute below when
    # they are relative. Absolute values are passed through unchanged.
    output_dir: str = Field(default="output")
    logs_dir: str = Field(default="logs")

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    # Defaults to a local SQLite file so the app runs with zero external
    # setup; set to a Postgres DSN in production
    # (postgresql+psycopg2://user:pass@host:5432/dbname).
    database_url: str = Field(default="sqlite:///output/erp_agent.db")

    # ------------------------------------------------------------------ #
    # Object storage (S3-compatible)
    # ------------------------------------------------------------------ #
    # All optional so the app starts without them configured - file upload
    # endpoints return a clear 503 if used before these are set.
    s3_bucket_name: Optional[str] = Field(default=None)
    s3_access_key_id: Optional[str] = Field(default=None)
    s3_secret_access_key: Optional[str] = Field(default=None)
    s3_region: str = Field(default="auto")
    # Set for R2/MinIO/any non-AWS S3-compatible endpoint; leave unset for
    # real AWS S3 (boto3 resolves the endpoint from s3_region instead).
    s3_endpoint_url: Optional[str] = Field(default=None)
    max_upload_size_mb: int = Field(default=15, gt=0)

    # ------------------------------------------------------------------ #
    # API security
    # ------------------------------------------------------------------ #
    api_auth_key: Optional[str] = Field(
        default=None,
        description="Deprecated: static shared API key. Superseded by per-user JWT auth "
                    "(see jwt_secret_key). Kept only so old .env files don't fail to load; "
                    "no endpoint checks it anymore.",
    )
    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="Comma-separated list of allowed CORS origins",
    )
    trusted_proxy_hops: int = Field(
        default=0, ge=0,
        description=(
            "Number of trusted reverse proxies in front of the app. Used by "
            "the rate limiter to extract the true client IP from X-Forwarded-For. "
            "0 = no proxy (use direct peer). 1 = single LB. 2 = CDN + LB."
        ),
    )
    max_request_body_mb: int = Field(
        default=25, gt=0,
        description=(
            "Maximum Content-Length for non-upload endpoints. The upload "
            "endpoints enforce their own per-file cap via max_upload_size_mb."
        ),
    )

    # JWT auth (per-user accounts)
    jwt_secret_key: str = Field(..., description="Secret key used to sign access tokens - required, no default")
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(
        default=1440, gt=0,
        description="Access token lifetime in minutes (default 24h). No refresh-token flow yet - "
                    "a user simply logs in again once expired.",
    )

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #
    @property
    def allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def object_storage_configured(self) -> bool:
        return bool(self.s3_bucket_name and self.s3_access_key_id and self.s3_secret_access_key)

    @property
    def configured_llm_providers(self) -> List[str]:
        """Ordered list of fully configured LLM providers, matching the
        fallback order used by HybridLLMClient. Useful for startup logging
        and for diagnosing why a call landed on a paid tier.

        A provider is listed only when BOTH its API key AND its matching
        model identifier are present (the model field validator already
        rejects empty/whitespace-only/internal-whitespace values, so a
        non-None model here is a valid, non-whitespace identifier). A
        provider with a key but no model, or a model but no key, is not
        configured."""
        providers: List[str] = []
        if self.gemini_api_key and self.gemini_model:
            providers.append("gemini")
        if self.groq_api_key and self.groq_model:
            providers.append("groq")
        if self.openai_api_key and self.openai_model:
            providers.append("openai")
        if self.anthropic_api_key and self.anthropic_model:
            providers.append("anthropic")
        return providers

    @property
    def unconfigured_llm_providers(self) -> List[str]:
        """Ordered list of providers that are not fully configured (missing
        API key, missing model, or both). Mirrors the fallback order."""
        configured = set(self.configured_llm_providers)
        return [p for p in ("gemini", "groq", "openai", "anthropic") if p not in configured]

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    # Known placeholder values from .env.example and common weak defaults -
    # rejected outright regardless of length, since someone could copy one
    # of these and pad it to 32+ characters without it being any less
    # guessable.
    _WEAK_JWT_SECRETS: ClassVar[set] = {
        "generate_a_long_random_secret_here",
        "changeme", "change_me", "secret", "your-secret-key",
        "your_secret_key_here", "insecure", "development",
    }

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret_strength(cls, v: str) -> str:
        """Fails fast at startup rather than silently accepting a weak
        signing key that would make every issued access token forgeable.
        This intentionally has no test/dev bypass - see .env.example and
        SECURITY.md for how to generate a real one; every environment,
        including local dev, needs one."""
        if v.strip().lower() in cls._WEAK_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY is set to a known placeholder/example value. "
                "Generate a real one: openssl rand -hex 32"
            )
        if len(v) < 32:
            raise ValueError(
                f"JWT_SECRET_KEY must be at least 32 characters (got {len(v)}) - a short key "
                "is brute-forceable and would let an attacker forge access tokens. "
                "Generate one: openssl rand -hex 32"
            )
        return v

    @field_validator("gemini_model", "groq_model", "openai_model", "anthropic_model")
    @classmethod
    def _validate_model_name(cls, v: Optional[str]) -> Optional[str]:
        """Model identifiers are environment-driven only - no hardcoded
        defaults exist anywhere.

        Contract:
          * None            -> valid; the provider's model is not
                               configured, so that provider is not
                               configured (see configured_llm_providers).
          * empty / ""      -> invalid; rejected so a stray empty env var
                               surfaces at startup.
          * whitespace-only -> invalid; rejected for the same reason.
          * internal WS     -> invalid; a stray space inside a model name
                               fails on every provider call with an opaque
                               400, so reject it early.
          * non-empty str   -> valid; returned stripped of surrounding
                               whitespace. The exact non-whitespace model
                               identifier is preserved with no provider-
                               specific format enforcement.

        No substitution: an invalid or missing value is never silently
        replaced with a different model."""
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError(
                "model name must be a non-empty string (empty and "
                "whitespace-only values are rejected)"
            )
        if any(c.isspace() for c in stripped):
            raise ValueError(f"model name must not contain whitespace: {v!r}")
        return stripped

    @field_validator("output_dir", "logs_dir")
    @classmethod
    def _make_paths_absolute(cls, v: str) -> str:
        """Resolve relative directory paths against the repository root,
        never the process's current working directory.

        An unanchored relative path resolves differently depending on
        where the process was started. In practice that means the server
        and any ad-hoc script (a migration, a shell one-liner, a test
        run) can agree on the setting while disagreeing on the physical
        directory - files written by one are invisible to the other. That
        is exactly the class of bug that made uploaded profile pictures
        appear to disappear: the upload wrote to <server-CWD>/output/
        profile_pictures/ and a later read from a different resolved
        directory 404'd.

        Absolute paths (production configuration, container WORKDIR-based
        paths) are returned unchanged.
        """
        path = Path(v)
        if path.is_absolute():
            return str(path)
        return str((_REPO_ROOT / path).resolve())

    @model_validator(mode="after")
    def _require_at_least_one_llm_provider(self) -> "Settings":
        """The hybrid LLM wrapper can run with any single fully-configured
        provider. A provider counts as configured only when BOTH its API
        key AND its matching model identifier are present - a key without
        a model, or a model without a key, is not configured and cannot
        serve requests."""
        if not self.configured_llm_providers:
            raise ValueError(
                "At least one complete LLM provider must be configured. Each "
                "provider requires BOTH an API key AND a model identifier. "
                "Set at least one of these pairs: "
                "GEMINI_API_KEY + GEMINI_MODEL, "
                "GROQ_API_KEY + GROQ_MODEL, "
                "OPENAI_API_KEY + OPENAI_MODEL, "
                "ANTHROPIC_API_KEY + ANTHROPIC_MODEL."
            )
        return self

    @model_validator(mode="after")
    def _require_serpapi_when_search_enabled(self) -> "Settings":
        """SerpApi is a feature-gated dependency, not a global prerequisite."""
        if self.enable_google_search and not self.serpapi_api_key:
            raise ValueError(
                "SERPAPI_API_KEY is required when ENABLE_GOOGLE_SEARCH is true. "
                "Either set the key or set ENABLE_GOOGLE_SEARCH=false."
            )
        return self

    @model_validator(mode="after")
    def _check_timeout_budget(self) -> "Settings":
        """The per-phase timeout must accommodate the aggregate LLM fallback
        budget, otherwise a phase will get killed by its own ceiling mid-
        fallback instead of surfacing a clean 'all providers failed' error.

        We intentionally only require `llm_total_timeout_seconds <=
        timeout_seconds` (the aggregate is a bounded quantity); the
        per-attempt math (attempts * tiers * call_timeout) can still exceed
        the phase ceiling if the aggregate is misconfigured, which is what
        this check catches. We log a warning for the per-attempt math but
        don't fail on it, because the aggregate is the real guarantee.
        """
        if self.llm_total_timeout_seconds > self.timeout_seconds:
            raise ValueError(
                f"llm_total_timeout_seconds ({self.llm_total_timeout_seconds}s) "
                f"must not exceed timeout_seconds ({self.timeout_seconds}s) - "
                "otherwise the phase-level timeout fires before the LLM "
                "fallback chain can finish, turning a clean provider-failure "
                "into an ambiguous phase failure."
            )
        return self

    # ------------------------------------------------------------------ #
    # Startup helpers
    # ------------------------------------------------------------------ #
    def init_directories(self) -> None:
        """Create output, log, and SQLite parent directories. Call once at
        application startup.

        All paths are absolute by the time they reach this method (see
        _make_paths_absolute), so directory creation is independent of the
        process's current working directory.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

        # For the default SQLite database, make sure the parent dir exists
        # so the first connection doesn't fail with an opaque error. Other
        # DSNs (Postgres, etc.) are the operator's responsibility.
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url[len("sqlite:///"):]
            if db_path and db_path != ":memory:":
                # Anchor a relative SQLite path the same way output_dir and
                # logs_dir are anchored. Absolute paths pass through.
                db_p = Path(db_path)
                if not db_p.is_absolute():
                    db_p = _REPO_ROOT / db_p
                parent = db_p.parent
                if parent and str(parent):
                    os.makedirs(parent, exist_ok=True)

    def describe_llm_configuration(self) -> dict:
        """Return a log-friendly summary of the effective LLM routing.

        Intended to be called once at startup so operators can see at a
        glance which providers are active, which are not, and which
        environment-supplied model each tier will use. In particular, this
        surfaces a wrong model name (which fails silently at call time and
        shifts load to a paid tier) as a config line you can eyeball.

        Distinguishes configured from unconfigured providers. API keys and
        other secrets are never included in the output.
        """
        configured = self.configured_llm_providers
        return {
            "providers": configured,
            "unconfigured_providers": self.unconfigured_llm_providers,
            "models": {
                "gemini": self.gemini_model,
                "groq": self.groq_model,
                "openai": self.openai_model,
                "anthropic": self.anthropic_model,
            },
            "timeouts": {
                "phase_seconds": self.timeout_seconds,
                "llm_call_seconds": self.llm_call_timeout_seconds,
                "llm_total_seconds": self.llm_total_timeout_seconds,
                "llm_retry_attempts": self.llm_retry_attempts,
            },
            "concurrency": {
                "llm_max_concurrent_calls": self.llm_max_concurrent_calls,
            },
            "paths": {
                "output_dir": self.output_dir,
                "logs_dir": self.logs_dir,
            },
        }


class AgentConfig:
    """Configuration for individual agents."""

    def __init__(
        self,
        name: str,
        description: str,
        temperature: float = 0.7,
        max_iterations: int = 5,
        tools: Optional[List[str]] = None,
    ):
        self.name = name
        self.description = description
        self.temperature = temperature
        self.max_iterations = max_iterations
        self.tools = tools or []


# Agent configurations
REQUIREMENTS_AGENT_CONFIG = AgentConfig(
    name="Requirements Gathering Agent",
    description="Analyzes stakeholder inputs and generates comprehensive requirement documents",
    temperature=0.5,
    max_iterations=5,
    tools=["google_search", "document_analyzer"],
)

PROCESS_MAPPING_AGENT_CONFIG = AgentConfig(
    name="Process Mapping Agent",
    description="Creates detailed business process maps and workflow diagrams",
    temperature=0.4,
    max_iterations=5,
    tools=["process_visualizer", "erp_knowledge_base"],
)

SOLUTION_DESIGN_AGENT_CONFIG = AgentConfig(
    name="Solution Design Agent",
    description="Designs ERP solutions based on requirements and best practices",
    temperature=0.6,
    max_iterations=5,
    tools=["erp_knowledge_base", "google_search"],
)

QA_TESTING_AGENT_CONFIG = AgentConfig(
    name="QA Testing Agent",
    description="Generates comprehensive QA test cases and test scripts",
    temperature=0.3,
    max_iterations=5,
    tools=["test_case_generator"],
)

UAT_TESTING_AGENT_CONFIG = AgentConfig(
    name="UAT Testing Agent",
    description="Creates user acceptance testing scenarios and test scripts",
    temperature=0.4,
    max_iterations=5,
    tools=["test_case_generator", "erp_knowledge_base"],
)

TRAINING_AGENT_CONFIG = AgentConfig(
    name="Training & Documentation Agent",
    description="Creates user manuals, training guides, and process documentation",
    temperature=0.5,
    max_iterations=5,
    tools=["document_generator", "process_visualizer"],
)


# Global settings instance
settings = Settings()