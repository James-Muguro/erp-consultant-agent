"""Pydantic schemas for the AI-assisted TOR fit response.

Only `LLMFitDraft` is a structured-output schema for the LLM; the other
model is the internal request/response shape used by the service layer.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


FIT_RESPONSE_VALUES = (
    "meets_out_of_the_box",
    "requires_customization",
    "not_supported",
)


class LLMFitDraft(BaseModel):
    """Structured output for the fit-response draft step."""
    fit_response: Literal[
        "meets_out_of_the_box",
        "requires_customization",
        "not_supported",
    ]
    comment: str = Field(
        ...,
        description=(
            "One to three sentences justifying the fit response. "
            "Reference the ERP feature or configuration area. Note any "
            "conflicting prior responses when they were provided as "
            "context, and state why this recommendation resolves them."
        ),
    )


class LLMRerankSelection(BaseModel):
    """Structured output for the firm-knowledge rerank step."""
    selected_indices: List[int] = Field(
        ...,
        description=(
            "Indices of the candidate prior responses most relevant to "
            "the new requirement, ordered from most to least relevant. "
            "Include only indices you are confident are relevant."
        ),
    )


class PriorResponse(BaseModel):
    """A single prior response returned from firm knowledge, for
    presentation to the LLM and to the Business Development."""
    requirement_text: str
    response_text: str
    response_kind: Optional[str] = None
    source_external_code: Optional[str] = None
    category: Optional[str] = None
    created_at_iso: Optional[str] = None