import json
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.auth import get_authenticated_user, get_current_user
from backend.schemas import (
    CreateSessionRequest,
    MessageMetadata,
    MessageResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionDetailResponse,
    SessionResponse,
    UserResponse,
)
from backend.service import ChatMessage, ChatSession, chat_service

app = FastAPI(title="Medical Triage API", version="0.1.0")

origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _msg_to_response(msg: ChatMessage) -> MessageResponse:
    meta = msg.metadata or {}
    return MessageResponse(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        created_at=msg.created_at,
        metadata=MessageMetadata(**meta) if meta else MessageMetadata(),
    )


def _session_to_response(session: ChatSession) -> SessionResponse:
    count = session.message_count if session.message_count else len(session.messages)
    return SessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=count,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/me", response_model=UserResponse)
async def me(user: dict = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user["id"], email=user.get("email"))


@app.get("/api/sessions", response_model=list[SessionResponse])
async def list_sessions(user: dict = Depends(get_authenticated_user)) -> list[SessionResponse]:
    try:
        sessions = chat_service.list_sessions(user["id"])
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [_session_to_response(s) for s in sessions]


@app.post("/api/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(get_authenticated_user),
) -> SessionResponse:
    try:
        session = chat_service.create_session(user["id"], body.title)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _session_to_response(session)


@app.get("/api/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    user: dict = Depends(get_authenticated_user),
) -> SessionDetailResponse:
    try:
        session = chat_service.get_session(session_id, user["id"])
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    base = _session_to_response(session)
    return SessionDetailResponse(
        **base.model_dump(),
        messages=[_msg_to_response(m) for m in session.messages],
    )


@app.delete("/api/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user: dict = Depends(get_authenticated_user)) -> None:
    if not chat_service.delete_session(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/api/sessions/{session_id}/messages", response_model=SendMessageResponse)
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    user: dict = Depends(get_authenticated_user),
) -> SendMessageResponse:
    try:
        session, _ = await chat_service.send_message(session_id, user["id"], body.content.strip())
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent error: {exc}") from exc

    assistant = session.messages[-1]
    return SendMessageResponse(
        message=_msg_to_response(assistant),
        session=_session_to_response(session),
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@app.post("/api/sessions/{session_id}/messages/stream")
async def send_message_stream(
    session_id: str,
    body: SendMessageRequest,
    user: dict = Depends(get_authenticated_user),
) -> StreamingResponse:
    content = body.content.strip()

    async def event_generator():
        async for item in chat_service.send_message_stream(session_id, user["id"], content):
            event_type = item.get("type", "message")
            payload = {k: v for k, v in item.items() if k != "type"}
            if event_type == "error":
                status_code = payload.pop("status", 503)
                if status_code == 404:
                    payload["detail"] = "Session not found"
                yield _sse("error", payload)
                return
            yield _sse(event_type, payload)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
