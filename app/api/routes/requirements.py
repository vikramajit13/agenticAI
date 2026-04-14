"""API routes for requirements-related operations."""

import json
import httpx
from fastapi import APIRouter
from fastapi import HTTPException

from app.config import get_settings
from app.logging import get_logger
from app.schemas.requests import RequirementsRequest
from app.schemas.responses import RequirementsResponse
from app.services.llm_service import LLMService
from app.services.parser import normalize_text
from app.services.parser import parse_requirements


router = APIRouter(prefix="/requirements", tags=["requirements"])
logger = get_logger(__name__)


@router.post("/generate", response_model=RequirementsResponse)
async def parse_requirements_endpoint(
    payload: RequirementsRequest,
) -> RequirementsResponse:
    """Parse text and generate rough stories and acceptance criteria."""
    settings = get_settings()
    llm_service = LLMService(settings)

    normalized_text = normalize_text(payload.text)
    sections = parse_requirements(payload.text)
    logger.info("Processing requirements text sections=%s", len(sections))

    try:
        extracted = await llm_service.extract_requirements(normalized_text, sections)
        print("Extracted requirements:", extracted)  # Debug log for extracted data
        story_texts = await llm_service.generate_stories(extracted)
        print("Generated story texts:", story_texts)  # Debug log for generated stories
        stories = await llm_service.generate_acceptance_criteria(
            story_texts,
            extracted,
        )
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
        summary=llm_service.build_summary(extracted, stories),
        extracted=llm_service.build_extraction_summary(extracted),
        stories=stories,
        normalized_text=normalized_text,
        sections=sections,
    )
