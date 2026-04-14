"""Request schema definitions."""

from pydantic import BaseModel
from pydantic import Field


class RequirementsRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw requirements text")
