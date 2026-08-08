from app.core.config import get_settings
from app.harness.providers.cli import CliRuntime
from app.schemas.learning import AgentHarness


def get_runtime(harness: AgentHarness, agent_name: str | None = None):
    """Select a live harness while enforcing LiteLLM as its model transport."""
    settings = get_settings()
    is_researcher = (agent_name or "").casefold() == "researcher"
    commands = {
        "codex": (["codex", "exec"], "CODEX_COMMAND"),
        "gemini-cli": (["gemini"], "GEMINI_CLI_COMMAND"),
        "antigravity-cli": (["agy"], "ANTIGRAVITY_CLI_COMMAND"),
    }
    command, env_var = commands[harness]
    required_args = {
        "codex": [
            "--json", "--model", settings.litellm_model,
            "-c", 'model_provider="litellm"',
            "-c", 'model_providers.litellm.name="LiteLLM"',
            "-c", f'model_providers.litellm.base_url="{settings.litellm_base_url.rstrip("/")}/v1"',
            "-c", 'model_providers.litellm.env_key="LITELLM_API_KEY"',
            "-c", 'model_providers.litellm.wire_api="responses"', "-",
        ],
        "gemini-cli": [
            "--model", settings.litellm_model,
            "--output-format", "stream-json" if is_researcher else "json",
            "--approval-mode", "plan",
            "--allowed-mcp-server-names", "learning-browser" if is_researcher else "browser-disabled",
        ],
        "antigravity-cli": [
            "--print", "--model", settings.litellm_model,
            "--output-format", "stream-json",
        ],
    }[harness]
    if harness == "gemini-cli" and is_researcher:
        required_args.extend([
            "--allowed-tools",
            "mcp_learning-browser_browser_search,mcp_learning-browser_browser_read",
        ])
    return CliRuntime(
        harness,
        command,
        env_var,
        prompt_flag="-p" if harness == "gemini-cli" else None,
        stream_json=(harness == "gemini-cli" and is_researcher) or harness == "antigravity-cli",
        timeout_seconds=300 if harness == "gemini-cli" else None,
        required_args=required_args,
    )
