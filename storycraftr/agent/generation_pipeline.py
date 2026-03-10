from __future__ import annotations

import json
import re
from dataclasses import dataclass

from storycraftr.agent.narrative_state import SceneDirective

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass(frozen=True)
class PipelineStepArtifacts:
    """Captured Plan->Draft->Edit artifacts for diagnostics."""

    directive: SceneDirective
    planner_response: str
    draft_response: str
    final_response: str


@dataclass(frozen=True)
class SceneGenerationPipeline:
    """Build role-scoped prompts and parse planner JSON responses."""

    planner_rules: str
    drafter_rules: str
    editor_rules: str

    def build_planner_user_prompt(self, user_input: str) -> str:
        """Build planner-stage instruction that returns SceneDirective JSON only."""

        cleaned = user_input.strip()
        return "\n".join(
            [
                "Planner stage: produce the next scene directive.",
                "Return ONLY valid JSON with keys: goal, conflict, stakes, outcome.",
                "Do not include markdown fences or explanatory text.",
                f"User request: {cleaned}",
            ]
        )

    def build_drafter_user_prompt(
        self,
        *,
        user_input: str,
        directive: SceneDirective,
    ) -> str:
        """Build drafter-stage instruction anchored to SceneDirective."""

        return "\n".join(
            [
                "Drafter stage: write scene prose only.",
                "Follow this directive exactly:",
                f"- Goal: {directive.goal}",
                f"- Conflict: {directive.conflict}",
                f"- Stakes: {directive.stakes}",
                f"- Outcome: {directive.outcome}",
                f"User request: {user_input.strip()}",
                "Return only scene prose, with no headings or commentary.",
            ]
        )

    def build_editor_user_prompt(
        self,
        *,
        user_input: str,
        directive: SceneDirective,
        draft: str,
    ) -> str:
        """Build editor-stage instruction to revise draft against directive."""

        return "\n".join(
            [
                "Editor stage: revise draft prose against directive and craft rules.",
                "Preserve intent, pacing, and scene trajectory.",
                "Directive:",
                f"- Goal: {directive.goal}",
                f"- Conflict: {directive.conflict}",
                f"- Stakes: {directive.stakes}",
                f"- Outcome: {directive.outcome}",
                f"User request: {user_input.strip()}",
                "Draft:",
                draft.strip(),
                "Return ONLY the revised prose.",
            ]
        )

    def parse_scene_directive(self, raw_response: str) -> SceneDirective:
        """Parse planner response into validated SceneDirective."""

        payload = self._extract_json_object(raw_response)
        data = json.loads(payload)
        return SceneDirective(**data)

    def _extract_json_object(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped

        block_match = _JSON_BLOCK_RE.search(stripped)
        if block_match is not None:
            return block_match.group(1).strip()

        first = stripped.find("{")
        last = stripped.rfind("}")
        if first != -1 and last != -1 and first < last:
            return stripped[first : last + 1].strip()

        raise ValueError("Planner response did not include a JSON object.")
