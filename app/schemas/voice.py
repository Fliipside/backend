from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.voice import VOICEPRINT_DIMENSIONS


class AIVoiceprint(BaseModel):
    """data of ai POST voice/enroll."""

    engine: str = Field(min_length=1, max_length=50)
    vector: list[float] = Field(
        min_length=VOICEPRINT_DIMENSIONS,
        max_length=VOICEPRINT_DIMENSIONS,
    )


class VoiceSpeaker(BaseModel):
    speaker: str
    role: str
    speech_seconds: float


class VoiceUtterance(BaseModel):
    start: float
    end: float
    speaker: str
    role: str
    text: str


class VoiceAnalysisResult(BaseModel):
    """data of ai POST voice/analyze, stored as the job result."""

    speakers: list[VoiceSpeaker]
    utterances: list[VoiceUtterance]


class VoiceEnrollResponse(BaseModel):
    engine: str
    dimensions: int
    update_at: datetime


class VoiceAnalysisCreateResponse(BaseModel):
    job_id: UUID
    status: str
    create_at: datetime


class VoiceAnalysisResponse(BaseModel):
    job_id: UUID
    status: str
    original_filename: str
    used_voiceprint: bool
    error_code: str | None
    error_message: str | None
    result: dict[str, Any] | None
    create_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
