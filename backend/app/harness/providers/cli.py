import asyncio
import ipaddress
import json
import os
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class ToolInvocationEvent:
    """Sanitized provider tool telemetry safe to persist in the audit table."""

    tool_name: str
    status: str
    metadata: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class ProviderExecution:
    """Provider payload plus non-public execution evidence."""

    payload: dict
    tool_events: tuple[ToolInvocationEvent, ...] = ()
    visited_urls: frozenset[str] = field(default_factory=frozenset)


class _RateLimited(RuntimeError):
    def __init__(self, retry_after: float = 1.0):
        super().__init__("Provider rate limit exceeded")
        self.retry_after = max(0.0, min(retry_after, 60.0))


class CliRuntime:
    """Run a JSON-emitting CLI without exposing its authentication settings."""

    def __init__(
        self,
        name: str,
        default_command: list[str],
        override_env: str,
        prompt_flag: str | None = None,
        *,
        stream_json: bool = False,
        timeout_seconds: int | None = None,
        required_args: list[str] | None = None,
    ):
        self.name = name
        override = shlex.split(os.getenv(override_env, ""))
        base_command = override or self._project_local_command(default_command)
        self.command = [*base_command, *(required_args or [])]
        self.prompt_flag = prompt_flag
        self.stream_json = stream_json
        self.timeout_seconds = timeout_seconds

    async def execute(self, prompt: str) -> ProviderExecution:
        attempts = 2 if self.name == "gemini-cli" else 1
        for attempt in range(attempts):
            try:
                return await self._execute_once(prompt)
            except _RateLimited as error:
                if attempt + 1 >= attempts:
                    raise RuntimeError(
                        f"{self.name} rate limit exceeded. Try again after its quota resets."
                    ) from None
                await asyncio.sleep(error.retry_after)
        raise AssertionError("CLI retry loop exited unexpectedly")

    async def _execute_once(self, prompt: str) -> ProviderExecution:
        command = [*self.command]
        environment = self._environment()
        # On Windows, npm exposes Gemini through a .cmd shim. Resolve it before
        # spawning so asyncio does not try to execute PowerShell's .ps1 wrapper.
        executable = shutil.which(command[0], path=environment.get("PATH") or environment.get("Path"))
        if executable:
            command[0] = executable
        command = self._replace_windows_npm_shim(command)
        stdin = asyncio.subprocess.PIPE
        prompt_bytes = prompt.encode()
        if self.prompt_flag:
            # create_subprocess_exec does not invoke a shell, so a learner prompt cannot
            # alter the command. Gemini's documented non-interactive interface uses -p.
            command.extend([self.prompt_flag, prompt])
            stdin = None
            prompt_bytes = None
        try:
            process_group_options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                **process_group_options,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                f"{self.name} executable was not found. Install it or set its command override in .env."
            ) from error

        timeout = self.timeout_seconds or int(os.getenv("AGENT_CLI_TIMEOUT_SECONDS", "120"))
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(prompt_bytes), timeout=timeout)
        except TimeoutError as error:
            await self._terminate_process_tree(process)
            raise RuntimeError(
                f"{self.name} timed out. Try again after checking provider availability."
            ) from error

        stdout_text = stdout.decode(errors="replace")
        stderr_text = stderr.decode(errors="replace")
        if process.returncode != 0:
            retry_after = self._structured_rate_limit_delay(stdout_text, stderr_text)
            if retry_after is not None:
                raise _RateLimited(retry_after)
            # CLI diagnostics can contain account, project, prompt, or page details.
            raise RuntimeError(f"{self.name} failed. Check its local authentication and configuration.")
        try:
            return self._parse_stream_response(stdout_text) if self.stream_json else ProviderExecution(
                payload=self._parse_response(stdout_text)
            )
        except _RateLimited:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise RuntimeError(
                f"{self.name} must emit the configured JSON response format."
            ) from error

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        if self.name == "gemini-cli":
            # Support the lowercase names commonly used in local .env files while
            # keeping the CLI's canonical environment variables authoritative.
            self._set_if_missing(environment, "GEMINI_API_KEY", "gemini_api_key")
            self._set_if_missing(environment, "GOOGLE_API_KEY", "google_api_key")
            self._set_if_missing(environment, "GOOGLE_CLOUD_PROJECT", "project_id")
            # Gemini CLI refuses unattended prompts in an untrusted workspace.
            # This flag is scoped to the child process, never persisted in .env.
            environment.setdefault("GEMINI_CLI_TRUST_WORKSPACE", "true")
        return environment

    @staticmethod
    async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
        """Stop the provider and MCP descendants so inherited pipes cannot hang."""
        if process.returncode is not None:
            return
        if os.name == "nt":
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=10)
            except (FileNotFoundError, OSError, TimeoutError):
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()

    def _project_local_command(self, default_command: list[str]) -> list[str]:
        """Prefer the pinned repository CLI without relying on npm shell shims."""
        if self.name != "gemini-cli" or not default_command or default_command[0] != "gemini":
            return list(default_command)
        repository_root = Path(__file__).resolve().parents[4]
        script = repository_root / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script), *default_command[1:]]
        return list(default_command)

    @staticmethod
    def _replace_windows_npm_shim(command: list[str]) -> list[str]:
        """Resolve Gemini's npm batch shim so prompts never cross cmd.exe."""
        if os.name != "nt" or not command:
            return command
        executable = Path(command[0])
        if executable.suffix.casefold() not in {".cmd", ".bat", ".ps1"}:
            return command
        script = executable.parent / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script), *command[1:]]
        raise RuntimeError("gemini-cli must resolve to a native executable or its installed Node entry point.")

    @staticmethod
    def _set_if_missing(environment: dict[str, str], destination: str, source: str) -> None:
        destination_value = environment.get(destination)
        source_value = environment.get(source)
        if source_value is None:
            source_value = next(
                (value for key, value in environment.items() if key.casefold() == source.casefold()), None
            )
        if not destination_value and source_value:
            environment[destination] = source_value

    @staticmethod
    def _parse_response(output: str) -> dict:
        payload = json.loads(output)
        if not isinstance(payload, dict):
            raise TypeError("CLI output must be an object")
        response = payload.get("response")
        if isinstance(response, dict):
            return response
        if isinstance(response, str):
            result = json.loads(CliRuntime._without_markdown_fence(response))
            if not isinstance(result, dict):
                raise TypeError("CLI response must be an object")
            return result
        return payload

    @classmethod
    def _parse_stream_response(cls, output: str) -> ProviderExecution:
        events: list[dict[str, Any]] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise TypeError("Gemini stream events must be objects")
            events.append(event)

        rate_delay = cls._rate_limit_from_objects(events)
        final_event = next((event for event in reversed(events) if event.get("type") == "result"), None)
        if final_event is None:
            if rate_delay is not None:
                raise _RateLimited(rate_delay)
            raise ValueError("Gemini stream did not contain a result event")

        response = final_event.get("response")
        if isinstance(response, dict):
            payload = response
        elif isinstance(response, str):
            payload = json.loads(cls._without_markdown_fence(response))
        elif isinstance(final_event.get("result"), dict):
            payload = final_event["result"]
        else:
            raise TypeError("Gemini result response must be a JSON object")
        if not isinstance(payload, dict):
            raise TypeError("Gemini result response must be a JSON object")

        tool_events, visited_urls = cls._tool_invocations(events)
        return ProviderExecution(payload, tuple(tool_events), frozenset(visited_urls))

    @classmethod
    def _tool_invocations(
        cls, events: list[dict[str, Any]]
    ) -> tuple[list[ToolInvocationEvent], set[str]]:
        pending: dict[str, dict[str, Any]] = {}
        completed: list[ToolInvocationEvent] = []
        visited_urls: set[str] = set()
        sequence = 0

        for event in events:
            event_type = event.get("type")
            if event_type == "tool_use":
                sequence += 1
                key = str(event.get("tool_id") or event.get("id") or sequence)
                pending[key] = event
                continue
            if event_type != "tool_result":
                continue

            key = str(event.get("tool_id") or event.get("id") or "")
            use = pending.pop(key, {})
            tool_name = str(
                event.get("tool_name") or event.get("name") or use.get("tool_name") or use.get("name") or "unknown"
            )[:80]
            raw_status = str(event.get("status") or ("failed" if event.get("error") else "success")).casefold()
            status = "success" if raw_status in {"success", "succeeded", "completed", "ok"} else "failed"
            output = event.get("output", event.get("result", event.get("content")))
            urls = cls._extract_urls(output)
            if tool_name == "browser_read" and status == "success":
                visited_urls.update(cls._successful_read_urls(output))
            metadata = cls._audit_metadata(urls, output)
            completed.append(
                ToolInvocationEvent(
                    tool_name=tool_name,
                    status=status,
                    metadata=metadata or None,
                    error=None if status == "success" else "Tool invocation failed",
                    duration_ms=cls._duration_ms(use, event),
                )
            )

        for use in pending.values():
            tool_name = str(use.get("tool_name") or use.get("name") or "unknown")[:80]
            completed.append(ToolInvocationEvent(tool_name, "failed", error="Tool result was not returned"))
        return completed, visited_urls

    @classmethod
    def _audit_metadata(cls, urls: set[str], output: Any) -> dict[str, Any]:
        sorted_urls = sorted(urls)[:20]
        domains = sorted({urlsplit(url).hostname for url in sorted_urls if urlsplit(url).hostname})
        result_count = cls._result_count(output)
        metadata: dict[str, Any] = {}
        if sorted_urls:
            metadata["urls"] = sorted_urls
            metadata["domains"] = domains
        if result_count is not None:
            metadata["result_count"] = result_count
        return metadata

    @classmethod
    def _extract_urls(cls, value: Any) -> set[str]:
        urls: set[str] = set()
        for payload in cls._gateway_payloads(value):
            for key in ("results", "pages", "sources"):
                items = payload.get(key)
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    for url_key in ("url", "final_url"):
                        normalized = cls._normalize_public_url(str(item.get(url_key, "")))
                        if normalized:
                            urls.add(normalized)
        return urls

    @classmethod
    def _successful_read_urls(cls, value: Any) -> set[str]:
        """Return only final URLs for page-level successful browser reads."""
        successful: set[str] = set()
        for payload in cls._gateway_payloads(value):
            pages = payload.get("pages")
            if not isinstance(pages, list):
                continue
            for page in pages:
                if not isinstance(page, dict) or str(page.get("status", "")).casefold() != "ok":
                    continue
                normalized = cls._normalize_public_url(str(page.get("url", "")))
                if normalized:
                    successful.add(normalized)
        return successful

    @classmethod
    def _gateway_payloads(cls, value: Any, depth: int = 0) -> list[dict[str, Any]]:
        """Unwrap MCP transport envelopes without interpreting page bodies."""
        if depth > 4:
            return []
        decoded = cls._decode_embedded_json(value)
        if decoded is not value:
            return cls._gateway_payloads(decoded, depth + 1)
        if isinstance(value, dict):
            if any(isinstance(value.get(key), list) for key in ("results", "pages", "sources")):
                return [value]
            payloads: list[dict[str, Any]] = []
            for key in ("structuredContent", "structured_content", "content", "result", "output"):
                child = value.get(key)
                if key == "content" and isinstance(child, list):
                    for block in child:
                        if isinstance(block, dict) and block.get("type") == "text":
                            payloads.extend(cls._gateway_payloads(block.get("text"), depth + 1))
                else:
                    payloads.extend(cls._gateway_payloads(child, depth + 1))
            return payloads
        if isinstance(value, list):
            payloads = []
            for item in value:
                if isinstance(item, dict) and item.get("type") == "text":
                    payloads.extend(cls._gateway_payloads(item.get("text"), depth + 1))
            return payloads
        return []

    @classmethod
    def _decode_embedded_json(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped.startswith(("{", "[")):
            return value
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value

    @staticmethod
    def _normalize_public_url(value: str) -> str | None:
        try:
            parts = urlsplit(value)
            if parts.scheme.casefold() != "https" or not parts.hostname or parts.username or parts.password:
                return None
            hostname = parts.hostname.casefold().rstrip(".").encode("idna").decode("ascii")
            port = parts.port
            if port not in (None, 443):
                return None
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                pass
            else:
                return None
            if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
                (".localhost", ".local", ".internal", ".home.arpa")
            ):
                return None
            return urlunsplit(("https", hostname, parts.path or "/", parts.query, ""))
        except (UnicodeError, ValueError):
            return None

    @classmethod
    def _result_count(cls, output: Any) -> int | None:
        counts: list[int] = []
        for value in cls._gateway_payloads(output):
            for key in ("results", "pages", "sources"):
                if isinstance(value.get(key), list):
                    counts.append(len(value[key]))
                    break
        return sum(counts) if counts else None

    @staticmethod
    def _duration_ms(start: dict[str, Any], end: dict[str, Any]) -> int | None:
        explicit = end.get("duration_ms") or end.get("durationMs")
        if isinstance(explicit, (int, float)) and explicit >= 0:
            return int(explicit)
        try:
            started = datetime.fromisoformat(str(start["timestamp"]).replace("Z", "+00:00"))
            finished = datetime.fromisoformat(str(end["timestamp"]).replace("Z", "+00:00"))
            return max(0, int((finished - started).total_seconds() * 1000))
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def _structured_rate_limit_delay(cls, *outputs: str) -> float | None:
        objects: list[Any] = []
        for output in outputs:
            try:
                objects.append(json.loads(output))
                continue
            except json.JSONDecodeError:
                pass
            for line in output.splitlines():
                try:
                    objects.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return cls._rate_limit_from_objects(objects)

    @classmethod
    def _rate_limit_from_objects(cls, objects: list[Any]) -> float | None:
        rate_limited = False
        retry_after: float | None = None

        def visit(value: Any, key: str = "") -> None:
            nonlocal rate_limited, retry_after
            if isinstance(value, dict):
                for child_key, child in value.items():
                    normalized_key = str(child_key).casefold().replace("-", "_")
                    if normalized_key in {"code", "status"} and (
                        child == 429 or str(child).upper() == "RESOURCE_EXHAUSTED"
                    ):
                        rate_limited = True
                    if normalized_key in {
                        "retry_after", "retry_after_seconds", "retryafter", "retry_delay", "retrydelay"
                    }:
                        try:
                            retry_after = float(str(child).removesuffix("s"))
                        except (TypeError, ValueError):
                            pass
                    visit(child, normalized_key)
            elif isinstance(value, list):
                for child in value:
                    visit(child, key)

        for item in objects:
            visit(item)
        return max(0.0, min(retry_after if retry_after is not None else 1.0, 60.0)) if rate_limited else None

    @staticmethod
    def _without_markdown_fence(value: str) -> str:
        value = value.strip()
        if value.startswith("```") and value.endswith("```"):
            return value.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
        return value
