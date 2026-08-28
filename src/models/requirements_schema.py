"""
Pydantic schema for structured requirements output.
Used to constrain and validate Gemini's JSON response for the
Requirements Gathering Agent.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class RequirementItem(BaseModel):
    id: str
    description: str
    priority: str = "Medium"
    type: str = "Functional"
    acceptance_criteria: Optional[str] = None


class FunctionalRequirementCategory(BaseModel):
    category: str
    requirements: List[RequirementItem]


class GeneralRequirementItem(BaseModel):
    id: str
    description: str
    priority: str = "Medium"


class RequirementsDocument(BaseModel):
    executive_summary: str
    business_context: str
    objectives: List[str] = Field(default_factory=list)
    functional_requirements: List[FunctionalRequirementCategory] = Field(default_factory=list)
    technical_requirements: List[GeneralRequirementItem] = Field(default_factory=list)
    integration_requirements: List[GeneralRequirementItem] = Field(default_factory=list)
    reporting_requirements: List[GeneralRequirementItem] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    def to_legacy_dict(self) -> dict:
        """Convert to the dict shape document_generator.py expects,
        where functional_requirements is keyed by category name."""
        data = self.model_dump()
        data["functional_requirements"] = {
            cat["category"]: cat["requirements"]
            for cat in data.pop("functional_requirements")
        }
        return data