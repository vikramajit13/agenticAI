"""LangGraph nodes for the requirements workflow."""

from app.config import get_settings
from app.domain.models import Epic
from app.logging import get_logger
from app.orchestration.common.state import ExtractedContext
from app.orchestration.common.state import RequirementsWorkflowState
from app.services.llm_service import LLMService
from app.services.parser import normalize_text
from app.services.parser import parse_requirements


logger = get_logger(__name__)
settings = get_settings()
llm_service = LLMService(settings)


def ingest_input(state: RequirementsWorkflowState) -> dict[str, object]:
    """Normalize incoming text and split it into sections."""
    normalized_text = normalize_text(state.raw_text)
    sections = parse_requirements(state.raw_text)
    logger.info("Ingested input into %s sections", len(sections))
    return {
        "normalized_text": normalized_text,
        "sections": sections,
    }


async def extract_context(state: RequirementsWorkflowState) -> dict[str, object]:
    """Extract actors, goals, features, and constraints."""
    extracted = await llm_service.extract_requirements(
        state.normalized_text,
        state.sections,
    )
    return {"extracted_context": ExtractedContext(**extracted)}


async def generate_epics_and_stories(
    state: RequirementsWorkflowState,
) -> dict[str, object]:
    """Generate epics and story shells from extracted context."""
    extracted = state.extracted_context.model_dump()
    epics = await llm_service.generate_epics_and_stories(extracted)
    return {"epics": epics}


async def generate_acceptance_criteria(
    state: RequirementsWorkflowState,
) -> dict[str, object]:
    """Attach acceptance criteria to each story."""
    extracted = state.extracted_context.model_dump()
    epics = await llm_service.generate_acceptance_criteria(state.epics, extracted)
    return {"epics": epics}


async def detect_dependencies(state: RequirementsWorkflowState) -> dict[str, object]:
    """Attach dependencies to each story."""
    extracted = state.extracted_context.model_dump()
    epics = llm_service.derive_dependencies(state.epics, extracted)
    summary = llm_service.build_summary(extracted, epics)
    return {
        "epics": epics,
        "summary": summary,
    }


async def find_open_questions(state: RequirementsWorkflowState) -> dict[str, object]:
    """Identify missing information and assumptions from the current draft."""
    extracted = state.extracted_context.model_dump()
    result = llm_service.derive_open_questions(extracted, state.epics)
    return {
        "open_questions": result["open_questions"],
        "assumptions": result["assumptions"],
    }


def build_fallback_state(raw_text: str) -> RequirementsWorkflowState:
    """Construct a minimal fallback state for defensive use."""
    normalized_text = normalize_text(raw_text)
    sections = parse_requirements(raw_text)
    extracted = ExtractedContext()
    epics: list[Epic] = llm_service._fallback_backlog(extracted.model_dump())
    return RequirementsWorkflowState(
        raw_text=raw_text,
        normalized_text=normalized_text,
        sections=sections,
        extracted_context=extracted,
        epics=epics,
        open_questions=[],
        assumptions=[],
        summary=llm_service.build_summary(extracted.model_dump(), epics),
    )
