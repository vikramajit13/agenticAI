"""Debug-oriented schema definitions."""

from pydantic import BaseModel

from app.orchestration.common.state import RequirementsWorkflowState


class GraphStateResponse(BaseModel):
    state: RequirementsWorkflowState
