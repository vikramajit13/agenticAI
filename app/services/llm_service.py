"""LLM service integration layer."""

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel
from pydantic import ValidationError

from app.config import Settings
from app.domain.models import AcceptanceCriterion
from app.domain.models import Dependency
from app.domain.models import Epic
from app.domain.models import Story
from app.logging import get_logger
from app.orchestration.common.state import Section
from app.schemas.responses import ExtractionSummary


logger = get_logger(__name__)


class BacklogGeneration(BaseModel):
    epics: list[Epic]


class OpenQuestionResult(BaseModel):
    open_questions: list[str]
    assumptions: list[str]


class ExtractedRequirementsResult(BaseModel):
    actors: list[dict[str, Any]]
    goals: list[dict[str, Any]]
    features: list[dict[str, Any]]
    constraints: list[dict[str, Any]]


class LLMService:
    """Ollama-backed service for requirements analysis and generation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract_requirements(
        self,
        text: str,
        sections: list[Section],
    ) -> dict[str, Any]:
        section_payload = [section.model_dump() for section in sections]
        prompt = (
            "You extract structured requirement details from product notes.\n"
            "Return strict JSON with keys: actors, goals, features, constraints.\n"
            "Each value must be an array of objects with keys: text and source_refs.\n"
            "source_refs must be an array of valid section IDs such as S1 or S2.\n"
            "Only use section IDs that appear in the provided parsed sections.\n"
            "Do not include markdown or explanation.\n\n"
            f"Full text:\n{text}\n\n"
            f"Parsed sections:\n{json.dumps(section_payload, ensure_ascii=True)}\n\n"
            f"JSON schema:\n{json.dumps(ExtractedRequirementsResult.model_json_schema(), ensure_ascii=True)}"
        )
        result = await self._generate_json(
            prompt,
            format_schema=ExtractedRequirementsResult.model_json_schema(),
        )
        valid_section_ids = {section.id for section in sections}
        return {
            "actors": self._extract_grounded_texts(result.get("actors"), valid_section_ids),
            "goals": self._extract_grounded_texts(result.get("goals"), valid_section_ids),
            "features": self._extract_grounded_texts(result.get("features"), valid_section_ids),
            "constraints": self._extract_grounded_texts(result.get("constraints"), valid_section_ids),
            "source_refs_by_category": {
                "actors": self._extract_grounded_refs(result.get("actors"), valid_section_ids),
                "goals": self._extract_grounded_refs(result.get("goals"), valid_section_ids),
                "features": self._extract_grounded_refs(result.get("features"), valid_section_ids),
                "constraints": self._extract_grounded_refs(result.get("constraints"), valid_section_ids),
            },
        }

    async def generate_epics_and_stories(
        self,
        extracted: dict[str, Any],
        sections: list[Section],
    ) -> list[Epic]:
        section_payload = [section.model_dump() for section in sections]
        prompt = (
            "You generate backlog-ready epics and user stories.\n"
            "Return strict JSON with exactly one top-level key: epics.\n"
            "epics must be an array of objects with keys: title, summary, stories.\n"
            "stories must be an array of objects with keys: title, story, acceptance_criteria, dependencies, source_refs.\n"
            "source_refs must be an array of valid section IDs such as S1 or S2.\n"
            "story must be a string in the format 'As a <actor>, I want <goal>, so that <benefit>'.\n"
            "Set acceptance_criteria to an empty array for now.\n"
            "Set dependencies to an empty array for now.\n"
            "Write 1 to 2 epics and 2 to 3 stories per epic.\n"
            "Do not return duplicates, filler, placeholders, markdown, commentary, or empty fields.\n"
            "If the grounding is unclear, return an empty source_refs array rather than making up a reference.\n"
            "Do not include markdown or explanation.\n\n"
            f"Extracted data:\n{json.dumps(extracted, ensure_ascii=True)}\n\n"
            f"Available sections:\n{json.dumps(section_payload, ensure_ascii=True)}\n\n"
            f"JSON schema:\n{json.dumps(BacklogGeneration.model_json_schema(), ensure_ascii=True)}"
        )
        result = await self._generate_json(
            prompt,
            format_schema=BacklogGeneration.model_json_schema(),
        )
        try:
            backlog = BacklogGeneration.model_validate(result)
            return self._clean_epics(
                backlog.epics,
                extracted,
                valid_section_ids={section.id for section in sections},
            )
        except ValidationError:
            logger.warning("Epic/story validation failed, using fallback backlog")
            return self._fallback_backlog(extracted)

    async def generate_acceptance_criteria(
        self,
        epics: list[Epic],
        extracted: dict[str, Any],
        sections: list[Section],
    ) -> list[Epic]:
        prompt = (
            "You generate acceptance criteria for the provided backlog draft.\n"
            "Return strict JSON with exactly one top-level key: epics.\n"
            "Keep epic titles, summaries, story titles, story text, and story source_refs intact.\n"
            "For each story, populate acceptance_criteria as an array of objects with key: text.\n"
            "Each acceptance criterion must use Given/When/Then wording.\n"
            "Return exactly 2 concise acceptance criteria per story.\n"
            "Leave dependencies as an empty array.\n"
            "Do not include markdown or explanation.\n\n"
            f"Extracted data:\n{json.dumps(extracted, ensure_ascii=True)}\n\n"
            f"Available sections:\n{json.dumps([section.model_dump() for section in sections], ensure_ascii=True)}\n\n"
            f"Current backlog:\n{json.dumps([epic.model_dump() for epic in epics], ensure_ascii=True)}\n\n"
            f"JSON schema:\n{json.dumps(BacklogGeneration.model_json_schema(), ensure_ascii=True)}"
        )
        result = await self._generate_json(
            prompt,
            format_schema=BacklogGeneration.model_json_schema(),
        )
        try:
            backlog = BacklogGeneration.model_validate(result)
            return self._clean_epics(
                backlog.epics,
                extracted,
                valid_section_ids={section.id for section in sections},
            )
        except ValidationError:
            logger.warning("Acceptance criteria validation failed, filling criteria heuristically")
            return self._fill_missing_acceptance_criteria(epics)

    def derive_dependencies(
        self,
        epics: list[Epic],
        extracted: dict[str, Any],
    ) -> list[Epic]:
        """Quick heuristic dependency pass to avoid another slow LLM call."""
        return self._fill_missing_dependencies(epics, extracted)

    def derive_open_questions(
        self,
        extracted: dict[str, Any],
        epics: list[Epic],
        ambiguity_flags: list[str] | None = None,
        completeness_score: float = 1.0,
    ) -> dict[str, list[str]]:
        """Quick heuristic open-question pass to avoid another slow LLM call."""
        result = self._fallback_open_questions(
            extracted,
            ambiguity_flags=ambiguity_flags or [],
            completeness_score=completeness_score,
        )
        if epics and not result["open_questions"]:
            result["open_questions"].append(
                "Which stories should be prioritized for the first implementation slice?"
            )
        return {
            "open_questions": self._clean_text_items(result["open_questions"]),
            "assumptions": self._clean_text_items(result["assumptions"]),
        }

    def assess_requirement_quality(
        self,
        normalized_text: str,
        extracted: dict[str, Any],
    ) -> dict[str, object]:
        """Heuristically score requirement completeness and identify ambiguity."""
        flags: list[str] = []
        lowered = normalized_text.lower()

        if not extracted.get("actors"):
            flags.append("missing_business_actor")

        vague_terms = {
            "fast",
            "user friendly",
            "easy to use",
            "scalable",
            "secure",
            "reliable",
            "efficient",
        }
        measurable_terms = {
            "ms",
            "second",
            "minute",
            "%",
            "sla",
            "uptime",
            "latency",
            "throughput",
        }
        if any(term in lowered for term in vague_terms) and not any(
            term in lowered for term in measurable_terms
        ):
            flags.append("vague_non_functionals")

        integration_terms = {
            "integrat",
            "api",
            "sync",
            "import",
            "export",
            "webhook",
            "crm",
            "erp",
            "record system",
            "patient record",
        }
        if not any(term in lowered for term in integration_terms):
            flags.append("missing_integrations")

        ownership_terms = {
            "owner",
            "ownership",
            "admin",
            "manager",
            "operations",
            "ops",
            "team",
            "support",
            "reception",
        }
        if not any(term in lowered for term in ownership_terms):
            flags.append("unclear_ownership")

        score = max(0.0, 1.0 - (0.2 * len(flags)))
        if extracted.get("goals"):
            score += 0.1
        if extracted.get("features"):
            score += 0.1

        return {
            "completeness_score": round(min(score, 1.0), 2),
            "ambiguity_flags": self._clean_text_items(flags),
        }

    def build_summary(
        self,
        extracted: dict[str, Any],
        epics: list[Epic],
    ) -> str:
        actors = ", ".join(extracted.get("actors", [])[:2]) or "users"
        feature_count = len(extracted.get("features", []))
        story_count = sum(len(epic.stories) for epic in epics)
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
            source_refs_by_category=extracted.get("source_refs_by_category", {}),
        )

    def _clean_epics(
        self,
        epics: list[Epic],
        extracted: dict[str, Any],
        valid_section_ids: set[str] | None = None,
    ) -> list[Epic]:
        cleaned_epics: list[Epic] = []
        seen_epics: set[str] = set()
        valid_ids = valid_section_ids or self._collect_valid_source_refs(extracted)

        for epic in epics:
            epic_title = self._clean_text(epic.title)
            epic_summary = self._clean_text(epic.summary)
            if not epic_title or not epic_summary:
                continue

            epic_key = epic_title.lower()
            if epic_key in seen_epics:
                continue
            seen_epics.add(epic_key)

            cleaned_stories: list[Story] = []
            seen_stories: set[str] = set()
            for story in epic.stories:
                normalized_story = self._normalize_story_text(story.story, extracted)
                story_title = self._clean_text(story.title) or self._derive_story_title(
                    normalized_story
                )
                if not normalized_story or self._looks_like_garbage(normalized_story):
                    continue

                story_key = normalized_story.lower()
                if story_key in seen_stories:
                    continue
                seen_stories.add(story_key)

                source_refs = self._clean_source_refs(story.source_refs, valid_ids)
                criteria = self._clean_acceptance_criteria(
                    story.acceptance_criteria,
                    normalized_story,
                )
                dependencies = self._clean_dependencies(
                    story.dependencies,
                    valid_ids,
                    fallback_source_refs=source_refs,
                )
                cleaned_stories.append(
                    Story(
                        title=story_title,
                        story=normalized_story,
                        source_refs=source_refs,
                        acceptance_criteria=criteria,
                        dependencies=dependencies,
                    )
                )

            if cleaned_stories:
                cleaned_epics.append(
                    Epic(title=epic_title, summary=epic_summary, stories=cleaned_stories)
                )

        return cleaned_epics or self._fallback_backlog(extracted)

    def _clean_acceptance_criteria(
        self,
        criteria: list[AcceptanceCriterion],
        story: str,
    ) -> list[AcceptanceCriterion]:
        cleaned: list[AcceptanceCriterion] = []
        seen: set[str] = set()
        for criterion in criteria:
            text = self._normalize_criterion_text(criterion.text)
            key = text.lower()
            if not text or key in seen or self._looks_like_garbage(text):
                continue
            seen.add(key)
            cleaned.append(AcceptanceCriterion(text=text))

        if cleaned:
            return cleaned
        return self._fallback_criteria(story)

    def _clean_dependencies(
        self,
        dependencies: list[Dependency],
        valid_section_ids: set[str],
        fallback_source_refs: list[str] | None = None,
    ) -> list[Dependency]:
        cleaned: list[Dependency] = []
        seen: set[tuple[str, str]] = set()
        for dependency in dependencies:
            name = self._clean_text(dependency.name)
            dep_type = self._clean_text(dependency.dependency_type).lower() or "relates_to"
            key = (name.lower(), dep_type)
            if not name or key in seen or self._looks_like_garbage(name):
                continue
            seen.add(key)
            source_refs = self._clean_source_refs(
                dependency.source_refs,
                valid_section_ids,
            ) or list(fallback_source_refs or [])
            cleaned.append(
                Dependency(
                    name=name,
                    dependency_type=dep_type,
                    source_refs=source_refs,
                )
            )
        return cleaned

    def _fallback_backlog(self, extracted: dict[str, Any]) -> list[Epic]:
        actors = extracted.get("actors", []) or ["user"]
        goals = extracted.get("goals", []) or ["achieve the core business outcome"]
        features = extracted.get("features", []) or ["support the primary workflow"]
        constraints = extracted.get("constraints", [])
        feature_refs = extracted.get("source_refs_by_category", {}).get("features", [])

        stories: list[Story] = []
        for index, feature in enumerate(features[:3]):
            actor = actors[min(index, len(actors) - 1)]
            goal = goals[min(index, len(goals) - 1)] if goals else feature
            story_text = self._normalize_story_text(feature, {"actors": [actor], "goals": [goal]})
            stories.append(
                Story(
                    title=self._derive_story_title(story_text),
                    story=story_text,
                    source_refs=list(feature_refs),
                    acceptance_criteria=self._fallback_criteria(story_text),
                    dependencies=self._fallback_dependencies(constraints, feature_refs),
                )
            )

        return [
            Epic(
                title="Core Product Workflow",
                summary="Initial backlog draft generated from extracted requirements.",
                stories=stories,
            )
        ]

    def _fill_missing_acceptance_criteria(self, epics: list[Epic]) -> list[Epic]:
        updated: list[Epic] = []
        for epic in epics:
            updated_stories: list[Story] = []
            for story in epic.stories:
                criteria = (
                    story.acceptance_criteria
                    if story.acceptance_criteria
                    else self._fallback_criteria(story.story)
                )
                updated_stories.append(
                    Story(
                        title=story.title,
                        story=story.story,
                        acceptance_criteria=criteria,
                        dependencies=story.dependencies,
                    )
                )
            updated.append(
                Epic(title=epic.title, summary=epic.summary, stories=updated_stories)
            )
        return updated

    def _fill_missing_dependencies(
        self,
        epics: list[Epic],
        extracted: dict[str, Any],
    ) -> list[Epic]:
        fallback_dependencies = self._fallback_dependencies(
            extracted.get("constraints", []),
            extracted.get("source_refs_by_category", {}).get("constraints", []),
        )
        updated: list[Epic] = []
        for epic in epics:
            updated_stories: list[Story] = []
            for story in epic.stories:
                dependencies = story.dependencies or fallback_dependencies
                updated_stories.append(
                    Story(
                        title=story.title,
                        story=story.story,
                        source_refs=story.source_refs,
                        acceptance_criteria=story.acceptance_criteria,
                        dependencies=dependencies,
                    )
                )
            updated.append(
                Epic(title=epic.title, summary=epic.summary, stories=updated_stories)
            )
        return updated

    def _fallback_criteria(self, story: str) -> list[AcceptanceCriterion]:
        goal = self._extract_goal_fragment(story)
        return [
            AcceptanceCriterion(
                text=(
                    "Given valid requirement text is submitted, when the service "
                    f"processes the request, then the story '{story}' is returned."
                )
            ),
            AcceptanceCriterion(
                text=(
                    f"Given the story '{story}', when backlog details are generated, "
                    "then the acceptance criteria are testable and use Given/When/Then wording."
                )
            ),
            AcceptanceCriterion(
                text=(
                    f"Given the goal '{goal}', when the response is produced, then the story "
                    "aligns with the extracted actors, goals, features, and constraints."
                )
            ),
        ]

    def _fallback_dependencies(
        self,
        constraints: list[str],
        source_refs: list[str] | None = None,
    ) -> list[Dependency]:
        return [
            Dependency(
                name=constraint,
                dependency_type="depends_on",
                source_refs=list(source_refs or []),
            )
            for constraint in constraints[:2]
            if constraint
        ]

    def _fallback_open_questions(
        self,
        extracted: dict[str, Any],
        ambiguity_flags: list[str] | None = None,
        completeness_score: float = 1.0,
    ) -> dict[str, list[str]]:
        questions: list[str] = []
        assumptions: list[str] = []
        active_flags = set(ambiguity_flags or [])
        if not extracted.get("actors"):
            questions.append("Who is the primary user or actor for the first release?")
        if not extracted.get("constraints"):
            questions.append("Are there platform, compliance, or integration constraints?")
        if "missing_business_actor" in active_flags:
            questions.append("Which business actor owns the workflow and receives the primary value from this capability?")
        if "vague_non_functionals" in active_flags:
            questions.append("Which non-functional requirements need measurable targets such as latency, availability, or security controls?")
        if "missing_integrations" in active_flags:
            questions.append("Which external systems, APIs, or internal platforms must this solution integrate with?")
        if "unclear_ownership" in active_flags:
            questions.append("Which team or operational owner is responsible for setup, support, and ongoing maintenance?")
        if completeness_score < 0.75:
            questions.append("What scope should be deferred if the current requirements are too incomplete for the first release?")
        if extracted.get("features"):
            assumptions.append("The listed features are all in scope for the initial backlog draft.")
        if extracted.get("goals"):
            assumptions.append("The extracted goals accurately represent the business outcome.")
        return {
            "open_questions": self._clean_text_items(questions),
            "assumptions": self._clean_text_items(assumptions),
        }

    def _normalize_story_text(
        self,
        story: str,
        extracted: dict[str, Any],
    ) -> str:
        cleaned = self._clean_text(story)
        if not cleaned:
            return ""
        if cleaned.lower().startswith("as a ") or cleaned.lower().startswith("as an "):
            return cleaned

        actors = extracted.get("actors", [])
        goals = extracted.get("goals", [])
        actor = actors[0] if actors else "user"
        benefit = goals[0].rstrip(".") if goals else "the team can act on the requirement"
        article = "an" if actor[:1].lower() in {"a", "e", "i", "o", "u"} else "a"
        return f"As {article} {actor}, I want {cleaned.rstrip('.')}, so that {benefit}."

    def _normalize_criterion_text(self, text: str) -> str:
        cleaned = self._clean_text(text)
        if not cleaned:
            return ""
        if cleaned.lower().startswith("given "):
            return cleaned
        return f"Given a valid request, when processing runs, then {cleaned.rstrip('.')}."

    def _derive_story_title(self, story: str) -> str:
        match = re.search(r"I want (.*?), so that", story)
        if match:
            return self._clean_text(match.group(1)).rstrip(".").title()[:120]
        return self._clean_text(story)[:120]

    def _extract_goal_fragment(self, story: str) -> str:
        match = re.search(r"I want (.*?), so that", story)
        if match:
            return self._clean_text(match.group(1))
        return self._clean_text(story)

    def _clean_text_items(self, items: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            value = self._clean_text(item)
            key = value.lower()
            if not value or key in seen or self._looks_like_garbage(value):
                continue
            seen.add(key)
            cleaned.append(value)
        return cleaned

    def _clean_text(self, text: str) -> str:
        cleaned = " ".join(str(text).split()).strip()
        cleaned = re.sub(r"^[\-\*\d\.\)\(]+", "", cleaned).strip()
        return cleaned

    def _looks_like_garbage(self, text: str) -> bool:
        lowered = text.lower()
        if lowered in {"n/a", "na", "none", "null", "tbd", "todo", "placeholder"}:
            return True
        if len(lowered) < 3:
            return True
        if re.fullmatch(r"[\W_]+", lowered):
            return True
        return False

    async def _generate_json(
        self,
        prompt: str,
        format_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "format": format_schema or "json",
            "options": {
                "temperature": self.settings.ollama_temperature,
            },
        }
        if self.settings.ollama_num_predict is not None:
            payload["options"]["num_predict"] = self.settings.ollama_num_predict
        headers = {}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        timeout = httpx.Timeout(
            connect=10.0,
            read=self.settings.ollama_timeout_seconds,
            write=30.0,
            pool=30.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.settings.ollama_base_url}/api/generate",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()

        raw_response = body.get("response", "{}")
        logger.info("Received Ollama response model=%s", self.settings.llm_model)
        parsed = self._parse_json_response(raw_response)
        return parsed if isinstance(parsed, dict) else {}

    def _parse_json_response(self, raw_response: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_response)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            logger.warning(
                "Model returned malformed JSON; attempting salvage snippet=%s",
                raw_response[:500].replace("\n", "\\n"),
            )
            match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if not match:
                return {}
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}

    def _ensure_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _extract_grounded_texts(
        self,
        items: Any,
        valid_section_ids: set[str],
    ) -> list[str]:
        if not isinstance(items, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            text = self._clean_text(item.get("text", ""))
            refs = self._clean_source_refs(item.get("source_refs", []), valid_section_ids)
            key = text.lower()
            if not text or not refs or key in seen or self._looks_like_garbage(text):
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned

    def _extract_grounded_refs(
        self,
        items: Any,
        valid_section_ids: set[str],
    ) -> list[str]:
        if not isinstance(items, list):
            return []
        refs: list[str] = []
        for item in items:
            if isinstance(item, dict):
                refs.extend(self._clean_source_refs(item.get("source_refs", []), valid_section_ids))
        return list(dict.fromkeys(refs))

    def _clean_source_refs(
        self,
        refs: Any,
        valid_section_ids: set[str],
    ) -> list[str]:
        if not isinstance(refs, list):
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            value = str(ref).strip()
            if value in valid_section_ids and value not in seen:
                seen.add(value)
                cleaned.append(value)
        return cleaned

    def _collect_valid_source_refs(self, extracted: dict[str, Any]) -> set[str]:
        refs = extracted.get("source_refs_by_category", {})
        valid: set[str] = set()
        if isinstance(refs, dict):
            for value in refs.values():
                if isinstance(value, list):
                    valid.update(str(item).strip() for item in value if str(item).strip())
        return valid
    
