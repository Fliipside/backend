from pydantic import BaseModel, Field


class Message(BaseModel):
    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)


class RelationshipRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
