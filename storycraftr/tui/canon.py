from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml import YAMLError


@dataclass(frozen=True)
class CanonFact:
    """One canon fact stored in the chapter-scoped canon ledger."""

    id: str
    text: str
    type: str
    source: str
    chapter: int


_ALLOWED_SOURCES = {"manual", "accepted"}
_DEFAULT_CANON: dict[str, Any] = {"version": 1, "chapters": {}}


def canon_file_path(book_path: str) -> Path:
    """Return the canonical ledger path under outline/."""

    return Path(book_path) / "outline" / "canon.yml"


def load_canon(book_path: str) -> dict[str, Any]:
    """Load canon YAML and normalize to the canonical schema."""

    path = canon_file_path(book_path)
    if not path.exists():
        return {"version": 1, "chapters": {}}

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not read canon file at {path}: {exc}") from exc

    if not raw.strip():
        return {"version": 1, "chapters": {}}

    try:
        parsed = yaml.safe_load(raw)
    except YAMLError as exc:
        raise RuntimeError(
            f"Malformed canon YAML at {path}. Fix outline/canon.yml or reset it."
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"Invalid canon format at {path}: root must be a mapping.")

    version = parsed.get("version", 1)
    chapters = parsed.get("chapters", {})
    if not isinstance(version, int):
        raise RuntimeError(f"Invalid canon format at {path}: 'version' must be int.")
    if not isinstance(chapters, dict):
        raise RuntimeError(
            f"Invalid canon format at {path}: 'chapters' must be a mapping."
        )

    normalized: dict[str, Any] = {"version": version, "chapters": {}}
    for chapter_key, chapter_payload in chapters.items():
        chapter_id = str(chapter_key)
        if not isinstance(chapter_payload, dict):
            raise RuntimeError(
                f"Invalid canon format at {path}: chapter '{chapter_id}' must be a mapping."
            )

        facts = chapter_payload.get("facts", [])
        if not isinstance(facts, list):
            raise RuntimeError(
                f"Invalid canon format at {path}: chapter '{chapter_id}' facts must be a list."
            )

        normalized_facts: list[dict[str, str]] = []
        for row in facts:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            normalized_facts.append(
                {
                    "id": str(row.get("id", "")).strip(),
                    "text": text,
                    "type": str(row.get("type", "constraint")).strip() or "constraint",
                    "source": _normalize_source(row.get("source")),
                }
            )

        normalized["chapters"][chapter_id] = {"facts": normalized_facts}

    return normalized


def save_canon(book_path: str, data: dict[str, Any]) -> None:
    """Persist canon YAML using the canonical schema keys."""

    path = canon_file_path(book_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": int(data.get("version", 1)),
        "chapters": data.get("chapters", {}),
    }

    try:
        rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
        path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not write canon file at {path}: {exc}") from exc


def list_facts(book_path: str, chapter: int | None = None) -> list[CanonFact]:
    """List canon facts, optionally restricted to a specific chapter."""

    data = load_canon(book_path)
    chapters = data.get("chapters", {})
    if not isinstance(chapters, dict):
        return []

    selected_keys: list[str]
    if chapter is None:
        selected_keys = sorted(chapters.keys(), key=_chapter_sort_key)
    else:
        selected_keys = [str(chapter)]

    facts: list[CanonFact] = []
    for chapter_key in selected_keys:
        chapter_payload = chapters.get(chapter_key, {})
        if not isinstance(chapter_payload, dict):
            continue
        rows = chapter_payload.get("facts", [])
        if not isinstance(rows, list):
            continue

        chapter_num = _safe_int(chapter_key)
        if chapter_num is None:
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            fact_id = str(row.get("id", "")).strip()
            if not fact_id:
                continue
            facts.append(
                CanonFact(
                    id=fact_id,
                    text=text,
                    type=str(row.get("type", "constraint")).strip() or "constraint",
                    source=_normalize_source(row.get("source")),
                    chapter=chapter_num,
                )
            )

    return facts


def add_fact(
    book_path: str,
    chapter: int,
    text: str,
    fact_type: str = "constraint",
    source: str = "manual",
) -> CanonFact:
    """Append one canon fact to a chapter and persist canon.yml."""

    chapter = max(1, int(chapter))
    text = text.strip()
    if not text:
        raise RuntimeError("Canon fact text cannot be empty.")

    data = load_canon(book_path)
    if not data:
        data = dict(_DEFAULT_CANON)

    chapters = data.setdefault("chapters", {})
    if not isinstance(chapters, dict):
        raise RuntimeError("Invalid canon data: 'chapters' must be a mapping.")

    chapter_key = str(chapter)
    chapter_entry = chapters.setdefault(chapter_key, {"facts": []})
    if not isinstance(chapter_entry, dict):
        chapter_entry = {"facts": []}
        chapters[chapter_key] = chapter_entry

    facts = chapter_entry.setdefault("facts", [])
    if not isinstance(facts, list):
        facts = []
        chapter_entry["facts"] = facts

    next_id = _next_fact_id(chapters)
    normalized_type = fact_type.strip() or "constraint"
    normalized_source = _normalize_source(source)
    row = {
        "id": next_id,
        "text": text,
        "type": normalized_type,
        "source": normalized_source,
    }
    facts.append(row)

    save_canon(book_path, data)
    return CanonFact(
        id=next_id,
        text=text,
        type=normalized_type,
        source=normalized_source,
        chapter=chapter,
    )


def clear_chapter_facts(book_path: str, chapter: int) -> int:
    """Clear facts for one chapter and return removed count."""

    chapter = max(1, int(chapter))
    data = load_canon(book_path)
    chapters = data.get("chapters", {})
    if not isinstance(chapters, dict):
        return 0

    chapter_key = str(chapter)
    chapter_entry = chapters.get(chapter_key)
    if not isinstance(chapter_entry, dict):
        return 0

    rows = chapter_entry.get("facts", [])
    removed = len(rows) if isinstance(rows, list) else 0

    chapters.pop(chapter_key, None)
    save_canon(book_path, data)
    return removed


def _normalize_source(value: Any) -> str:
    source = str(value or "manual").strip().lower()
    if source not in _ALLOWED_SOURCES:
        return "manual"
    return source


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _chapter_sort_key(value: str) -> tuple[int, str]:
    parsed = _safe_int(value)
    if parsed is None:
        return (10**9, value)
    return (parsed, value)


def _next_fact_id(chapters: dict[str, Any]) -> str:
    max_seen = 0
    for chapter_payload in chapters.values():
        if not isinstance(chapter_payload, dict):
            continue
        rows = chapter_payload.get("facts", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_id = str(row.get("id", "")).strip()
            if raw_id.startswith("fact-"):
                tail = raw_id[5:]
                if tail.isdigit():
                    max_seen = max(max_seen, int(tail))

    return f"fact-{max_seen + 1:03d}"
