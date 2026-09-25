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
# where the process was launched from.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Cross-field invariants (enforced by validators below):
      * At least one LLM provider must be fully configured.
      * SerpApi key is required only when `enable_google_search` is on.
      * The per-phase timeout must be at least as long as the worst-case
        LLM fallback chain.
      * SMTP configuration is required when email delivery is enabled.
      * SMTP must use exactly one of TLS or SSL, and at least one when
        email delivery is enabled.
      * Secure cookies are required outside the development environment.

    Provider model identifiers are environment-driven only. There are no
    hardcoded production model names or defaults anywhere in this file.

    Path anchoring: output_dir, logs_dir, and the .env file location are
    all resolved against _REPO_ROOT, not the process's current working
    directory.
    """

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / '.env'),
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    # ------------------------------------------------------------------ #
    # LLM provider credentials
    # ------------------------------------------------------------------ #
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
    timeout_seconds: int = Field(default=300, gt=0)

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
        description="Aggregate budget for the entire provider fallback chain. "
                    "Must be <= timeout_seconds.",
    )
    llm_max_concurrent_calls: int = Field(
        default=16, gt=0,
        description="Bounded size of the shared thread pool for timeout-wrapped "
                    "LLM calls.",
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
        description="Maximum conversation turns kept per session before oldest "
                    "entries are trimmed",
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    project_name: str = Field(default="ERP Consultant Agent")
    environment: str = Field(default="development")

    # ------------------------------------------------------------------ #
    # Directories
    # ------------------------------------------------------------------ #
    output_dir: str = Field(default="output")
    logs_dir: str = Field(default="logs")

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    database_url: str = Field(default="sqlite:///output/erp_agent.db")

    # ------------------------------------------------------------------ #
    # Object storage (S3-compatible)
    # ------------------------------------------------------------------ #
    s3_bucket_name: Optional[str] = Field(default=None)
    s3_access_key_id: Optional[str] = Field(default=None)
    s3_secret_access_key: Optional[str] = Field(default=None)
    s3_region: str = Field(default="auto")
    s3_endpoint_url: Optional[str] = Field(default=None)
    max_upload_size_mb: int = Field(default=15, gt=0)

    # ------------------------------------------------------------------ #
    # API security
    # ------------------------------------------------------------------ #
    api_auth_key: Optional[str] = Field(
        default=None,
        description="Deprecated: static shared API key. Superseded by per-user "
                    "JWT auth (see jwt_secret_key). Kept only so old .env files "
                    "don't fail to load; no endpoint checks it anymore.",
    )
    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="Comma-separated list of allowed CORS origins",
    )
    trusted_proxy_hops: int = Field(
        default=0, ge=0,
        description="Number of trusted reverse proxies in front of the app.",
    )
    max_request_body_mb: int = Field(
        default=25, gt=0,
        description="Maximum Content-Length for non-upload endpoints.",
    )

    # ================================================================== #
    # Authentication
    # ================================================================== #
    # JWT (access tokens)
    # ------------------------------------------------------------------ #
    jwt_secret_key: str = Field(
        ...,
        description="Secret key used to sign access tokens - required, no "
                    "default. Must be at least 32 characters.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="Fixed JWT signing algorithm. Validated at import time "
                    "against an allowlist; 'none' is never accepted. The "
                    "algorithm is never read from the token header.",
    )
    # ------------------------------------------------------------------ #
    # Access token TTL
    # ------------------------------------------------------------------ #
    # Phase 1 locked architecture: JWT access tokens are SHORT-LIVED.
    # The default is 15 minutes, matching the locked architecture.
    # Deployments with an explicit ACCESS_TOKEN_EXPIRE_MINUTES in their
    # environment keep their configured value; only the built-in default
    # changed. Access tokens are still accepted until they expire even
    # after this change - existing sessions continue to work.
    access_token_expire_minutes: int = Field(
        default=15, gt=0, le=1440,
        description="Access-token lifetime in minutes (default 15). Bounded "
                    "at 1440 (24h); short-lived tokens are paired with the "
                    "server-side revocable refresh flow.",
    )
    refresh_token_expire_days: int = Field(
        default=30, gt=0, le=365,
        description="Refresh-token lifetime in days. Refresh tokens are "
                    "opaque, stored server-side, and revocable.",
    )
    pending_auth_expire_minutes: int = Field(
        default=10, gt=0, le=60,
        description="Lifetime of the pre-authentication state issued between "
                    "password verification and OTP verification. Short-lived; "
                    "the pre-auth credential grants NO authenticated API "
                    "access on its own.",
    )

    # ------------------------------------------------------------------ #
    # Email OTP (MFA)
    # ------------------------------------------------------------------ #
    otp_length: int = Field(
        default=6, ge=4, le=10,
        description="Number of digits in an email OTP. Cryptographically "
                    "generated; not a sequence or timestamp.",
    )
    otp_expire_minutes: int = Field(
        default=10, gt=0, le=60,
        description="OTP lifetime in minutes. Short expiry is a core "
                    "brute-force defence alongside attempt limits.",
    )
    otp_max_attempts: int = Field(
        default=5, gt=0, le=20,
        description="Maximum failed OTP verification attempts per issued "
                    "code before the code is invalidated.",
    )
    otp_resend_interval_seconds: int = Field(
        default=60, ge=0, le=3600,
        description="Minimum interval between OTP resends for the same "
                    "pending-auth flow. Enforced at the service layer; also "
                    "paired with endpoint-level rate limiting.",
    )

    # ------------------------------------------------------------------ #
    # Email verification and password reset
    # ------------------------------------------------------------------ #
    email_verification_expire_hours: int = Field(
        default=24, gt=0, le=168,
        description="Lifetime of an email-verification token in hours.",
    )
    password_reset_expire_minutes: int = Field(
        default=30, gt=0, le=1440,
        description="Lifetime of a password-reset token in minutes.",
    )

    # ------------------------------------------------------------------ #
    # Progressive login protection (account-level)
    # ------------------------------------------------------------------ #
    # Account-level backstop. Endpoint-level rate limiting is the primary
    # control; these values shape the account-level response. Lockout is
    # time-bounded and reset on successful authentication, so an attacker
    # cannot permanently disable an account through this mechanism alone.
    login_max_failed_attempts: int = Field(
        default=10, gt=0, le=100,
        description="Consecutive failed password attempts before the "
                    "account is temporarily locked.",
    )
    login_lockout_duration_minutes: int = Field(
        default=15, gt=0, le=1440,
        description="Duration of the temporary account lockout once the "
                    "failed-attempt threshold is reached.",
    )

    # ------------------------------------------------------------------ #
    # Authentication cookies
    # ------------------------------------------------------------------ #
    # Refresh credentials are delivered as Secure, HttpOnly cookies. The
    # HttpOnly flag is hardcoded True wherever the cookie is set - it is
    # NOT configurable here, because a value of False for an auth cookie
    # is always a security defect and offering it as an option invites
    # accidental misconfiguration.
    auth_cookie_secure: bool = Field(
        default=True,
        description="Set the Secure flag on authentication cookies. Must "
                    "remain True outside development; the validator below "
                    "enforces that.",
    )
    auth_cookie_samesite: str = Field(
        default="lax",
        description="SameSite attribute for auth cookies: 'strict', 'lax', "
                    "or 'none'. 'none' additionally requires "
                    "auth_cookie_secure=True (browser rule).",
    )
    auth_cookie_domain: Optional[str] = Field(
        default=None,
        description="Cookie Domain attribute. Leave unset to scope cookies "
                    "to the exact request host.",
    )
    auth_cookie_path: str = Field(
        default="/",
        description="Cookie Path attribute.",
    )
    auth_refresh_cookie_name: str = Field(
        default="erp_refresh_token",
        description="Name of the HttpOnly refresh-credential cookie.",
    )
    auth_csrf_cookie_name: str = Field(
        default="erp_csrf_token",
        description="Name of the CSRF double-submit cookie. Read by the "
                    "frontend and echoed in the CSRF header.",
    )
    auth_csrf_header_name: str = Field(
        default="X-CSRF-Token",
        description="Name of the header the frontend uses to echo the "
                    "CSRF cookie value on state-changing requests.",
    )

    # ------------------------------------------------------------------ #
    # Email delivery (SMTP)
    # ------------------------------------------------------------------ #
    # The current provider is Gmail SMTP. Gmail SMTP has known constraints
    # that are documented here rather than only in external docs:
    #
    #   * The sending account MUST have 2-Step Verification enabled.
    #   * Authentication uses an APP PASSWORD, not the account password.
    #   * Gmail enforces daily sending limits (roughly a few hundred per
    #     day for a personal account; lower for a fresh account).
    #   * Deliverability and reputation are materially weaker than a
    #     dedicated transactional email provider (SendGrid, SES,
    #     Postmark). Messages may be throttled or filtered.
    #
    # The application talks to email through an interface
    # (send_email(to, subject, body)); the Gmail SMTP client is one
    # implementation behind that interface. Switching providers later
    # does not change authentication call sites.
    #
    # No credentials are hardcoded; all values come from the environment.
    email_delivery_enabled: bool = Field(
        default=False,
        description="Gate for SMTP configuration validation. When False, "
                    "SMTP fields are not required and no email is sent. Set "
                    "to True (and configure SMTP) to enable the email "
                    "verification and MFA flows.",
    )
    smtp_host: Optional[str] = Field(
        default=None,
        description="SMTP server hostname. For Gmail: smtp.gmail.com.",
    )
    smtp_port: int = Field(
        default=587, gt=0, le=65535,
        description="SMTP server port. Gmail uses 587 (STARTTLS) or "
                    "465 (implicit TLS).",
    )
    smtp_username: Optional[str] = Field(
        default=None,
        description="SMTP username. For Gmail, the full email address of "
                    "the sending account.",
    )
    smtp_password: Optional[str] = Field(
        default=None,
        description="SMTP password. For Gmail, an APP PASSWORD generated "
                    "after enabling 2-Step Verification on the account.",
    )
    smtp_from_address: Optional[str] = Field(
        default=None,
        description="Sender address used in the From header. For Gmail, "
                    "must match (or be an alias of) smtp_username.",
    )
    smtp_use_tls: bool = Field(
        default=True,
        description="Use STARTTLS on the connection (upgrade an ordinary "
                    "SMTP connection to TLS). Mutually exclusive with "
                    "smtp_use_ssl.",
    )
    smtp_use_ssl: bool = Field(
        default=False,
        description="Use implicit TLS (SMTPS). Mutually exclusive with "
                    "smtp_use_tls.",
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
        """Ordered list of fully configured LLM providers."""
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
        """Ordered list of providers that are not fully configured."""
        configured = set(self.configured_llm_providers)
        return [p for p in ("gemini", "groq", "openai", "anthropic") if p not in configured]

    @property
    def smtp_configured(self) -> bool:
        """True when every SMTP field required to actually send is set.
        Independent of email_delivery_enabled - a caller can be enabled
        but misconfigured, in which case this returns False and the
        startup validator would already have raised."""
        return bool(
            self.smtp_host
            and self.smtp_username
            and self.smtp_password
            and self.smtp_from_address
        )

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    _WEAK_JWT_SECRETS: ClassVar[set] = {
        "generate_a_long_random_secret_here",
        "changeme", "change_me", "secret", "your-secret-key",
        "your_secret_key_here", "insecure", "development",
        "your key here",
    }

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret_strength(cls, v: str) -> str:
        """Reject placeholder or short JWT secrets at startup. Preserved
        verbatim from the previous implementation, with one addition to
        the blocklist: 'your key here', which is the value used in the
        shipped .env.example."""
        if v.strip().lower() in cls._WEAK_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY is set to a known placeholder/example value. "
                "Generate a real one: openssl rand -hex 32"
            )
        if len(v) < 32:
            raise ValueError(
                f"JWT_SECRET_KEY must be at least 32 characters (got {len(v)}). "
                "Generate one: openssl rand -hex 32"
            )
        return v

    @field_validator("gemini_model", "groq_model", "openai_model", "anthropic_model")
    @classmethod
    def _validate_model_name(cls, v: Optional[str]) -> Optional[str]:
        """Model identifiers are environment-driven only."""
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
        """Resolve relative directory paths against the repository root."""
        path = Path(v)
        if path.is_absolute():
            return str(path)
        return str((_REPO_ROOT / path).resolve())

    @field_validator("auth_cookie_samesite")
    @classmethod
    def _normalize_auth_cookie_samesite(cls, v: str) -> str:
        """Normalize to lowercase and restrict to the three values
        browsers recognize. Any other value is rejected rather than
        passed through to a Set-Cookie header where it would be silently
        ignored."""
        normalized = (v or "").strip().lower()
        if normalized not in ("strict", "lax", "none"):
            raise ValueError(
                "auth_cookie_samesite must be one of 'strict', 'lax', "
                f"'none' (got {v!r})"
            )
        return normalized

    @model_validator(mode="after")
    def _require_at_least_one_llm_provider(self) -> "Settings":
        """At least one complete LLM provider must be configured."""
        if not self.configured_llm_providers:
            raise ValueError(
                "At least one complete LLM provider must be configured. Each "
                "provider requires BOTH an API key AND a model identifier."
            )
        return self

    @model_validator(mode="after")
    def _require_serpapi_when_search_enabled(self) -> "Settings":
        """SerpApi is a feature-gated dependency."""
        if self.enable_google_search and not self.serpapi_api_key:
            raise ValueError(
                "SERPAPI_API_KEY is required when ENABLE_GOOGLE_SEARCH is true."
            )
        return self

    @model_validator(mode="after")
    def _check_timeout_budget(self) -> "Settings":
        """The per-phase timeout must accommodate the aggregate LLM
        fallback budget."""
        if self.llm_total_timeout_seconds > self.timeout_seconds:
            raise ValueError(
                f"llm_total_timeout_seconds ({self.llm_total_timeout_seconds}s) "
                f"must not exceed timeout_seconds ({self.timeout_seconds}s)."
            )
        return self

    @model_validator(mode="after")
    def _validate_auth_cookie_security(self) -> "Settings":
        """Cookie security rules that must not be silently weakened.

        * SameSite=None requires Secure=True (browsers reject the
          combination outright, so failing here is clearer than a silent
          no-op in the Set-Cookie header).
        * Outside development, Secure must be True. Development is exempt
          so a developer testing over a plain-HTTP non-localhost host can
          still receive the cookie; every other environment must be
          served over HTTPS with Secure cookies.
        """
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError(
                "auth_cookie_samesite='none' requires auth_cookie_secure=True "
                "(browsers reject SameSite=None without Secure)."
            )
        if self.environment != "development" and not self.auth_cookie_secure:
            raise ValueError(
                f"auth_cookie_secure must be True when environment is "
                f"{self.environment!r}. Secure cookies are required outside "
                "development."
            )
        return self

    @model_validator(mode="after")
    def _validate_smtp_tls_ssl(self) -> "Settings":
        """TLS and SSL modes are mutually exclusive; at least one must be
        in use when email delivery is enabled."""
        if self.smtp_use_tls and self.smtp_use_ssl:
            raise ValueError(
                "smtp_use_tls and smtp_use_ssl are mutually exclusive."
            )
        if self.email_delivery_enabled and not (self.smtp_use_tls or self.smtp_use_ssl):
            raise ValueError(
                "SMTP must use TLS or SSL when email_delivery_enabled is True."
            )
        return self

    @model_validator(mode="after")
    def _validate_smtp_when_enabled(self) -> "Settings":
        """Require a complete SMTP configuration when email delivery is
        enabled. The error names every missing field so the operator can
        fix the configuration in one pass rather than one variable at a
        time."""
        if not self.email_delivery_enabled:
            return self
        missing: List[str] = []
        if not self.smtp_host:
            missing.append("smtp_host")
        if not self.smtp_username:
            missing.append("smtp_username")
        if not self.smtp_password:
            missing.append("smtp_password")
        if not self.smtp_from_address:
            missing.append("smtp_from_address")
        if missing:
            raise ValueError(
                "email_delivery_enabled=True requires the following SMTP "
                f"settings: {', '.join(missing)}."
            )
        return self

    # ------------------------------------------------------------------ #
    # Startup helpers
    # ------------------------------------------------------------------ #
    def init_directories(self) -> None:
        """Create output, log, and SQLite parent directories."""
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url[len("sqlite:///"):]
            if db_path and db_path != ":memory:":
                db_p = Path(db_path)
                if not db_p.is_absolute():
                    db_p = _REPO_ROOT / db_p
                parent = db_p.parent
                if parent and str(parent):
                    os.makedirs(parent, exist_ok=True)

    def describe_llm_configuration(self) -> dict:
        """Log-friendly summary of the effective LLM routing."""
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