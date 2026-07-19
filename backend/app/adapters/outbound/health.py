from app.domain.health import HealthStatus


class MockHealthCheckAdapter:
    """Local liveness adapter; replaceable by dependency-aware checks later."""

    async def check(self) -> HealthStatus:
        return HealthStatus(status="ok")
