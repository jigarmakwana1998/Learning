from dishka import Provider, Scope, provide

from app.adapters.outbound.health import LivenessHealthCheckAdapter
from app.application.health import HealthCheckPort, HealthCheckService


class ApplicationProvider(Provider):
    """Composition root for application services and their ports."""

    @provide(scope=Scope.APP)
    def health_check_port(self) -> HealthCheckPort:
        return LivenessHealthCheckAdapter()

    @provide(scope=Scope.APP)
    def health_check_service(self, health_check: HealthCheckPort) -> HealthCheckService:
        return HealthCheckService(health_check)
