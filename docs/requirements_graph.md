# Requirements Graph

This workflow is currently wired as a simple linear LangGraph pipeline.

```mermaid
flowchart LR
    START([START]) --> INGEST["ingest_input"]
    INGEST --> EXTRACT["extract_context"]
    EXTRACT --> EPICS["generate_epics_and_stories"]
    EPICS --> AC["generate_acceptance_criteria"]
    AC --> DEPS["detect_dependencies"]
    DEPS --> QUESTIONS["find_open_questions"]
    QUESTIONS --> END([END])
```

State keys carried through the graph:

- `raw_text`
- `normalized_text`
- `sections`
- `extracted_context`
- `epics`
- `open_questions`
- `assumptions`
- `summary`
