from app.domain.health import HealthStatus


class LivenessHealthCheckAdapter:
    """Process-level liveness adapter."""

    async def check(self) -> HealthStatus:
        return HealthStatus(status="ok")
