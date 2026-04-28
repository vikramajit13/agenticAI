"""Request schema definitions."""

from pydantic import BaseModel
from pydantic import Field

from app.domain.constants import Action
from app.orchestration.common.state import RequirementsWorkflowState


class RequirementsRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw requirements text")


class ReviewActionRequest(BaseModel):
    prior_state: RequirementsWorkflowState
    action: Action
    story_title: str = Field(..., min_length=1)
    instructions: str = ""
