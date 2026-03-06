from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import List


@dataclass
class SubAgentRole:
    slug: str
    name: str
    description: str
    command_whitelist: List[str]
    system_prompt: str
    language: str = "en"
    persona: str = ""
    temperature: float = 0.2

    @classmethod
    def from_dict(cls, slug: str, data: dict) -> "SubAgentRole":
        if not isinstance(data, dict):
            raise TypeError("Role payload must be a mapping.")

        resolved_slug = str(data.get("slug", slug)).strip().lower()
        if not resolved_slug:
            raise ValueError("Role slug cannot be empty.")

        whitelist_raw = data.get("command_whitelist", [])
        if not isinstance(whitelist_raw, list):
            raise ValueError("Role command_whitelist must be a list.")

        command_whitelist: List[str] = []
        for command in whitelist_raw:
            if not isinstance(command, str):
                raise ValueError("Role command_whitelist entries must be strings.")
            token = command.strip()
            if not token.startswith("!"):
                raise ValueError("Role command_whitelist entries must start with '!'.")
            command_whitelist.append(token)

        try:
            temperature = float(data.get("temperature", 0.2))
        except (TypeError, ValueError) as exc:
            raise ValueError("Role temperature must be a numeric value.") from exc

        if not isfinite(temperature) or temperature < 0.0 or temperature > 2.0:
            raise ValueError("Role temperature must be within the range [0.0, 2.0].")

        return cls(
            slug=resolved_slug,
            name=str(data.get("name", slug.title())).strip() or slug.title(),
            description=str(data.get("description", "")),
            command_whitelist=command_whitelist,
            system_prompt=str(data.get("system_prompt", "")),
            language=str(data.get("language", "en") or "en"),
            persona=str(data.get("persona", "")),
            temperature=temperature,
        )

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "command_whitelist": self.command_whitelist,
            "system_prompt": self.system_prompt,
            "language": self.language,
            "persona": self.persona,
            "temperature": self.temperature,
        }
