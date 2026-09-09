"""
Configuration settings for ERP Consultant Agent
"""
import os
from typing import Optional, List, ClassVar
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    # Gemini API Configuration
    gemini_api_key: str = Field(..., description="Gemini API Key")
    
    # Groq API Configuration (secondary fallback - free tier)
    groq_api_key: Optional[str] = Field(None, description="Groq API Key for secondary (free) fallback LLM")
    groq_model: str = Field(default="openai/gpt-oss-20b", description="Groq model for the secondary fallback tier")
    
    # OpenAI API Configuration (tertiary fallback)
    openai_api_key: Optional[str] = Field(None, description="OpenAI API Key for tertiary fallback LLM")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model for the tertiary fallback tier")
    
    # Anthropic API Configuration (quaternary fallback)
    anthropic_api_key: Optional[str] = Field(None, description="Anthropic API Key for quaternary fallback LLM")
    anthropic_model: str = Field(default="claude-sonnet-4-6", description="Anthropic model for the quaternary fallback tier")
    
    # SerpApi
    serpapi_api_key: str = Field(..., description="SerpApi API Key")
    
    # LLM / Model Configuration
    gemini_model: str = Field(default="gemini-3.7-flash", description="Default Gemini model to use")
    
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8192, gt=0)
    
    # Agent Configuration
    max_iterations: int = Field(default=10, gt=0)
    # Phase-level ceiling: bounds one whole agent phase call (tool use +
    # LLM calls + document generation), wired into
    # ERPOrchestratorAgent._call_agent_safely via run_with_timeout.
    timeout_seconds: int = Field(default=300, gt=0)
    # LLM-call-level settings: bound and harden individual provider calls,
    # wired into HybridLLMClient (see src/utils/llm.py). Deliberately
    # smaller than timeout_seconds - several of these can happen inside
    # one phase (retries, provider fallback) and must still fit inside the
    # phase-level ceiling above with room to spare.
    llm_call_timeout_seconds: int = Field(default=60, gt=0)
    llm_retry_attempts: int = Field(default=2, gt=0)
    
    # Logging Configuration
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")
    
    # Memory Configuration
    memory_enabled: bool = Field(default=True)
    max_memory_items: int = Field(default=100, gt=0)
    max_conversation_history_items: int = Field(
        default=200, gt=0,
        description="Maximum conversation turns kept per session before oldest entries are trimmed"
    )
    
    # Application Settings
    project_name: str = Field(default="ERP Consultant Agent")
    environment: str = Field(default="development")
    
    # Agent-specific settings
    enable_google_search: bool = Field(default=True)
    
    # Output directories
    output_dir: str = Field(default="output")
    logs_dir: str = Field(default="logs")
    
    # Database - defaults to a local SQLite file so the app runs with zero
    # external setup; set to a Postgres DSN in production
    # (postgresql+psycopg2://user:pass@host:5432/dbname).
    database_url: str = Field(default="sqlite:///output/erp_agent.db")

    # API security
    api_auth_key: Optional[str] = Field(
        default=None,
        description="Deprecated: static shared API key. Superseded by per-user JWT auth "
                    "(see jwt_secret_key). Kept only so old .env files don't fail to load; "
                    "no endpoint checks it anymore."
    )
    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="Comma-separated list of allowed CORS origins"
    )

    # JWT auth (per-user accounts)
    jwt_secret_key: str = Field(..., description="Secret key used to sign access tokens - required, no default")
    jwt_algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(
        default=1440, gt=0,
        description="Access token lifetime in minutes (default 24h). No refresh-token flow yet - "
                    "a user simply logs in again once expired."
    )
    
    @property
    def allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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

    def init_directories(self) -> None:
        """Create output and log directories. Call once at application startup."""
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

class AgentConfig:
    """Configuration for individual agents"""
    def __init__(
        self,
        name: str,
        description: str,
        temperature: float = 0.7,
        max_iterations: int = 5,
        tools: Optional[List[str]] = None
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
    tools=["google_search", "document_analyzer"]
)

PROCESS_MAPPING_AGENT_CONFIG = AgentConfig(
    name="Process Mapping Agent",
    description="Creates detailed business process maps and workflow diagrams",
    temperature=0.4,
    max_iterations=5,
    tools=["process_visualizer", "erp_knowledge_base"]
)

SOLUTION_DESIGN_AGENT_CONFIG = AgentConfig(
    name="Solution Design Agent",
    description="Designs ERP solutions based on requirements and best practices",
    temperature=0.6,
    max_iterations=5,
    tools=["erp_knowledge_base", "google_search"]
)

QA_TESTING_AGENT_CONFIG = AgentConfig(
    name="QA Testing Agent",
    description="Generates comprehensive QA test cases and test scripts",
    temperature=0.3,
    max_iterations=5,
    tools=["test_case_generator"]
)

UAT_TESTING_AGENT_CONFIG = AgentConfig(
    name="UAT Testing Agent",
    description="Creates user acceptance testing scenarios and test scripts",
    temperature=0.4,
    max_iterations=5,
    tools=["test_case_generator", "erp_knowledge_base"]
)

TRAINING_AGENT_CONFIG = AgentConfig(
    name="Training & Documentation Agent",
    description="Creates user manuals, training guides, and process documentation",
    temperature=0.5,
    max_iterations=5,
    tools=["document_generator", "process_visualizer"]
)


# Global settings instance
settings = Settings()