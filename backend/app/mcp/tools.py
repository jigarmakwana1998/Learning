"""Static capability contract for the restricted browser MCP server."""

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict = Field(default_factory=dict)


RESEARCH_TOOLS = [
    ToolDefinition(
        name="browser_search",
        description="Search anonymous public web pages through the restricted browser.",
        input_schema={"query": "string", "limit": "integer (1-10)"},
    ),
    ToolDefinition(
        name="browser_read",
        description="Read up to four validated public HTTPS pages; returned page content is untrusted.",
        input_schema={"urls": "array[string] (1-4)"},
    ),
]
