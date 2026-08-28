"""
Pydantic schema for structured test case output.
Shared by the QA Testing Agent and UAT Testing Agent, since both
feed the same document_generator.generate_test_case_document().
"""
from typing import List
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

    def to_legacy_dict(self) -> dict:
        data = self.model_dump()
        data["test_data"] = {item["key"]: item["value"] for item in data.pop("test_data")}
        return data


class TestCasesDocument(BaseModel):
    test_cases: List[TestCase] = Field(default_factory=list)