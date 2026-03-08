from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from storycraftr.agent.memory_manager import NarrativeMemoryManager
from storycraftr.utils.core import load_book_config

console = Console()


def _resolve_book_path(book_path: str | None) -> str:
    return str((Path(book_path) if book_path else Path.cwd()).resolve())


def _build_manager(book_path: str | None) -> NarrativeMemoryManager:
    resolved = _resolve_book_path(book_path)
    config = load_book_config(resolved)
    return NarrativeMemoryManager(book_path=resolved, config=config)


@click.group(name="memory")
def memory() -> None:
    """Long-term memory diagnostics and search commands."""


@memory.command(name="status")
@click.option("--book-path", type=click.Path(), required=False)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
)
def memory_status(book_path: str | None, output_format: str) -> None:
    """Show memory runtime status and provider mode."""

    manager = _build_manager(book_path)
    info = manager.get_runtime_diagnostics()

    if output_format == "json":
        click.echo(json.dumps(info, indent=2))
        return

    lines = [
        "Memory Status",
        f"- Enabled: {'yes' if info.get('enabled') else 'no'}",
        f"- Provider Mode: {info.get('provider', 'unknown')}",
        f"- Story ID: {info.get('story_id', 'unknown')}",
        f"- Storage Path: {info.get('storage_path', 'unknown')}",
    ]
    retrieval = info.get("last_retrieval")
    if isinstance(retrieval, dict):
        lines.append(
            "- Last Recall Hits: "
            f"{retrieval.get('hits_returned', 0)} "
            f"(queries run: {retrieval.get('queries_run', 0)}/"
            f"{retrieval.get('queries_attempted', 0)})"
        )
        hits_by_source = retrieval.get("hits_by_source") or {}
        if isinstance(hits_by_source, dict) and hits_by_source:
            source_summary = ", ".join(
                f"{name}={count}" for name, count in hits_by_source.items()
            )
            lines.append(f"- Last Recall Sources: {source_summary}")
    if not info.get("enabled") and info.get("reason"):
        lines.append(f"- Reason: {info['reason']}")
    click.echo("\n".join(lines))


@memory.command(name="search")
@click.option("--book-path", type=click.Path(), required=False)
@click.option("--query", type=str, required=True, help="Memory search query.")
@click.option("--chapter", type=int, required=False)
@click.option("--limit", type=int, default=10, show_default=True)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json", "ndjson"]),
    default="table",
    show_default=True,
)
def memory_search(
    book_path: str | None,
    query: str,
    chapter: int | None,
    limit: int,
    output_format: str,
) -> None:
    """Search long-term memories for narrative context debugging."""

    manager = _build_manager(book_path)
    rows = manager.search_memories(
        query=query,
        chapter=chapter,
        limit=max(1, limit),
    )

    if output_format == "json":
        click.echo(json.dumps(rows, indent=2))
        return
    if output_format == "ndjson":
        for row in rows:
            click.echo(json.dumps(row, separators=(",", ":")))
        return

    if not rows:
        console.print("[dim]No memory hits.[/dim]")
        return

    table = Table(title=f"Memory Search ({len(rows)} hit(s))")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Memory", style="white")
    for idx, row in enumerate(rows, start=1):
        table.add_row(str(idx), row.get("memory", ""))
    console.print(table)


@memory.command(name="remember")
@click.option("--book-path", type=click.Path(), required=False)
@click.option("--user", "user_prompt", type=str, required=True)
@click.option("--assistant", "assistant_response", type=str, required=True)
@click.option("--chapter", type=int, required=False)
@click.option("--scene", type=str, default="Unknown", show_default=True)
def memory_remember(
    book_path: str | None,
    user_prompt: str,
    assistant_response: str,
    chapter: int | None,
    scene: str,
) -> None:
    """Persist one explicit turn into long-term memory."""

    manager = _build_manager(book_path)
    ok = manager.remember_turn(
        user_prompt=user_prompt,
        assistant_response=assistant_response,
        chapter=chapter,
        scene=scene,
    )
    if ok:
        console.print("[green]Memory turn stored.[/green]")
        return

    reason = manager.disabled_reason or "memory backend unavailable"
    raise click.ClickException(f"Unable to store memory turn: {reason}")
