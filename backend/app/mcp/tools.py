"""Capability contracts to expose through an MCP server, not raw unrestricted tools."""
from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict = Field(default_factory=dict)


RESEARCH_TOOLS = [
    ToolDefinition(name="search_web", description="Search approved web sources.", input_schema={"query": "string"}),
    ToolDefinition(name="fetch_source", description="Fetch an allowed public URL.", input_schema={"url": "string"}),
    ToolDefinition(name="rank_sources", description="Rank sources by authority and learner fit.", input_schema={"sources": "array"}),
]
LEARNING_TOOLS = [
    ToolDefinition(name="get_progress", description="Read learner progress.", input_schema={"learner_id": "string"}),
    ToolDefinition(name="record_assessment", description="Save a validated outcome.", input_schema={"run_id": "string", "score": "number"}),
]
