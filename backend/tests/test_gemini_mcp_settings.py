"""Static security contract for Gemini's project-scoped browser MCP server."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _settings() -> dict:
    path = PROJECT_ROOT / ".gemini" / "settings.json"
    assert path.is_file()
    return json.loads(path.read_text(encoding="utf-8"))


def test_only_learning_browser_mcp_server_is_allowed_and_registered():
    settings = _settings()

    assert settings["general"]["plan"]["modelRouting"] is False
    assert settings["mcp"] == {
        "allowed": ["learning-browser"],
        "autoAllowInHeadless": True,
    }
    assert set(settings["mcpServers"]) == {"learning-browser"}


def test_learning_browser_uses_the_python_stdio_gateway_and_safe_tool_allowlist():
    server = _settings()["mcpServers"]["learning-browser"]

    assert server["command"] == "python"
    assert server["args"] == ["-m", "app.browser.server"]
    assert server["includeTools"] == ["browser_search", "browser_read"]
    assert server["trust"] is True
    assert 180_000 <= server["timeout"] <= 600_000
    assert "excludeTools" not in server


def test_mcp_module_is_discoverable_from_root_backend_and_docker_layouts():
    server = _settings()["mcpServers"]["learning-browser"]

    # Gemini inherits its own cwd for stdio when `cwd` is omitted. PYTHONPATH
    # covers root launches; backend/ and Docker /app launches find `app`
    # directly from their current directory.
    assert "cwd" not in server
    assert server["env"] == {"PYTHONPATH": "backend"}
    assert (PROJECT_ROOT / "backend" / "app" / "browser" / "server.py").is_file()

    dockerfile = (PROJECT_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "WORKDIR /app" in dockerfile
    assert "COPY .gemini ./.gemini" in dockerfile
    assert "COPY backend/app ./app" in dockerfile
