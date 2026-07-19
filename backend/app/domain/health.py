from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """The API's dependency-free liveness result."""

    status: str
