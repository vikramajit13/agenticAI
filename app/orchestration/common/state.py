"""Shared state models for requirements orchestration."""

from pydantic import BaseModel
from pydantic import Field

from app.domain.models import Epic


class Section(BaseModel):
    id: str
    content: str


class ExtractedContext(BaseModel):
    actors: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    source_refs_by_category: dict[str, list[str]] = Field(default_factory=dict)


class RequirementsWorkflowState(BaseModel):
    raw_text: str = ""
    normalized_text: str = ""
    sections: list[Section] = Field(default_factory=list)
    extracted_context: ExtractedContext = Field(default_factory=ExtractedContext)
    completeness_score: float = 0.0
    ambiguity_flags: list[str] = Field(default_factory=list)
    epics: list[Epic] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    summary: str = ""
