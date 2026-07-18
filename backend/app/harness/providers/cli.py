import asyncio
import json
import os
import shlex


class CliRuntime:
    """Prompts travel over stdin, never a shell command, to prevent command injection."""
    def __init__(self, name: str, default_command: list[str], override_env: str):
        self.name = name
        self.command = shlex.split(os.getenv(override_env, "")) or default_command

    async def execute(self, prompt: str) -> dict:
        process = await asyncio.create_subprocess_exec(*self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate(prompt.encode())
        if process.returncode != 0: raise RuntimeError(f"{self.name} failed: {stderr.decode()[:300]}")
        try: return json.loads(stdout.decode())
        except json.JSONDecodeError as error: raise RuntimeError(f"{self.name} must emit one JSON object; set its command override in .env.") from error
