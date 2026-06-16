from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.agent.graph import (
    AgentState,
    build_graph,
    format_agent_result,
    fresh_state,
    next_agent_state,
)
from backend.data.agent_state_codec import (
    deserialize_agent_state,
    parse_timestamp,
    serialize_agent_state,
)
from backend.data import chat_store
from backend.data.chat_store import ChatStoreError
from backend.data.conversation_summary import prepare_conversation_context

_STREAM_STATUS_BY_NODE = {
    "triage_validator_node": "กำลังตรวจสอบคำถามและ intent...",
    "route_after_triage": "กำลังเลือกวิธีตอบ...",
    "prepare_agent_node": "กำลังค้นหาข้อมูลจาก knowledge base...",
    "tools_node": "กำลังค้นหาข้อมูล / เรียก tools...",
    "planner_node": "กำลังวางแผนการตอบ...",
    "plan_executor_node": "กำลังดำเนินการตามแผน...",
    "dose_pipeline_node": "กำลังคำนวณ dose...",
    "fast_node": "กำลังสรุปคำตอบ...",
    "agent_node": "กำลังสรุปคำตอบ...",
}
_USER_ANSWER_STREAM_NODES = frozenset({"agent_node", "fast_node", "plan_executor_node"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _chunk_text_content(chunk) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text", "")))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content) if content else ""


def _chunk_has_tool_calls(chunk) -> bool:
    tool_chunks = getattr(chunk, "tool_call_chunks", None)
    if tool_chunks:
        return True
    tool_calls = getattr(chunk, "tool_calls", None)
    return bool(tool_calls)


def _stream_event(event_type: str, **payload) -> dict:
    return {"type": event_type, **payload}


@dataclass
class ChatMessage:
    id: str
    role: str  # user | assistant
    content: str
    created_at: datetime = field(default_factory=_utcnow)
    metadata: dict = field(default_factory=dict)


@dataclass
class ChatSession:
    id: str
    user_id: str
    title: str
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    messages: list[ChatMessage] = field(default_factory=list)
    agent_state: AgentState = field(default_factory=fresh_state)
    message_count: int = 0
    conversation_summary: str = ""
    summary_message_count: int = 0


def _row_to_message(row: dict) -> ChatMessage:
    return ChatMessage(
        id=str(row["id"]),
        role=row["role"],
        content=row["content"],
        created_at=parse_timestamp(row["created_at"]),
        metadata=row.get("metadata") or {},
    )


def _row_to_session(row: dict, *, messages: list[ChatMessage] | None = None) -> ChatSession:
    return ChatSession(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        title=row["title"],
        created_at=parse_timestamp(row["created_at"]),
        updated_at=parse_timestamp(row["updated_at"]),
        messages=messages or [],
        agent_state=deserialize_agent_state(row.get("agent_state")),
        message_count=int(row.get("message_count", len(messages or []))),
        conversation_summary=row.get("conversation_summary") or "",
        summary_message_count=int(row.get("summary_message_count") or 0),
    )


class ChatService:
    def __init__(self) -> None:
        self._graph = build_graph()

    def list_sessions(self, user_id: str) -> list[ChatSession]:
        try:
            rows = chat_store.list_sessions(user_id)
        except ChatStoreError as exc:
            raise RuntimeError(str(exc)) from exc
        return [_row_to_session(row) for row in rows]

    def get_session(self, session_id: str, user_id: str) -> ChatSession | None:
        try:
            row = chat_store.get_session_row(session_id, user_id)
            if not row:
                return None
            msg_rows = chat_store.list_messages(session_id)
            messages = [_row_to_message(m) for m in msg_rows]
            session = _row_to_session(row, messages=messages)
            session.message_count = len(messages)
            return session
        except ChatStoreError as exc:
            raise RuntimeError(str(exc)) from exc

    def create_session(self, user_id: str, title: str = "New chat") -> ChatSession:
        try:
            row = chat_store.create_session_row(user_id, title)
            return _row_to_session(row)
        except ChatStoreError as exc:
            raise RuntimeError(str(exc)) from exc

    def delete_session(self, session_id: str, user_id: str) -> bool:
        try:
            return chat_store.delete_session_row(session_id, user_id)
        except ChatStoreError:
            return False

    async def send_message(self, session_id: str, user_id: str, content: str) -> tuple[ChatSession, dict]:
        session: ChatSession | None = None
        payload: dict | None = None
        async for event in self.send_message_stream(session_id, user_id, content):
            if event["type"] == "done":
                session = event["session"]
                payload = event["payload"]
            elif event["type"] == "error":
                if event.get("status") == 404:
                    raise KeyError("session_not_found")
                raise RuntimeError(str(event.get("detail", "Stream failed")))
        if not session or not payload:
            raise RuntimeError("Stream ended without result")
        row_session = self.get_session(session_id, user_id)
        if not row_session:
            raise KeyError("session_not_found")
        return row_session, payload

    async def send_message_stream(
        self,
        session_id: str,
        user_id: str,
        content: str,
    ) -> AsyncIterator[dict]:
        try:
            async for event in self._send_message_stream(session_id, user_id, content):
                yield event
        except KeyError:
            yield _stream_event("error", detail="session_not_found", status=404)
        except ChatStoreError as exc:
            yield _stream_event("error", detail=str(exc), status=503)
        except Exception as exc:
            yield _stream_event("error", detail=f"Agent error: {exc}", status=503)

    async def _send_message_stream(
        self,
        session_id: str,
        user_id: str,
        content: str,
    ) -> AsyncIterator[dict]:
        session = self.get_session(session_id, user_id)
        if not session:
            raise KeyError("session_not_found")

        yield _stream_event("status", text="กำลังบันทึกข้อความ...")

        user_msg = ChatMessage(
            id=str(uuid.uuid4()),
            role="user",
            content=content,
        )

        inserted_user = chat_store.insert_message_row(
            session_id,
            role="user",
            content=content,
        )
        user_msg.id = str(inserted_user["id"])
        user_msg.created_at = parse_timestamp(inserted_user["created_at"])
        session.messages.append(user_msg)

        yield _stream_event("status", text="กำลังเตรียม context การสนทนา...")

        message_pairs = [(m.role, m.content) for m in session.messages]
        conv_ctx = prepare_conversation_context(
            message_pairs,
            existing_summary=session.conversation_summary,
            summary_message_count=session.summary_message_count,
        )
        session.conversation_summary = conv_ctx.conversation_summary
        session.summary_message_count = conv_ctx.summary_message_count

        new_title = session.title
        if session.title == "New chat" and content.strip():
            new_title = content.strip()[:48] + ("..." if len(content.strip()) > 48 else "")

        state = dict(session.agent_state)
        state["user_input"] = content
        state["conversation_summary"] = conv_ctx.conversation_summary
        state["recent_conversation"] = conv_ctx.recent_conversation

        result: AgentState | None = None
        streamed_tokens = False
        answer_started = False
        streamed_answer_parts: list[str] = []
        llm_runs_with_tools: set[str] = set()
        seen_status_nodes: set[str] = set()

        async for event in self._graph.astream_events(state, version="v2"):
            kind = event.get("event")
            metadata = event.get("metadata") or {}
            node = metadata.get("langgraph_node", "")

            if kind == "on_chain_start" and node in _STREAM_STATUS_BY_NODE:
                if node not in seen_status_nodes:
                    seen_status_nodes.add(node)
                    yield _stream_event("status", text=_STREAM_STATUS_BY_NODE[node])

            if kind == "on_chat_model_stream" and node in _USER_ANSWER_STREAM_NODES:
                run_id = event.get("run_id", "")
                run_key = f"{node}:{run_id}"
                chunk = event.get("data", {}).get("chunk")
                if chunk is None:
                    continue
                if _chunk_has_tool_calls(chunk):
                    llm_runs_with_tools.add(run_key)
                    continue
                if run_key in llm_runs_with_tools:
                    continue
                piece = _chunk_text_content(chunk)
                if not piece:
                    continue
                if not answer_started:
                    yield _stream_event("start", content="")
                    answer_started = True
                streamed_tokens = True
                streamed_answer_parts.append(piece)
                yield _stream_event("token", content=piece)

            if kind == "on_chain_end" and event.get("name") == "LangGraph":
                result = event.get("data", {}).get("output")

        if result is None:
            result = await self._graph.ainvoke(state)

        session.agent_state = next_agent_state(result)
        payload = format_agent_result(result)
        answer = payload["content"]

        if answer and not streamed_tokens:
            if not answer_started:
                yield _stream_event("start", content="")
            yield _stream_event("token", content=answer)
        elif answer and streamed_answer_parts:
            streamed_answer = "".join(streamed_answer_parts)
            if streamed_answer != answer:
                remainder = answer[len(streamed_answer) :]
                if remainder:
                    yield _stream_event("token", content=remainder)

        assistant_metadata = {
            "intent": payload["intent"],
            "route_mode": payload["route_mode"],
            "route_mode_label": payload["route_mode_label"],
            "route_reason": payload["route_reason"],
            "plan_summary": payload["plan_summary"],
            "audit_log": payload["audit_log"],
            "awaiting_user": payload["awaiting_user"],
            "done": payload["done"],
        }

        inserted_assistant = chat_store.insert_message_row(
            session_id,
            role="assistant",
            content=answer,
            metadata=assistant_metadata,
        )
        chat_store.update_session_row(
            session_id,
            title=new_title,
            agent_state=serialize_agent_state(session.agent_state),
            conversation_summary=session.conversation_summary,
            summary_message_count=session.summary_message_count,
        )

        assistant_msg = ChatMessage(
            id=str(inserted_assistant["id"]),
            role="assistant",
            content=answer,
            created_at=parse_timestamp(inserted_assistant["created_at"]),
            metadata=assistant_metadata,
        )
        session.messages.append(assistant_msg)
        session.title = new_title
        session.updated_at = _utcnow()
        session.message_count = len(session.messages)

        yield _stream_event(
            "done",
            message={
                "id": assistant_msg.id,
                "role": assistant_msg.role,
                "content": assistant_msg.content,
                "created_at": assistant_msg.created_at.isoformat(),
                "metadata": assistant_metadata,
            },
            session={
                "id": session.id,
                "title": session.title,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "message_count": session.message_count,
            },
            payload=payload,
        )


chat_service = ChatService()
