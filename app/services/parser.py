"""Parsing helpers for incoming requirement payloads."""

import re

from app.orchestration.common.state import Section


def normalize_text(raw_text: str) -> str:
    """Collapse whitespace while preserving paragraph breaks."""
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def split_into_sections(normalized_text: str) -> list[Section]:
    """Split text into rough sections using headings and paragraph breaks."""
    if not normalized_text:
        return []

    sections: list[Section] = []
    seen_contents: set[str] = set()
    heading: str | None = None
    section_counter = 1

    for block in normalized_text.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        first_line = lines[0]
        is_heading = len(lines) == 1 and (
            first_line.endswith(":")
            or first_line.isupper()
            or (len(first_line.split()) <= 8 and not first_line.endswith("."))
        )

        if is_heading:
            heading = first_line.rstrip(":")
            continue

        paragraph = "\n".join(lines).strip()
        content = f"{heading}: {paragraph}" if heading else paragraph
        heading = None
        if content in seen_contents:
            continue
        seen_contents.add(content)
        sections.append(Section(id=f"S{section_counter}", content=content))
        section_counter += 1

    if heading:
        if heading not in seen_contents:
            sections.append(Section(id=f"S{section_counter}", content=heading))

    return sections


def parse_requirements(raw_text: str) -> list[Section]:
    """Normalize and split raw requirements text into rough sections."""
    normalized = normalize_text(raw_text)
    return split_into_sections(normalized)
