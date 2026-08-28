"""
Pydantic schema for structured process map output.
Used to constrain and validate Gemini's JSON response for the
Process Mapping Agent.
"""
from typing import List
from pydantic import BaseModel, Field
from pydantic import ValidationError
from src.models.process_map_schema import ProcessMap


class ProcessStep(BaseModel):
    number: int
    name: str
    description: str = ""
    transaction: str = ""
    responsible_role: str = ""


class ProcessMap(BaseModel):
    overview: str
    scope: str
    roles: List[str] = Field(default_factory=list)
    steps: List[ProcessStep] = Field(default_factory=list)
    decision_points: List[str] = Field(default_factory=list)
    integration_points: List[str] = Field(default_factory=list)
    exceptions: List[str] = Field(default_factory=list)
    improvements: List[str] = Field(default_factory=list)