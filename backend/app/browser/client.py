"""Argument-safe subprocess adapter for the agent-browser CLI."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shlex
import shutil
from pathlib import Path
from typing import Any


class AgentBrowserError(RuntimeError):
    """A sanitized agent-browser execution failure."""


def resolve_agent_browser_command() -> list[str]:
    """Resolve the pinned project binary before considering the user's PATH."""
    override = os.getenv("AGENT_BROWSER_COMMAND", "").strip()
    if override:
        command = shlex.split(override, posix=os.name != "nt")
        if command:
            return command

    repository_root = Path(__file__).resolve().parents[3]
    local_package = repository_root / "node_modules" / "agent-browser"
    local_binary = _native_package_binary(local_package)
    if local_binary is not None:
        return [str(local_binary)]

    binary_name = "agent-browser.cmd" if os.name == "nt" else "agent-browser"
    local_shim = repository_root / "node_modules" / ".bin" / binary_name
    if local_shim.is_file() and os.name != "nt":
        return [str(local_shim)]

    resolved = shutil.which("agent-browser")
    if resolved and os.name == "nt" and Path(resolved).suffix.casefold() in {".cmd", ".bat"}:
        # npm's Windows shim is a batch file. Resolve its downloaded native Rust
        # binary so untrusted URL arguments never cross cmd.exe parsing.
        global_binary = _native_package_binary(Path(resolved).parent / "node_modules" / "agent-browser")
        if global_binary is not None:
            return [str(global_binary)]
    return [resolved or "agent-browser"]


def _native_package_binary(package_directory: Path) -> Path | None:
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    machine = platform.machine().casefold()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"amd64", "x86_64"} else None
    if system is None or architecture is None:
        return None
    extension = ".exe" if system == "win32" else ""
    direct = package_directory / "bin" / f"agent-browser-{system}-{architecture}{extension}"
    if direct.is_file():
        return direct
    # Linux packages may contain the musl build instead of the glibc build.
    if system == "linux":
        musl = package_directory / "bin" / f"agent-browser-linux-musl-{architecture}"
        if musl.is_file():
            return musl
    return None


class AgentBrowserClient:
    """Use one ephemeral, domain-confined Chrome session per browser operation."""

    def __init__(self, *, command: list[str] | None = None, timeout_seconds: float = 30) -> None:
        self.command = list(command or resolve_agent_browser_command())
        self.timeout_seconds = timeout_seconds
        self.policy_path = Path(__file__).with_name("action-policy.json").resolve()

    async def run(self, session: str, host: str, *arguments: str) -> Any:
        allowed_domains = f"{host},*.{host}"
        command = [
            *self.command,
            "--session",
            session,
            "--json",
            "--content-boundaries",
            "--max-output",
            "6000",
            "--allowed-domains",
            allowed_domains,
            "--action-policy",
            str(self.policy_path),
            *arguments,
        ]
        environment = self._environment(allowed_domains)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
        except FileNotFoundError as error:
            raise AgentBrowserError("agent-browser executable was not found") from error
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise AgentBrowserError("agent-browser operation timed out") from error
        if process.returncode != 0:
            raise AgentBrowserError("agent-browser could not complete the read-only operation")
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AgentBrowserError("agent-browser returned invalid JSON") from error
        if isinstance(payload, dict) and payload.get("success") is False:
            raise AgentBrowserError("agent-browser reported an unsuccessful operation")
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    async def close(self, session: str, host: str) -> None:
        try:
            await self.run(session, host, "close")
        except AgentBrowserError:
            # Cleanup must not replace the useful navigation error.
            pass

    def _environment(self, allowed_domains: str) -> dict[str, str]:
        # The browser CLI does not need provider, database, or application
        # credentials. Give the third-party child only the OS/runtime values it
        # needs instead of inheriting the API process environment wholesale.
        allowed_environment = {
            "APPDATA",
            "COMSPEC",
            "HOME",
            "LANG",
            "LC_ALL",
            "LD_LIBRARY_PATH",
            "LOCALAPPDATA",
            "PATH",
            "PATHEXT",
            "PUPPETEER_CACHE_DIR",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "WINDIR",
            "XDG_CACHE_HOME",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed_environment}
        environment.update(
            {
                "AGENT_BROWSER_CONTENT_BOUNDARIES": "1",
                "AGENT_BROWSER_MAX_OUTPUT": "6000",
                "AGENT_BROWSER_ALLOWED_DOMAINS": allowed_domains,
                "AGENT_BROWSER_ACTION_POLICY": str(self.policy_path),
                "AGENT_BROWSER_DEFAULT_TIMEOUT": "25000",
                "AGENT_BROWSER_IDLE_TIMEOUT_MS": "15000",
                "AGENT_BROWSER_NO_AUTO_DIALOG": "1",
            }
        )
        return environment


def output_text(payload: Any, *preferred_keys: str) -> str:
    """Extract user-visible content from agent-browser's stable JSON envelope."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, str):
                return value
        for key in ("text", "content", "snapshot", "value", "url", "title"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return ""
