"""
Pydantic schema for structured training materials output.
Used to constrain and validate Gemini's JSON response for the
Training Agent.
"""
from typing import List
from pydantic import BaseModel, Field


class UserManualStep(BaseModel):
    title: str
    transaction: str = ""
    instructions: str = ""
    fields: List[str] = Field(default_factory=list)
    tips: List[str] = Field(default_factory=list)


class UserManual(BaseModel):
    steps: List[UserManualStep] = Field(default_factory=list)
    tips: List[str] = Field(default_factory=list)
    faqs: List[str] = Field(default_factory=list)


class TrainingGuide(BaseModel):
    objectives: List[str] = Field(default_factory=list)
    agenda: List[str] = Field(default_factory=list)
    exercises: List[str] = Field(default_factory=list)


class TrainingMaterials(BaseModel):
    user_manual: UserManual = Field(default_factory=UserManual)
    training_guide: TrainingGuide = Field(default_factory=TrainingGuide)
    quick_reference: str = ""
    sop: str = ""