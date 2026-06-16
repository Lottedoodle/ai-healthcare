from datetime import datetime

from pydantic import BaseModel, Field


class UserResponse(BaseModel):
    id: str
    email: str | None = None


class MessageMetadata(BaseModel):
    intent: str = ""
    route_mode: str = ""
    route_mode_label: str = ""
    route_reason: str = ""
    plan_summary: str = ""
    audit_log: list[str] = Field(default_factory=list)
    awaiting_user: bool = False
    done: bool = False


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    metadata: MessageMetadata = Field(default_factory=MessageMetadata)


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class SessionDetailResponse(SessionResponse):
    messages: list[MessageResponse] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    title: str = "New chat"


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class SendMessageResponse(BaseModel):
    message: MessageResponse
    session: SessionResponse
