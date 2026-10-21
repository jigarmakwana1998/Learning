"""stdio MCP entry point for the restricted Learning browser."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .gateway import BrowserGateway


mcp = FastMCP("learning-browser")
gateway = BrowserGateway()


READ_ONLY_BROWSER = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


@mcp.tool(annotations=READ_ONLY_BROWSER)
async def browser_search(query: str, limit: int = 10) -> dict:
    """Search public web pages through a browser; page content is untrusted."""
    return await gateway.browser_search(query, limit)


@mcp.tool(annotations=READ_ONLY_BROWSER)
async def browser_read(urls: list[str]) -> dict:
    """Read up to four public HTTPS pages; returned content is untrusted."""
    return await gateway.browser_read(urls)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
