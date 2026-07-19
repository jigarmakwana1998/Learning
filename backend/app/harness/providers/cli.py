import asyncio
import json
import os
import shlex
import shutil


class CliRuntime:
    """Run a JSON-emitting CLI without exposing its authentication settings."""
    def __init__(self, name: str, default_command: list[str], override_env: str, prompt_flag: str | None = None):
        self.name = name
        self.command = shlex.split(os.getenv(override_env, "")) or default_command
        self.prompt_flag = prompt_flag

    async def execute(self, prompt: str) -> dict:
        command = [*self.command]
        environment = self._environment()
        # On Windows, npm exposes Gemini through a .cmd shim. Resolve it before
        # spawning so asyncio does not try to execute PowerShell's .ps1 wrapper.
        executable = shutil.which(command[0], path=environment.get("PATH") or environment.get("Path"))
        if executable:
            command[0] = executable
        stdin = asyncio.subprocess.PIPE
        prompt_bytes = prompt.encode()
        if self.prompt_flag:
            # create_subprocess_exec does not invoke a shell, so a learner prompt cannot
            # alter the command. Gemini's documented non-interactive interface uses -p.
            command.extend([self.prompt_flag, prompt])
            stdin = None
            prompt_bytes = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
        except FileNotFoundError as error:
            raise RuntimeError(f"{self.name} executable was not found. Install it or set its command override in .env.") from error

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt_bytes), timeout=int(os.getenv("AGENT_CLI_TIMEOUT_SECONDS", "120")),
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise RuntimeError(f"{self.name} timed out. Try again after checking provider availability.") from error
        if process.returncode != 0:
            # CLI stderr can contain provider diagnostics. Do not forward it because it
            # may include account or project details that do not belong in an API error.
            raise RuntimeError(f"{self.name} failed. Check its local authentication and configuration.")
        try:
            return self._parse_response(stdout.decode())
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError(f"{self.name} must emit one JSON object containing the requested result.") from error

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
    def _set_if_missing(environment: dict[str, str], destination: str, source: str) -> None:
        # os.environ.copy() can preserve an existing uppercase spelling on Windows.
        # Prefer the canonical key exactly; only use a case-insensitive lookup when
        # locating the source alias. On Linux, the two Gemini names are distinct.
        destination_value = environment.get(destination)
        source_value = environment.get(source)
        if source_value is None:
            source_value = next((value for key, value in environment.items() if key.casefold() == source.casefold()), None)
        if not destination_value and source_value:
            environment[destination] = source_value

    @staticmethod
    def _parse_response(output: str) -> dict:
        payload = json.loads(output)
        if not isinstance(payload, dict):
            raise TypeError("CLI output must be an object")
        # Gemini CLI's --output-format json envelope puts model output in response.
        # Other runtimes already emit the requested object directly.
        response = payload.get("response")
        if isinstance(response, dict):
            return response
        if isinstance(response, str):
            return json.loads(CliRuntime._without_markdown_fence(response))
        return payload

    @staticmethod
    def _without_markdown_fence(value: str) -> str:
        value = value.strip()
        if value.startswith("```") and value.endswith("```"):
            return value.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
        return value
