from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rich.console import Console

from storycraftr.chat.commands import CommandContext, handle_command
from storycraftr.subagents.models import SubAgentRole


class _Emitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


def _build_context(
    manager: mock.Mock, emitter: _Emitter, book_path: str
) -> CommandContext:
    return CommandContext(
        console=Console(file=StringIO(), force_terminal=False),
        session_manager=SimpleNamespace(),
        transcript=[],
        assistant=SimpleNamespace(last_documents=[]),
        book_path=book_path,
        job_manager=manager,
        event_emitter=emitter,
    )


def _role() -> SubAgentRole:
    return SubAgentRole(
        slug="editor",
        name="Editor",
        description="Polishes prose",
        command_whitelist=["!outline", "!chapters"],
        system_prompt="You are an editor.",
    )


def test_sub_agent_list_emits_roles_payload(tmp_path: Path) -> None:
    role = _role()
    manager = mock.Mock()
    manager.list_roles.return_value = [role]
    emitter = _Emitter()

    context = _build_context(manager, emitter, str(tmp_path / "book"))
    handle_command(":sub-agent !list", context)

    assert len(emitter.events) == 1
    event_name, payload = emitter.events[0]
    assert event_name == "sub_agent.roles"
    assert payload["roles"] == [role.to_dict()]


def test_sub_agent_status_emits_jobs_payload(tmp_path: Path) -> None:
    role = _role()
    manager = mock.Mock()
    manager.list_jobs.return_value = [
        SimpleNamespace(
            job_id="abc123",
            role=role,
            command_text="outline chapter-1",
            status="running",
            to_dict=lambda: {
                "job_id": "abc123",
                "status": "running",
                "role": "editor",
            },
        )
    ]
    emitter = _Emitter()

    context = _build_context(manager, emitter, str(tmp_path / "book"))
    handle_command(":sub-agent !status", context)

    assert len(emitter.events) == 1
    event_name, payload = emitter.events[0]
    assert event_name == "sub_agent.status"
    assert payload["jobs"] == [
        {
            "job_id": "abc123",
            "status": "running",
            "role": "editor",
        }
    ]


def test_sub_agent_command_emits_queued_payload(tmp_path: Path) -> None:
    job_payload = {
        "job_id": "xyz789",
        "status": "pending",
        "command_text": "outline chapter-1",
    }
    manager = mock.Mock()
    manager.get_role.return_value = None
    manager.submit.return_value = SimpleNamespace(to_dict=lambda: job_payload)
    emitter = _Emitter()

    context = _build_context(manager, emitter, str(tmp_path / "book"))
    handle_command(":sub-agent !outline chapter-1", context)

    assert len(emitter.events) == 1
    event_name, payload = emitter.events[0]
    assert event_name == "sub_agent.queued"
    assert payload == job_payload


def test_sub_agent_command_emit_error_payload_on_submit_failure(
    tmp_path: Path,
) -> None:
    manager = mock.Mock()
    manager.get_role.return_value = None
    manager.submit.side_effect = ValueError("bad command")
    emitter = _Emitter()

    context = _build_context(manager, emitter, str(tmp_path / "book"))
    handle_command(":sub-agent !bad", context)

    assert len(emitter.events) == 1
    event_name, payload = emitter.events[0]
    assert event_name == "sub_agent.error"
    assert payload["input"] == "!bad"
    assert payload["error"] == "bad command"
