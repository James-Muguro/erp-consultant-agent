"""
Pydantic schema for structured solution design output.
Used to constrain and validate Gemini's JSON response for the
Solution Design Agent.
"""
from typing import List
from pydantic import BaseModel, Field


class ConfigurationItem(BaseModel):
    component: str
    description: str = ""
    steps: List[str] = Field(default_factory=list)


class IntegrationItem(BaseModel):
    name: str
    type: str = "Real-time"
    source: str = ""
    target: str = ""
    description: str = ""


class CustomizationItem(BaseModel):
    type: str
    component: str
    description: str = ""
    justification: str = ""


class MasterDataItem(BaseModel):
    data_type: str
    details: str


class TechnicalSpecItem(BaseModel):
    name: str
    value: str


class SecurityDesign(BaseModel):
    overview: str = ""


class MigrationStrategy(BaseModel):
    strategy: str = ""


class SolutionDesign(BaseModel):
    executive_summary: str
    architecture_overview: str
    configurations: List[ConfigurationItem] = Field(default_factory=list)
    master_data: List[MasterDataItem] = Field(default_factory=list)
    integrations: List[IntegrationItem] = Field(default_factory=list)
    security: SecurityDesign = Field(default_factory=SecurityDesign)
    customizations: List[CustomizationItem] = Field(default_factory=list)
    migration: MigrationStrategy = Field(default_factory=MigrationStrategy)
    technical_specs: List[TechnicalSpecItem] = Field(default_factory=list)

    def to_legacy_dict(self) -> dict:
        """Convert to the dict shape document_generator.py expects,
        where master_data and technical_specs are keyed by name."""
        data = self.model_dump()
        data["master_data"] = {
            item["data_type"]: item["details"] for item in data.pop("master_data")
        }
        data["technical_specs"] = {
            item["name"]: item["value"] for item in data.pop("technical_specs")
        }
        return data

class ConfigurationItem(BaseModel):
    component: str
    description: str = ""
    steps: List[str] = Field(default_factory=list)
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (e.g. 'REQ-001') from the provided requirement list that this configuration addresses. Leave empty if none clearly apply - never guess."
    )


class IntegrationItem(BaseModel):
    name: str
    type: str = "Real-time"
    source: str = ""
    target: str = ""
    description: str = ""
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (e.g. 'REQ-001') this integration addresses. Leave empty if none clearly apply - never guess."
    )


class CustomizationItem(BaseModel):
    type: str
    component: str
    description: str = ""
    justification: str = ""
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (e.g. 'REQ-001') this customization addresses. Leave empty if none clearly apply - never guess."
    )