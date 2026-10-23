from datetime import datetime

from pydantic import BaseModel, Field

from course_mcp.course import Chapter, WrittenSentence


class CourseSource(BaseModel):
    id: str
    url: str
    title: str


class CourseVersion(BaseModel):
    id: str
    version: int
    status: str
    created_at: datetime


class CourseView(CourseVersion):
    research_run_id: str
    topic: str
    error: str | None = None
    activity: str | None = None
    gaps: list[str] = Field(default_factory=list, description="Coverage questions no written section teaches.")
    chapters: list[Chapter] = Field(default_factory=list)
    sections: dict[str, list[list[WrittenSentence]]] = Field(default_factory=dict)
    sources: list[CourseSource] = Field(default_factory=list)
