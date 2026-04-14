"""Parsing helpers for incoming requirement payloads."""

import re


def normalize_text(raw_text: str) -> str:
    """Collapse whitespace while preserving paragraph breaks."""
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def split_into_sections(normalized_text: str) -> list[str]:
    """Split text into rough sections using headings and paragraph breaks."""
    if not normalized_text:
        return []

    sections: list[str] = []
    heading: str | None = None

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
        if heading:
            sections.append(f"{heading}: {paragraph}")
            heading = None
        else:
            sections.append(paragraph)

    if heading:
        sections.append(heading)

    # Preserve order while removing duplicates from repeated blocks.
    seen: set[str] = set()
    deduped: list[str] = []
    for section in sections:
        if section not in seen:
            seen.add(section)
            deduped.append(section)
    return deduped


def parse_requirements(raw_text: str) -> list[str]:
    """Normalize and split raw requirements text into rough sections."""
    normalized = normalize_text(raw_text)
    return split_into_sections(normalized)
