from fastapi import APIRouter

from ..models.domain import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.api_route("", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()
