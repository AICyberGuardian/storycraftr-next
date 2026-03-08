from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from storycraftr.agent.execution_mode import parse_execution_mode
from storycraftr.agent.narrative_state import NarrativeStateStore
from storycraftr.llm.openrouter_discovery import get_free_models, refresh_free_models
from storycraftr.services.control_plane import (
    canon_check_impl,
    mode_set_impl,
    mode_show_impl,
    state_audit_impl,
    state_extract_impl,
)

console = Console()


def _resolve_book_path(book_path: str | None) -> str:
    return str(Path(book_path or os.getcwd()).resolve())


@click.command(name="tui")
@click.option(
    "--book-path",
    type=click.Path(file_okay=False, path_type=Path),
    required=False,
    help="Path to the project directory.",
)
def tui(book_path: Path | None) -> None:
    """Launch the interactive Textual TUI."""

    resolved_path = str((book_path or Path.cwd()).resolve())
    try:
        from storycraftr.tui.app import TuiApp
    except ImportError as exc:  # pragma: no cover - depends on optional runtime env
        raise click.ClickException(f"TUI dependencies are unavailable: {exc}") from exc

    TuiApp(book_path=resolved_path).run()


@click.group(name="state")
def state() -> None:
    """Narrative state management commands."""


@state.command(name="audit")
@click.option("--book-path", type=click.Path(), required=False)
@click.option(
    "--entity-type",
    type=click.Choice(["character", "location", "plot_thread"]),
    required=False,
)
@click.option("--entity-id", type=str, required=False)
@click.option("--limit", type=int, default=20, show_default=True)
@click.option(
    "--format", "output_format", type=click.Choice(["table", "json"]), default="table"
)
def state_audit(
    book_path: str | None,
    entity_type: str | None,
    entity_id: str | None,
    limit: int,
    output_format: str,
) -> None:
    """Display narrative state audit entries."""

    result = state_audit_impl(
        _resolve_book_path(book_path),
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
    if not result.enabled:
        raise click.ClickException("State audit logging is disabled.")
    entries = result.entries

    if output_format == "json":
        click.echo(json.dumps([entry.to_dict() for entry in entries], indent=2))
        return

    if not entries:
        console.print("[dim]No audit entries found.[/dim]")
        return

    table = Table(title=f"Narrative State Audit ({len(entries)} entries)")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Actor", style="green")
    table.add_column("Operation", style="yellow")
    table.add_column("Changes", style="white")

    for entry in entries:
        changes = entry.changeset.count_changes() if entry.changeset else 0
        table.add_row(
            entry.timestamp,
            entry.actor,
            entry.operation_type,
            str(changes),
        )

    console.print(table)


@state.command(name="validate")
@click.option("--book-path", type=click.Path(), required=False)
def state_validate(book_path: str | None) -> None:
    """Validate narrative state consistency checks."""

    store = NarrativeStateStore(_resolve_book_path(book_path))
    snapshot = store.load()

    issues: list[str] = []
    valid_locations = set(snapshot.locations.keys())
    for character in snapshot.characters.values():
        if character.location and character.location not in valid_locations:
            issues.append(
                f"Character '{character.name}' references unknown location '{character.location}'."
            )

    for thread in snapshot.plot_threads.values():
        if thread.status == "resolved" and thread.resolved_chapter is None:
            issues.append(
                f"Plot thread '{thread.id}' is resolved without resolved_chapter."
            )

    if issues:
        console.print("[yellow]State validation warnings:[/yellow]")
        for issue in issues:
            console.print(f"- {issue}")
        sys.exit(1)

    console.print("[green]State validation passed.[/green]")


@state.command(name="show")
@click.option("--book-path", type=click.Path(), required=False)
@click.option(
    "--format", "output_format", type=click.Choice(["text", "json"]), default="text"
)
def state_show(book_path: str | None, output_format: str) -> None:
    """Display the current narrative state snapshot."""

    store = NarrativeStateStore(_resolve_book_path(book_path))
    snapshot = store.load()

    if output_format == "json":
        click.echo(json.dumps(snapshot.model_dump(mode="json"), indent=2))
        return

    click.echo(store.render_prompt_block())


@state.command(name="extract")
@click.option("--book-path", type=click.Path(), required=False)
@click.option("--text", type=str, required=False, help="Text to extract state from.")
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
)
@click.option("--apply", "apply_patch", is_flag=True, default=False)
@click.option(
    "--format", "output_format", type=click.Choice(["text", "json"]), default="text"
)
def state_extract(
    book_path: str | None,
    text: str | None,
    file_path: Path | None,
    apply_patch: bool,
    output_format: str,
) -> None:
    """Extract deterministic state patch proposal from prose and optionally apply it."""

    payload = text
    if file_path is not None:
        payload = file_path.read_text(encoding="utf-8")
    elif payload is None and not sys.stdin.isatty():
        payload = sys.stdin.read().strip()

    if not payload:
        raise click.ClickException("Provide --text, --file, or piped input.")

    try:
        result = state_extract_impl(
            _resolve_book_path(book_path),
            text=payload,
            apply_patch=apply_patch,
            actor="cli-state-extractor",
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if output_format == "json":
        click.echo(
            json.dumps(
                {
                    "operation_count": len(result.extracted.patch.operations),
                    "events": [event.__dict__ for event in result.extracted.events],
                    "patch": result.extracted.patch.model_dump(),
                    "applied": result.applied,
                    "applied_version": result.applied_version,
                },
                indent=2,
            )
        )
        return

    lines = [
        "State Extraction",
        f"- Operations: {len(result.extracted.patch.operations)}",
        f"- Events: {len(result.extracted.events)}",
    ]
    if result.extracted.patch.operations:
        lines.append("- Patch operations:")
        for operation in result.extracted.patch.operations:
            lines.append(
                "  "
                f"* {operation.operation} {operation.entity_type}:{operation.entity_id}"
            )
    else:
        lines.append("- Patch operations: <none>")

    if apply_patch:
        if result.applied:
            lines.append(f"- Applied: yes (version {result.applied_version})")
        else:
            lines.append("- Applied: no (no operations extracted)")

    click.echo("\n".join(lines))


@click.group(name="canon")
def canon() -> None:
    """Canon verification commands."""


@canon.command(name="check")
@click.option("--book-path", type=click.Path(), required=False)
@click.option("--chapter", type=int, default=1, show_default=True)
@click.option("--text", type=str, required=False, help="Text to verify against canon.")
@click.option(
    "--file",
    "file_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
)
def canon_check(
    book_path: str | None,
    chapter: int,
    text: str | None,
    file_path: Path | None,
) -> None:
    """Check candidate canon statements for duplicates or direct conflicts."""

    payload = text
    if file_path is not None:
        payload = file_path.read_text(encoding="utf-8")
    elif payload is None and not sys.stdin.isatty():
        payload = sys.stdin.read().strip()

    if not payload:
        raise click.ClickException("Provide --text, --file, or piped input.")

    result = canon_check_impl(
        _resolve_book_path(book_path),
        chapter=max(1, chapter),
        text=payload,
    )

    table = Table(title=f"Canon Verification (chapter {result.chapter})")
    table.add_column("Candidate", style="white")
    table.add_column("Allowed", style="green")
    table.add_column("Reason", style="yellow")
    table.add_column("Conflict", style="red")
    for row in result.rows:
        table.add_row(
            row.candidate,
            "yes" if row.allowed else "no",
            row.reason,
            row.conflicting_fact or "-",
        )
    console.print(table)

    if result.failures:
        sys.exit(1)


@click.group(name="mode")
def mode() -> None:
    """Execution mode controls for runtime metadata."""


@mode.command(name="show")
@click.option("--book-path", type=click.Path(), required=False)
def mode_show(book_path: str | None) -> None:
    """Display persisted execution mode state."""

    state = mode_show_impl(_resolve_book_path(book_path))
    lines = [
        f"mode: {state.mode_config.mode.value}",
        f"max_autopilot_turns: {state.mode_config.max_autopilot_turns}",
        f"autopilot_turns_remaining: {state.autopilot_turns_remaining}",
        (
            "auto_regenerate_on_conflict: "
            f"{str(state.mode_config.auto_regenerate_on_conflict).lower()}"
        ),
    ]
    click.echo("\n".join(lines))


@mode.command(name="set")
@click.argument("mode_name", type=click.Choice(["manual", "hybrid", "autopilot"]))
@click.option("--book-path", type=click.Path(), required=False)
@click.option("--turns", type=int, required=False)
def mode_set(mode_name: str, book_path: str | None, turns: int | None) -> None:
    """Set execution mode and optionally adjust autopilot turn limit."""

    requested = parse_execution_mode(mode_name)
    if requested is None:
        raise click.ClickException("Unsupported execution mode.")

    try:
        updated = mode_set_impl(
            _resolve_book_path(book_path),
            mode_name,
            turns=turns,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"Execution mode set to {updated.mode_config.mode.value} "
        f"(remaining turns: {updated.autopilot_turns_remaining})."
    )


@mode.command(name="stop")
@click.option("--book-path", type=click.Path(), required=False)
def mode_stop(book_path: str | None) -> None:
    """Stop autonomous execution and force manual mode."""

    try:
        mode_set_impl(
            _resolve_book_path(book_path),
            "manual",
            turns=0,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo("Execution stopped. Mode set to manual.")


@click.group(name="models")
def models() -> None:
    """OpenRouter model catalog commands."""


@models.command(name="list")
@click.option("--refresh", is_flag=True, default=False, help="Refresh before listing.")
@click.option(
    "--format", "output_format", type=click.Choice(["table", "json"]), default="table"
)
def models_list(refresh: bool, output_format: str) -> None:
    """List free OpenRouter models with discovered limits."""

    records = get_free_models(force_refresh=refresh)
    if output_format == "json":
        click.echo(
            json.dumps(
                [
                    {
                        "id": record.model_id,
                        "label": record.label,
                        "context_length": record.context_length,
                        "max_completion_tokens": record.max_completion_tokens,
                    }
                    for record in records
                ],
                indent=2,
            )
        )
        return

    if not records:
        console.print("[yellow]No free OpenRouter models were discovered.[/yellow]")
        return

    table = Table(title=f"OpenRouter Free Models ({len(records)})")
    table.add_column("ID", style="cyan")
    table.add_column("Context", style="yellow")
    table.add_column("Max Completion", style="green")
    for record in records:
        table.add_row(
            record.model_id,
            str(record.context_length),
            (
                str(record.max_completion_tokens)
                if record.max_completion_tokens is not None
                else "unknown"
            ),
        )
    console.print(table)


@models.command(name="refresh")
def models_refresh() -> None:
    """Force-refresh and print free OpenRouter model count."""

    refreshed = refresh_free_models()
    click.echo(f"Refreshed {len(refreshed)} free model(s).")
