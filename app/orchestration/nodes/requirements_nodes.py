"""LangGraph nodes for the requirements workflow."""

from app.config import get_settings
from app.domain.models import AcceptanceCriterion
from app.domain.models import Epic
from app.domain.models import Story
from app.logging import get_logger
from app.orchestration.common.state import ExtractedContext
from app.orchestration.common.state import RequirementsWorkflowState
from app.orchestration.common.state import ReviewWorkflowState
from app.services.llm_service import LLMService
from app.services.parser import normalize_text
from app.services.parser import parse_requirements
from app.domain.constants import Action


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


def assess_requirement_quality(state: RequirementsWorkflowState) -> dict[str, object]:
    """Score requirement quality and capture ambiguity flags."""
    return llm_service.assess_requirement_quality(
        state.normalized_text,
        state.extracted_context.model_dump(),
    )


def route_after_quality_check(state: RequirementsWorkflowState) -> str:
    """Route weak requirements to an early question pass."""
    if state.completeness_score < 0.75 or state.ambiguity_flags:
        return "weak"
    return "strong"

def route_after_review_action(state: RequirementsWorkflowState) -> str:
    """Route to appropriate node based on human review action."""
    if state.action == Action.REGENERATEAC:
        return "regenerate"
    # Future actions like SPLITSTORY or TECHNICALSTORY would be handled here
    return "generate_epics_and_stories"  # Default route if no specific action
   

async def generate_epics_and_stories(
    state: RequirementsWorkflowState,
) -> dict[str, object]:
    """Generate epics and story shells from extracted context."""
    extracted = state.extracted_context.model_dump()
    epics = await llm_service.generate_epics_and_stories(extracted, state.sections)
    ambiguity_flags = list(state.ambiguity_flags)
    if any(not story.source_refs for epic in epics for story in epic.stories):
        ambiguity_flags.append("ungrounded_story_output")
    return {
        "epics": epics,
        "ambiguity_flags": sorted(set(ambiguity_flags)),
    }


async def generate_acceptance_criteria(
    state: RequirementsWorkflowState,
) -> dict[str, object]:
    """Attach acceptance criteria to each story."""
    extracted = state.extracted_context.model_dump()
    epics = await llm_service.generate_acceptance_criteria(
        state.epics,
        extracted,
        state.sections,
    )
    return {"epics": epics}


async def detect_dependencies(state: RequirementsWorkflowState) -> dict[str, object]:
    """Attach dependencies to each story."""
    extracted = state.extracted_context.model_dump()
    epics = llm_service.derive_dependencies(state.epics, extracted)
    summary = llm_service.build_summary(extracted, epics)
    ambiguity_flags = list(state.ambiguity_flags)
    if any(
        dependency and not dependency.source_refs
        for epic in epics
        for story in epic.stories
        for dependency in story.dependencies
    ):
        ambiguity_flags.append("ungrounded_dependency_output")
    return {
        "epics": epics,
        "summary": summary,
        "ambiguity_flags": sorted(set(ambiguity_flags)),
    }


async def find_open_questions(state: RequirementsWorkflowState) -> dict[str, object]:
    """Identify missing information and assumptions from the current draft."""
    extracted = state.extracted_context.model_dump()
    result = llm_service.derive_open_questions(
        extracted,
        state.epics,
        ambiguity_flags=state.ambiguity_flags,
        completeness_score=state.completeness_score,
    )
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
        completeness_score=0.0,
        ambiguity_flags=[],
        epics=epics,
        open_questions=[],
        assumptions=[],
        summary=llm_service.build_summary(extracted.model_dump(), epics),
    )


def route_after_review_action(state: ReviewWorkflowState) -> str:
    """Route to the appropriate review node."""
    if state.action == Action.REGENERATEAC:
        return "regenerate_ac_for_story"
    if state.action == Action.SPLITSTORY:
        return "split_story_in_two"
    if state.action == Action.TECHNICALSTORY:
        return "rewrite_story_technically"
    return "no_review_action"


async def regenerate_ac_for_story(state: ReviewWorkflowState) -> dict[str, object]:
    """Regenerate acceptance criteria for a single story."""
    updated_state = state.workflow_state.model_copy(deep=True)
    target = _find_story(updated_state, state.story_title)
    if target is None:
        return _flag_missing_story(updated_state, state.story_title)

    regenerated = await llm_service.regenerate_acceptance_criteria_for_story(target)
    _replace_story(updated_state, state.story_title, regenerated)
    updated_state.summary = f"Regenerated acceptance criteria for story '{state.story_title}'."
    return {"workflow_state": updated_state}


async def split_story_in_two(state: ReviewWorkflowState) -> dict[str, object]:
    """Split a single story into two smaller stories."""
    updated_state = state.workflow_state.model_copy(deep=True)
    target = _find_story(updated_state, state.story_title)
    if target is None:
        return _flag_missing_story(updated_state, state.story_title)

    split_stories = await llm_service.split_story_in_two(target, state.instructions)
    _replace_story_with_many(updated_state, state.story_title, split_stories)
    updated_state.summary = f"Split story '{state.story_title}' into {len(split_stories)} stories."
    return {"workflow_state": updated_state}


async def rewrite_story_technically(state: ReviewWorkflowState) -> dict[str, object]:
    """Rewrite a story in a more technical implementation-oriented style."""
    updated_state = state.workflow_state.model_copy(deep=True)
    target = _find_story(updated_state, state.story_title)
    if target is None:
        return _flag_missing_story(updated_state, state.story_title)

    rewritten = await llm_service.rewrite_story_technically(target, state.instructions)
    _replace_story(updated_state, state.story_title, rewritten)
    updated_state.summary = f"Rewrote story '{state.story_title}' technically."
    return {"workflow_state": updated_state}


def no_review_action(state: ReviewWorkflowState) -> dict[str, object]:
    """Pass the state through unchanged when no action is selected."""
    return {"workflow_state": state.workflow_state}


def _find_story(state: RequirementsWorkflowState, story_title: str) -> Story | None:
    for epic in state.epics:
        for story in epic.stories:
            if story.title == story_title:
                return story
    return None


def _replace_story(
    state: RequirementsWorkflowState,
    story_title: str,
    replacement: Story,
) -> None:
    for epic in state.epics:
        for index, story in enumerate(epic.stories):
            if story.title == story_title:
                epic.stories[index] = replacement
                return


def _replace_story_with_many(
    state: RequirementsWorkflowState,
    story_title: str,
    replacements: list[Story],
) -> None:
    for epic in state.epics:
        for index, story in enumerate(epic.stories):
            if story.title == story_title:
                epic.stories[index:index + 1] = replacements
                return


def _flag_missing_story(
    state: RequirementsWorkflowState,
    story_title: str,
) -> dict[str, object]:
    flags = sorted(set(state.ambiguity_flags + ["review_story_not_found"]))
    state.ambiguity_flags = flags
    state.open_questions = list(state.open_questions) + [
        f"Could not find a story titled '{story_title}' in the prior graph state."
    ]
    state.summary = f"Review action could not be applied because story '{story_title}' was not found."
    return {"workflow_state": state}
