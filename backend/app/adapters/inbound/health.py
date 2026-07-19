from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter
from pydantic import BaseModel

from app.application.health import HealthCheckService


router = APIRouter(tags=["system"], route_class=DishkaRoute)


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse, summary="Check API liveness")
async def health(service: FromDishka[HealthCheckService]) -> HealthResponse:
    result = await service.execute()
    return HealthResponse(status=result.status)
