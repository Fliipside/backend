from fastapi import APIRouter

from app.schemas.relationship import RelationshipRequest
from app.services.relationship import infer_relationship

router = APIRouter()


@router.post("/infer")
async def infer(request: RelationshipRequest) -> None:
    """Provisional conversation endpoint; inference will be added later."""
    await infer_relationship(request)
