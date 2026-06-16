from __future__ import annotations

from typing import Any

import httpx

from backend.context import supabase_user_token
from backend.data.db import supabase_rest_config


class ChatStoreError(Exception):
    pass


def _headers(*, json: bool = False, prefer: str | None = None) -> dict[str, str]:
    cfg = supabase_rest_config()
    if not cfg:
        raise ChatStoreError("Supabase is not configured")

    base_key = cfg[1]
    user_jwt = supabase_user_token.get()
    if not user_jwt:
        raise ChatStoreError("Missing user auth token for database access")

    headers = {
        "apikey": base_key,
        "Authorization": f"Bearer {user_jwt}",
    }
    if json:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    elif json:
        headers["Prefer"] = "return=representation"
    return headers


def _base_url() -> str:
    cfg = supabase_rest_config()
    if not cfg:
        raise ChatStoreError("Supabase is not configured")
    return cfg[0]


def _request(
    method: str,
    path: str,
    *,
    prefer: str | None = None,
    **kwargs: Any,
) -> httpx.Response:
    url = f"{_base_url()}/rest/v1/{path}"
    with httpx.Client(timeout=30.0) as client:
        response = client.request(
            method,
            url,
            headers=_headers(json=method in ("POST", "PATCH"), prefer=prefer),
            **kwargs,
        )
    if response.status_code >= 400:
        raise ChatStoreError(f"{method} {path} failed ({response.status_code}): {response.text[:300]}")
    return response


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    response = _request(
        "GET",
        "chat_sessions",
        params={
            "user_id": f"eq.{user_id}",
            "order": "updated_at.desc",
            "select": "id,user_id,title,agent_state,conversation_summary,summary_message_count,created_at,updated_at,chat_messages(count)",
        },
    )
    rows = response.json()
    out: list[dict[str, Any]] = []
    for row in rows:
        count_block = row.pop("chat_messages", None)
        count = 0
        if isinstance(count_block, list) and count_block:
            count = int(count_block[0].get("count", 0))
        row["message_count"] = count
        out.append(row)
    return out


def get_session_row(session_id: str, user_id: str) -> dict[str, Any] | None:
    response = _request(
        "GET",
        "chat_sessions",
        params={
            "id": f"eq.{session_id}",
            "user_id": f"eq.{user_id}",
            "select": "id,user_id,title,agent_state,conversation_summary,summary_message_count,created_at,updated_at",
        },
    )
    rows = response.json()
    return rows[0] if rows else None


def list_messages(session_id: str) -> list[dict[str, Any]]:
    response = _request(
        "GET",
        "chat_messages",
        params={
            "session_id": f"eq.{session_id}",
            "order": "created_at.asc",
            "select": "id,session_id,role,content,metadata,created_at",
        },
    )
    return response.json()


def create_session_row(user_id: str, title: str = "New chat") -> dict[str, Any]:
    response = _request(
        "POST",
        "chat_sessions",
        json={"user_id": user_id, "title": title, "agent_state": {}},
    )
    rows = response.json()
    if not rows:
        raise ChatStoreError("Failed to create session")
    row = rows[0]
    row["message_count"] = 0
    return row


def update_session_row(
    session_id: str,
    *,
    title: str | None = None,
    agent_state: dict | None = None,
    conversation_summary: str | None = None,
    summary_message_count: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if agent_state is not None:
        payload["agent_state"] = agent_state
    if conversation_summary is not None:
        payload["conversation_summary"] = conversation_summary
    if summary_message_count is not None:
        payload["summary_message_count"] = summary_message_count

    if not payload:
        raise ChatStoreError("Nothing to update")

    response = _request(
        "PATCH",
        "chat_sessions",
        params={"id": f"eq.{session_id}"},
        json=payload,
    )
    rows = response.json()
    if not rows:
        raise ChatStoreError("Session not found or update forbidden")
    return rows[0]


def insert_message_row(
    session_id: str,
    *,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> dict[str, Any]:
    response = _request(
        "POST",
        "chat_messages",
        json={
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
        },
    )
    rows = response.json()
    if not rows:
        raise ChatStoreError("Failed to insert message")
    return rows[0]


def delete_session_row(session_id: str, user_id: str) -> bool:
    response = _request(
        "DELETE",
        "chat_sessions",
        prefer="return=representation",
        params={"id": f"eq.{session_id}", "user_id": f"eq.{user_id}"},
    )
    return bool(response.json())
