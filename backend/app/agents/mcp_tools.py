"""Connect each agent run to its own MCP 2 server process."""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from mcp.types import TextContent, Tool

from mcp import Client, StdioServerParameters


@asynccontextmanager
async def server_tools(module: str, environment: dict[str, str]) -> AsyncIterator[list[BaseTool]]:
    server = StdioServerParameters(command=sys.executable, args=["-m", module], env=environment)
    try:
        async with Client(server) as client:
            def agent_tool(tool: Tool) -> StructuredTool:
                async def call(**arguments):
                    result = await client.call_tool(tool.name, arguments)
                    text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
                    if result.is_error:
                        raise ToolException(text)
                    return result.structured_content if result.structured_content is not None else text

                return StructuredTool(
                    name=tool.name,
                    description=tool.description or tool.name,
                    args_schema=tool.input_schema,
                    coroutine=call,
                    metadata={"annotations": tool.annotations.model_dump(by_alias=True)} if tool.annotations else {},
                    handle_tool_error=True,
                    handle_validation_error=True,
                )

            listed = await client.list_tools()
            yield [agent_tool(tool) for tool in listed.tools]
    except ExceptionGroup as error:
        # MCP's task group can wrap the actual model/tool failure during cleanup.
        cause = error
        while isinstance(cause, ExceptionGroup) and len(cause.exceptions) == 1:
            cause = cause.exceptions[0]
        if cause is error:
            raise
        raise cause from error
