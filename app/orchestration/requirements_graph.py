"""Requirement orchestration graph wiring."""

from app.orchestration.state import GraphState


def build_requirements_graph() -> GraphState:
    """Return a placeholder graph definition until workflow nodes are added."""
    return {"nodes": [], "edges": []}
