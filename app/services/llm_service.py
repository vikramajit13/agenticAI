"""LLM service integration layer."""

import json
import re
from typing import Any

import httpx

from app.config import Settings
from app.logging import get_logger
from app.schemas.responses import ExtractionSummary
from app.schemas.responses import StoryDraft


logger = get_logger(__name__)


class LLMService:
    """Ollama-backed service for requirements analysis and generation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract_requirements(self, text: str, sections: list[str]) -> dict[str, list[str]]:
        prompt = (
            "You extract structured requirement details from product notes.\n"
            "Return strict JSON with keys: actors, goals, features, constraints.\n"
            "Each value must be an array of short strings.\n"
            "Do not include markdown or explanation.\n\n"
            f"Full text:\n{text}\n\n"
            f"Parsed sections:\n{json.dumps(sections, ensure_ascii=True)}"
        )
        result = await self._generate_json(prompt)
        return {
            "actors": self._ensure_string_list(result.get("actors")),
            "goals": self._ensure_string_list(result.get("goals")),
            "features": self._ensure_string_list(result.get("features")),
            "constraints": self._ensure_string_list(result.get("constraints")),
        }

    async def generate_stories(self, extracted: dict[str, list[str]]) -> list[str]:
        prompt = (
            "You generate backlog-ready rough user stories from extracted requirement data.\n"
            "Return strict JSON with one key: stories.\n"
            "stories must be an array of strings in the format "
            "'As a <actor>, I want <goal>, so that <benefit>'.\n"
            "Every story must start with 'As a' or 'As an'.\n"
            "Write 2 to 5 stories.\n"
            "Prefer explicit actors from the input. Infer a short benefit when needed.\n"
            "Do not return fragments, titles, bullets, or feature names by themselves.\n"
            "Do not include markdown or explanation.\n\n"
            f"Extracted data:\n{json.dumps(extracted, ensure_ascii=True)}"
        )
        result = await self._generate_json(prompt)
        return self._normalize_stories(self._ensure_string_list(result.get("stories")), extracted)

    async def generate_acceptance_criteria(
        self,
        stories: list[str],
        extracted: dict[str, list[str]],
    ) -> list[StoryDraft]:
        prompt = (
            "You generate acceptance criteria for rough user stories.\n"
            "Return strict JSON with one key: acceptance_criteria.\n"
            "acceptance_criteria must be an array where each item is an object "
            "with keys story and criteria. criteria must be an array of short strings.\n"
            "Each criterion must use Given/When/Then wording and be concrete and testable.\n"
            "Return 2 to 4 criteria per story.\n"
            "Do not include markdown or explanation.\n\n"
            f"Stories:\n{json.dumps(stories, ensure_ascii=True)}\n\n"
            f"Extracted data:\n{json.dumps(extracted, ensure_ascii=True)}"
        )
        result = await self._generate_json(prompt)
        raw_items = result.get("acceptance_criteria", [])
        grouped: list[StoryDraft] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict):
                    story = str(item.get("story", "")).strip()
                    criteria = self._normalize_criteria(
                        self._ensure_string_list(item.get("criteria"))
                    )
                    if story:
                        grouped.append(
                            StoryDraft(story=story, acceptance_criteria=criteria)
                        )
        if not grouped:
            return [
                StoryDraft(
                    story=story,
                    acceptance_criteria=self._fallback_criteria(story),
                )
                for story in stories
            ]
        return self._align_story_drafts(stories, grouped)

    def build_summary(
        self,
        extracted: dict[str, list[str]],
        stories: list[StoryDraft],
    ) -> str:
        actors = ", ".join(extracted.get("actors", [])[:2]) or "users"
        feature_count = len(extracted.get("features", []))
        story_count = len(stories)
        return (
            f"Generated {story_count} rough user stories for {actors}, "
            f"covering {feature_count} key feature areas."
        )

    def build_extraction_summary(
        self,
        extracted: dict[str, list[str]],
    ) -> ExtractionSummary:
        return ExtractionSummary(
            actors=extracted.get("actors", []),
            goals=extracted.get("goals", []),
            features=extracted.get("features", []),
            constraints=extracted.get("constraints", []),
        )

    def _align_story_drafts(
        self,
        stories: list[str],
        generated: list[StoryDraft],
    ) -> list[StoryDraft]:
        by_story = {draft.story: draft for draft in generated}
        aligned: list[StoryDraft] = []
        for story in stories:
            draft = by_story.get(story)
            if draft:
                aligned.append(draft)
            else:
                aligned.append(
                    StoryDraft(
                        story=story,
                        acceptance_criteria=self._fallback_criteria(story),
                    )
                )
        return aligned

    def _normalize_stories(
        self,
        stories: list[str],
        extracted: dict[str, list[str]],
    ) -> list[str]:
        normalized: list[str] = []
        actors = extracted.get("actors", [])
        goals = extracted.get("goals", [])

        for index, story in enumerate(stories):
            cleaned = " ".join(story.split())
            if not cleaned:
                continue
            if cleaned.lower().startswith("as a ") or cleaned.lower().startswith("as an "):
                normalized.append(cleaned)
                continue

            actor = actors[min(index, len(actors) - 1)] if actors else "user"
            goal = cleaned.rstrip(".")
            benefit = goals[0].rstrip(".") if goals else "the team can act on the requirement"
            article = "an" if actor[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
            normalized.append(
                f"As {article} {actor}, I want {goal}, so that {benefit}."
            )

        return normalized

    def _normalize_criteria(self, criteria: list[str]) -> list[str]:
        normalized: list[str] = []
        for criterion in criteria:
            cleaned = " ".join(criterion.split())
            if not cleaned:
                continue
            if cleaned.lower().startswith("given "):
                normalized.append(cleaned)
            else:
                normalized.append(f"Given a valid request, when processing runs, then {cleaned.rstrip('.')}.")
        return normalized

    def _fallback_criteria(self, story: str) -> list[str]:
        goal = self._extract_goal_fragment(story)
        return [
            f"Given valid requirement text is submitted, when the service processes the request, then the response includes the story '{story}'.",
            f"Given the story '{story}', when acceptance criteria are generated, then each criterion is testable and uses Given/When/Then wording.",
            f"Given the goal '{goal}', when the response is returned, then it aligns with the extracted actors, goals, features, and constraints.",
        ]

    def _extract_goal_fragment(self, story: str) -> str:
        match = re.search(r"I want (.*?), so that", story)
        if match:
            return match.group(1)
        return story

    async def _generate_json(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        headers = {}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.settings.ollama_base_url}/api/generate",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()

        raw_response = body.get("response", "{}")
        logger.info("Received Ollama response model=%s", self.settings.llm_model)
        parsed = json.loads(raw_response)
        return parsed if isinstance(parsed, dict) else {}

    def _ensure_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
