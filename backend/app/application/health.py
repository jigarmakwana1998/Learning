from typing import Protocol

from app.domain.health import HealthStatus


class HealthCheckPort(Protocol):
    """Port used by the health use case to obtain a liveness result."""

    async def check(self) -> HealthStatus: ...


class HealthCheckService:
    """A small vertical slice proving adapters are reached through a port."""

    def __init__(self, health_check: HealthCheckPort) -> None:
        self._health_check = health_check

    async def execute(self) -> HealthStatus:
        return await self._health_check.check()
