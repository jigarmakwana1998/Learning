"""Executable-resolution contracts for the project-local browser toolchain."""

from pathlib import Path

from app.browser import client


def test_browser_command_override_is_parsed_without_a_shell(monkeypatch):
    monkeypatch.setenv("AGENT_BROWSER_COMMAND", "custom-browser --channel stable")
    monkeypatch.setattr(client.shutil, "which", lambda _name: None)

    assert client.resolve_agent_browser_command() == ["custom-browser", "--channel", "stable"]


def test_project_local_native_browser_binary_is_preferred_to_path(monkeypatch):
    monkeypatch.delenv("AGENT_BROWSER_COMMAND", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda path: "node_modules" in path.parts)

    def unexpected_path_lookup(_name):
        raise AssertionError("PATH must not be consulted when the pinned local binary exists")

    monkeypatch.setattr(client.shutil, "which", unexpected_path_lookup)
    command = client.resolve_agent_browser_command()

    assert len(command) == 1
    assert Path(command[0]).parent.name == "bin"
    assert Path(command[0]).name.startswith("agent-browser-")


def test_browser_binary_falls_back_to_resolved_path(monkeypatch):
    monkeypatch.delenv("AGENT_BROWSER_COMMAND", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda _path: False)
    monkeypatch.setattr(client.shutil, "which", lambda name: f"/runtime/bin/{name}")

    assert client.resolve_agent_browser_command() == ["/runtime/bin/agent-browser"]
