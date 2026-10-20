from fastapi import APIRouter, File, UploadFile

from app.services.voice import infer_voice

router = APIRouter()


@router.post("/infer")
async def infer(file: UploadFile = File(...)) -> None:
    """Provisional audio upload endpoint; inference will be added later."""
    await infer_voice(file)
