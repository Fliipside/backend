from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ImageResponse(BaseModel):
    image_id: UUID
    # Temporary signed URL; usable as <img src> without a token until url_expires_at.
    url: str
    url_expires_at: datetime
    content_type: str
    file_size: int
    create_at: datetime
