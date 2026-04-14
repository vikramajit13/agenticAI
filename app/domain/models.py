"""Domain models for requirements processing."""

from dataclasses import dataclass


@dataclass
class Requirement:
    text: str
