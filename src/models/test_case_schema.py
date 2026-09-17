"""
Pydantic schema for structured test case output.
Shared by the QA Testing Agent and UAT Testing Agent, since both
feed the same document_generator.generate_test_case_document().
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class TestDataItem(BaseModel):
    key: str
    value: str


class TestCase(BaseModel):
    id: str
    scenario: str
    priority: str = "Medium"
    type: str = "Functional"
    objective: str = ""
    preconditions: List[str] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    test_data: List[TestDataItem] = Field(default_factory=list)
    expected_result: str = ""
    related_requirement_ids: List[str] = Field(
        default_factory=list,
        description="Requirement ID codes (e.g. 'REQ-001') from the provided requirement list that this test case validates. Leave empty if none clearly apply - never guess."
    )
    execution_status: str = Field(
        default="not_run",
        description="One of: not_run, passed, failed. Only set to passed/failed if the requirements or context explicitly describe a test outcome - otherwise leave as not_run; never guess a result."
    )
    failure_classification: Optional[str] = Field(
        default=None,
        description="Only set if execution_status is 'failed'. One of: defect, unclear_requirement, changed_requirement, data_issue, integration_issue, environment_issue, other."
    )
    failure_description: Optional[str] = Field(
        default=None,
        description="Only set if execution_status is 'failed'. A concrete description of what went wrong, grounded in the given context - never fabricated."
    )

    def to_legacy_dict(self) -> dict:
        data = self.model_dump()
        data["test_data"] = {item["key"]: item["value"] for item in data.pop("test_data")}
        return data


class TestCasesDocument(BaseModel):
    test_cases: List[TestCase] = Field(default_factory=list)