from fastapi import UploadFile

from app.core.errors import FeatureNotReadyError


async def infer_voice(file: UploadFile) -> None:
    # Validate the upload and call the separate voice AI service here.
    raise FeatureNotReadyError("voice")
