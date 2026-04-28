"""API routes for requirements-related operations."""

import json
import httpx
from fastapi import APIRouter
from fastapi import HTTPException

from app.config import get_settings
from app.logging import get_logger
from app.orchestration.common.state import RequirementsWorkflowState
from app.orchestration.common.state import ReviewWorkflowState
from app.orchestration.requirements_graph import requirements_graph
from app.orchestration.requirements_graph import review_graph
from app.schemas.debug import GraphStateResponse
from app.schemas.requests import RequirementsRequest
from app.schemas.requests import ReviewActionRequest
from app.schemas.responses import ExtractionSummary
from app.schemas.responses import RequirementsResponse


router = APIRouter(prefix="/requirements", tags=["requirements"])
review_router = APIRouter(prefix="/api/v1", tags=["review"])
logger = get_logger(__name__)



async def _run_requirements_graph(payload: RequirementsRequest) -> RequirementsWorkflowState:
    """Invoke the compiled requirements graph and validate the result."""
    graph_state = await requirements_graph.ainvoke(
        RequirementsWorkflowState(raw_text=payload.text).model_dump()
    )
    return RequirementsWorkflowState.model_validate(graph_state)


async def _run_review_graph(payload: ReviewActionRequest) -> RequirementsWorkflowState:
    """Invoke the compiled review graph and validate the resulting workflow state."""
    review_state = await review_graph.ainvoke(
        ReviewWorkflowState(
            workflow_state=payload.prior_state,
            action=payload.action,
            story_title=payload.story_title,
            instructions=payload.instructions,
        ).model_dump()
    )
    validated = ReviewWorkflowState.model_validate(review_state)
    return validated.workflow_state


def _to_requirements_response(workflow_state: RequirementsWorkflowState) -> RequirementsResponse:
    return RequirementsResponse(
        summary=workflow_state.summary,
        extracted=ExtractionSummary(**workflow_state.extracted_context.model_dump()),
        completeness_score=workflow_state.completeness_score,
        ambiguity_flags=workflow_state.ambiguity_flags,
        epics=workflow_state.epics,
        open_questions=workflow_state.open_questions,
        assumptions=workflow_state.assumptions,
        normalized_text=workflow_state.normalized_text,
        sections=workflow_state.sections,
    )


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

    return _to_requirements_response(workflow_state)


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


@review_router.post("/review-action", response_model=RequirementsResponse)
async def review_action_endpoint(
    payload: ReviewActionRequest,
) -> RequirementsResponse:
    """Run a review action against a prior workflow state."""
    settings = get_settings()

    try:
        workflow_state = await _run_review_graph(payload)
    except httpx.HTTPError as exc:
        logger.exception("Ollama request failed during review action")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach Ollama at {settings.ollama_base_url}",
        ) from exc
    except json.JSONDecodeError as exc:
        logger.exception("Ollama returned invalid JSON during review action")
        raise HTTPException(
            status_code=502,
            detail="Ollama returned invalid JSON output",
        ) from exc

    return _to_requirements_response(workflow_state)
