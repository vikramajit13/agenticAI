"""Requirement orchestration graph wiring."""

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from app.orchestration.common.state import RequirementsWorkflowState
from app.orchestration.nodes import assess_requirement_quality
from app.orchestration.nodes import detect_dependencies
from app.orchestration.nodes import extract_context
from app.orchestration.nodes import find_open_questions
from app.orchestration.nodes import generate_acceptance_criteria
from app.orchestration.nodes import generate_epics_and_stories
from app.orchestration.nodes import ingest_input
from app.orchestration.nodes import route_after_quality_check


def build_requirements_graph():
    """Build and compile the requirements workflow graph."""
    builder = StateGraph(RequirementsWorkflowState)
    builder.add_node("ingest_input", ingest_input)
    builder.add_node("extract_context", extract_context)
    builder.add_node("assess_requirement_quality", assess_requirement_quality)
    builder.add_node("generate_epics_and_stories", generate_epics_and_stories)
    builder.add_node("generate_acceptance_criteria", generate_acceptance_criteria)
    builder.add_node("detect_dependencies", detect_dependencies)
    builder.add_node("find_open_questions", find_open_questions)
    builder.add_edge(START, "ingest_input")
    builder.add_edge("ingest_input", "extract_context")
    builder.add_edge("extract_context", "assess_requirement_quality")
    builder.add_conditional_edges(
        "assess_requirement_quality",
        route_after_quality_check,
        {
            "weak": "find_open_questions",
            "strong": "generate_epics_and_stories",
        },
    )
    builder.add_edge("find_open_questions", "generate_epics_and_stories")
    builder.add_edge("generate_epics_and_stories", "generate_acceptance_criteria")
    builder.add_edge("generate_acceptance_criteria", "detect_dependencies")
    builder.add_edge("detect_dependencies", END)
    return builder.compile()


requirements_graph = build_requirements_graph()
