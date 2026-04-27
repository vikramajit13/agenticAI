"""Response schema definitions."""

from pydantic import BaseModel
from pydantic import Field

from app.domain.models import Epic
from app.orchestration.common.state import ExtractedContext
from app.orchestration.common.state import Section


class ExtractionSummary(BaseModel):
    actors: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    source_refs_by_category: dict[str, list[str]] = Field(default_factory=dict)


class StoryDraft(BaseModel):
    story: str
    acceptance_criteria: list[str] = Field(default_factory=list)


class RequirementsResponse(BaseModel):
    summary: str
    extracted: ExtractionSummary | ExtractedContext
    completeness_score: float = 0.0
    ambiguity_flags: list[str] = Field(default_factory=list)
    epics: list[Epic] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    normalized_text: str
    sections: list[Section] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
