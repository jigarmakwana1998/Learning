from .auth import router as auth_router
from .courses import router as courses_router
from .health import router as health_router
from .research import router as research_router
from .observability import router as observability_router

__all__ = ["auth_router", "courses_router", "health_router", "research_router", "observability_router"]
