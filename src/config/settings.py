"""
Configuration settings for ERP Consultant Agent
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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
    serpapi_api_key: str = Field(..., description="SerpApi API Key")
    gemini_model: str = Field(
        default="gemini-2.0-flash-exp",
        description="Gemini model to use"
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=8192, gt=0)
    
    # Agent Configuration
    max_iterations: int = Field(default=10, gt=0)
    timeout_seconds: int = Field(default=300, gt=0)
    
    # Logging Configuration
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")
    
    # Memory Configuration
    memory_enabled: bool = Field(default=True)
    max_memory_items: int = Field(default=100, gt=0)
    
    # Application Settings
    project_name: str = Field(default="ERP Consultant Agent")
    environment: str = Field(default="development")
    
    # Agent-specific settings
    enable_google_search: bool = Field(default=True)
    enable_code_execution: bool = Field(default=True)
    
    # Output directories
    output_dir: str = Field(default="output")
    logs_dir: str = Field(default="logs")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Create output directories if they don't exist
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
        tools: Optional[list] = None
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
    tools=["test_case_generator", "code_execution"]
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