from fastapi import APIRouter, File, UploadFile

from app.services.voice import infer_voice
from app.schemas.response import ApiResponse

router = APIRouter()


@router.post("/infer", response_model=ApiResponse[None])
async def infer(file: UploadFile = File(...)) -> ApiResponse[None]:
    await infer_voice(file)
    return ApiResponse[None].ok()
