from fastapi import APIRouter

from app.schemas.relationship import RelationshipRequest
from app.schemas.response import ApiResponse
from app.services.relationship import infer_relationship

router = APIRouter()


@router.post("/infer", response_model=ApiResponse[None])
async def infer(request: RelationshipRequest) -> ApiResponse[None]:
    await infer_relationship(request)
    return ApiResponse[None].ok()
