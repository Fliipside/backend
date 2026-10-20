from pydantic import BaseModel, Field


class EmotionRequest(BaseModel):
    text: str = Field(min_length=1)
