"""
Pydantic schema for structured process map output.
Used to constrain and validate Gemini's JSON response for the
Process Mapping Agent.
"""
from typing import List
from pydantic import BaseModel, Field


class ProcessStep(BaseModel):
    number: int
    name: str
    description: str = ""
    transaction: str = ""
    responsible_role: str = ""
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (e.g. 'REQ-001') from the provided requirement list that this step implements. Leave empty if none clearly apply - never guess."
    )


class ProcessMap(BaseModel):
    overview: str
    scope: str
    roles: List[str] = Field(default_factory=list)
    steps: List[ProcessStep] = Field(default_factory=list)
    decision_points: List[str] = Field(default_factory=list)
    integration_points: List[str] = Field(default_factory=list)
    exceptions: List[str] = Field(default_factory=list)
    improvements: List[str] = Field(default_factory=list)

