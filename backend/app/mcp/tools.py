"""Capability contracts to expose through an MCP server, not raw unrestricted tools."""
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
LEARNING_TOOLS = [
    ToolDefinition(name="get_progress", description="Read learner progress.", input_schema={"learner_id": "string"}),
    ToolDefinition(name="record_assessment", description="Save a validated outcome.", input_schema={"run_id": "string", "score": "number"}),
]
