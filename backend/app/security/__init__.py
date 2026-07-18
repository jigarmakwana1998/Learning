"""Security boundaries for untrusted agent-authored data."""

from .write_guard import AgentWriteContext, ClaimWrite, ResourceWrite, WriteGuard

__all__ = ["AgentWriteContext", "ClaimWrite", "ResourceWrite", "WriteGuard"]
