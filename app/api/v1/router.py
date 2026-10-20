from fastapi import APIRouter

from app.api.v1 import emotion, relationship, voice

router = APIRouter()
router.include_router(voice.router, prefix="/voice", tags=["voice"])
router.include_router(emotion.router, prefix="/emotion", tags=["emotion"])
router.include_router(relationship.router, prefix="/relationship", tags=["relationship"])
