import os
import shlex

from app.harness.providers.cli import CliRuntime
from app.schemas.learning import AgentProvider


def get_runtime(provider: AgentProvider, agent_name: str | None = None):
    is_researcher = (agent_name or "").casefold() == "researcher"
    commands = {
        "codex": (["codex", "exec", "--json", "-"], "CODEX_COMMAND"),
        "gemini-cli": (["gemini"], "GEMINI_CLI_COMMAND"),
        "antigravity-cli": (["agy", "--output-format", "json"], "ANTIGRAVITY_CLI_COMMAND"),
    }
    command, env_var = commands[provider]
    gemini_override = shlex.split(os.getenv("GEMINI_CLI_COMMAND", ""))
    gemini_model_args = [] if any(flag in gemini_override for flag in ("--model", "-m")) else [
        "--model", os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
    ]
    gemini_role_args = [
        *gemini_model_args,
        "--output-format", "stream-json" if is_researcher else "json",
        "--approval-mode", "plan", "--allowed-mcp-server-names",
        "learning-browser" if is_researcher else "browser-disabled",
    ] if provider == "gemini-cli" else None
    if provider == "gemini-cli" and is_researcher:
        gemini_role_args.extend([
            "--allowed-tools",
            "mcp_learning-browser_browser_search,mcp_learning-browser_browser_read",
        ])
    return CliRuntime(
        provider, command, env_var,
        prompt_flag="-p" if provider == "gemini-cli" else None,
        stream_json=provider == "gemini-cli" and is_researcher,
        # Live Gemini calls routinely need more than the generic 120-second CLI
        # limit, including the plain JSON query-planning/selection stages that
        # deliberately run without browser tools.
        timeout_seconds=300 if provider == "gemini-cli" else None,
        required_args=gemini_role_args,
    )
