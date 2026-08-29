"""
Pydantic schema for classifying chat intent. Used by the /api/chat
endpoint to replace brittle keyword matching (Stage 5 finding: any
message containing the word "training" used to hijack unrelated
questions into generating a canned document) with real LLM-driven
intent understanding, while keeping execution fully deterministic -
the LLM only picks from a fixed set of known actions, it never
executes anything itself.
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ChatIntent(str, Enum):
    START_PROJECT = "start_project"
    RUN_PHASE = "run_phase"
    GENERATE_TRAINING = "generate_training"
    ASK_QUESTION = "ask_question"


class ChatIntentDecision(BaseModel):
    intent: ChatIntent
    project_name: Optional[str] = Field(
        default=None, description="Only for start_project - the project name if the user gave one"
    )
    phase: Optional[str] = Field(
        default=None,
        description="Only for run_phase - one of: requirements, process_mapping, solution_design, qa_testing, uat_testing, training"
    )