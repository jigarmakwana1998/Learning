from .auth import router as auth_router
from .health import router as health_router
from .learning import router as learning_router
from .observability import router as observability_router

__all__ = ["auth_router", "health_router", "learning_router", "observability_router"]
