from app.harness.providers.cli import CliRuntime
from app.schemas.learning import AgentProvider


class MockRuntime:
    name = "mock"
    async def execute(self, prompt: str) -> dict: return {"prompt_received": prompt}


def get_runtime(provider: AgentProvider, agent_name: str | None = None):
    if provider == "mock": return MockRuntime()
    is_researcher = (agent_name or "").casefold() == "researcher"
    commands = {
        "codex": (["codex", "exec", "--json", "-"], "CODEX_COMMAND"),
        "gemini-cli": (["gemini"], "GEMINI_CLI_COMMAND"),
        "antigravity-cli": (["agy", "--output-format", "json"], "ANTIGRAVITY_CLI_COMMAND"),
    }
    command, env_var = commands[provider]
    gemini_role_args = [
        "--output-format", "stream-json" if is_researcher else "json",
        "--approval-mode", "plan", "--allowed-mcp-server-names",
        "learning-browser" if is_researcher else "browser-disabled",
    ] if provider == "gemini-cli" else None
    return CliRuntime(
        provider, command, env_var,
        prompt_flag="-p" if provider == "gemini-cli" else None,
        stream_json=provider == "gemini-cli" and is_researcher,
        timeout_seconds=300 if provider == "gemini-cli" and is_researcher else None,
        required_args=gemini_role_args,
    )
