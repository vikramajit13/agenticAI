"""API routes for requirements-related operations."""

import json
import httpx
from fastapi import APIRouter
from fastapi import HTTPException

from app.config import get_settings
from app.logging import get_logger
from app.orchestration.common.state import RequirementsWorkflowState
from app.orchestration.requirements_graph import requirements_graph
from app.schemas.debug import GraphStateResponse
from app.schemas.requests import RequirementsRequest
from app.schemas.responses import ExtractionSummary
from app.schemas.responses import RequirementsResponse


router = APIRouter(prefix="/requirements", tags=["requirements"])
logger = get_logger(__name__)


async def _run_requirements_graph(payload: RequirementsRequest) -> RequirementsWorkflowState:
    """Invoke the compiled requirements graph and validate the result."""
    graph_state = await requirements_graph.ainvoke(
        RequirementsWorkflowState(raw_text=payload.text).model_dump()
    )
    return RequirementsWorkflowState.model_validate(graph_state)


@router.post("/generate", response_model=RequirementsResponse)
async def parse_requirements_endpoint(
    payload: RequirementsRequest,
) -> RequirementsResponse:
    """Run the LangGraph workflow and return the final state."""
    settings = get_settings()

    try:
        workflow_state = await _run_requirements_graph(payload)
    except httpx.HTTPError as exc:
        logger.exception("Ollama request failed")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Ollama at {settings.ollama_base_url}",
        ) from exc
    except json.JSONDecodeError as exc:
        logger.exception("Ollama returned invalid JSON")
        raise HTTPException(
            status_code=502,
            detail="Ollama returned invalid JSON output",
        ) from exc

    return RequirementsResponse(
        summary=workflow_state.summary,
        extracted=ExtractionSummary(**workflow_state.extracted_context.model_dump()),
        epics=workflow_state.epics,
        open_questions=workflow_state.open_questions,
        assumptions=workflow_state.assumptions,
        normalized_text=workflow_state.normalized_text,
        sections=workflow_state.sections,
    )


@router.post("/graph-state", response_model=GraphStateResponse)
async def graph_state_endpoint(payload: RequirementsRequest) -> GraphStateResponse:
    """Return the final LangGraph workflow state for debugging."""
    settings = get_settings()

    try:
        workflow_state = await _run_requirements_graph(payload)
    except httpx.HTTPError as exc:
        logger.exception("Ollama request failed")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Ollama at {settings.ollama_base_url}",
        ) from exc
    except json.JSONDecodeError as exc:
        logger.exception("Ollama returned invalid JSON")
        raise HTTPException(
            status_code=502,
            detail="Ollama returned invalid JSON output",
        ) from exc

    return GraphStateResponse(state=workflow_state)
