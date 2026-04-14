"""Response schema definitions."""

from pydantic import BaseModel
from pydantic import Field


class ExtractionSummary(BaseModel):
    actors: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class StoryDraft(BaseModel):
    story: str
    acceptance_criteria: list[str] = Field(default_factory=list)


class RequirementsResponse(BaseModel):
    summary: str
    extracted: ExtractionSummary
    stories: list[StoryDraft] = Field(default_factory=list)
    normalized_text: str
    sections: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
