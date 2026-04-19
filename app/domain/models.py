"""Domain models for backlog generation."""

from pydantic import BaseModel
from pydantic import Field


class AcceptanceCriterion(BaseModel):
    text: str = Field(..., min_length=1)


class Dependency(BaseModel):
    name: str = Field(..., min_length=1)
    dependency_type: str = Field(default="relates_to", min_length=1)


class Story(BaseModel):
    title: str = Field(..., min_length=1)
    story: str = Field(..., min_length=1)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)


class Epic(BaseModel):
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    stories: list[Story] = Field(default_factory=list)
