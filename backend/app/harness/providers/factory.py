from app.harness.providers.cli import CliRuntime
from app.schemas.learning import AgentProvider


class MockRuntime:
    name = "mock"
    async def execute(self, prompt: str) -> dict: return {"prompt_received": prompt}


def get_runtime(provider: AgentProvider):
    if provider == "mock": return MockRuntime()
    commands = {
        "codex": (["codex", "exec", "--json", "-"], "CODEX_COMMAND"),
        "gemini-cli": (["gemini", "--output-format", "json"], "GEMINI_CLI_COMMAND"),
        "antigravity-cli": (["agy", "--output-format", "json"], "ANTIGRAVITY_CLI_COMMAND"),
    }
    command, env_var = commands[provider]
    return CliRuntime(provider, command, env_var, prompt_flag="-p" if provider == "gemini-cli" else None)
