from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.agent.graph import AgentState, fresh_state

AGENT_STATE_KEYS = (
    "user_input",
    "intent",
    "provided_fields",
    "clarifying_question",
    "next_step",
    "route_mode",
    "route_reason",
    "patient_hn",
    "weight_kg",
    "renal_cr",
    "current_step",
    "audit_log",
    "execution_result",
    "plan",
    "plan_summary",
)


def serialize_agent_state(state: AgentState) -> dict[str, Any]:
    return {k: state[k] for k in AGENT_STATE_KEYS if k in state}


def deserialize_agent_state(data: dict[str, Any] | None) -> AgentState:
    base: AgentState = fresh_state()
    if not data:
        return base
    for key in AGENT_STATE_KEYS:
        if key in data:
            base[key] = data[key]  # type: ignore[literal-required]
    return base


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)
