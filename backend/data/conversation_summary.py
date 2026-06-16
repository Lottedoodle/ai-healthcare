from __future__ import annotations

import os
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

RECENT_MESSAGE_COUNT = int(os.getenv("CHAT_SUMMARY_RECENT_MESSAGES", "6"))
MIN_MESSAGES_TO_SUMMARIZE = int(os.getenv("CHAT_SUMMARY_MIN_BATCH", "4"))
SUMMARY_ENABLED = os.getenv("CHAT_SUMMARY_ENABLED", "true").lower() in ("1", "true", "yes")

SUMMARY_SYSTEM_PROMPT = """\
You compress medical chat history for a physician-facing AI assistant.

Merge the existing summary (if any) with the new messages into one concise summary in Thai.

Keep: patient HN, weight, renal function, drug names, intents, clinical conclusions, pending questions.
Drop: greetings, filler, repeated content.

Output only the summary text — no headings or preamble.\
"""


def _create_summary_llm() -> ChatOpenAI:
    openrouter_key = (os.getenv("OPEN_ROUTER_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")
    model = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")

    if openrouter_key:
        return ChatOpenAI(
            model=model if "/" in model else f"openai/{model}",
            openai_api_key=openrouter_key,
            openai_api_base=os.getenv("OPEN_ROUTER_BASE", "https://openrouter.ai/api/v1"),
            temperature=0.2,
        )

    if not openai_key:
        raise RuntimeError("Missing OPENAI_API_KEY or OPEN_ROUTER_KEY in .env")

    return ChatOpenAI(model=model, openai_api_key=openai_key, temperature=0.2)


@dataclass
class ConversationContext:
    conversation_summary: str
    recent_conversation: str
    summary_message_count: int


def format_messages_for_context(messages: list[tuple[str, str]]) -> str:
    """Format (role, content) pairs for LLM context."""
    lines: list[str] = []
    for role, content in messages:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def build_recent_context(
    messages: list[tuple[str, str]],
    *,
    recent_count: int = RECENT_MESSAGE_COUNT,
) -> str:
    """Recent turns excluding the current user message (last item)."""
    if len(messages) <= 1:
        return ""
    prior = messages[:-1]
    window = prior[-recent_count:]
    return format_messages_for_context(window)


def maybe_summarize(
    messages: list[tuple[str, str]],
    *,
    existing_summary: str,
    summary_message_count: int,
    recent_count: int = RECENT_MESSAGE_COUNT,
    min_batch: int = MIN_MESSAGES_TO_SUMMARIZE,
) -> tuple[str, int]:
    """
    Fold older messages into a rolling summary.

    Returns (conversation_summary, summary_message_count).
    """
    if not SUMMARY_ENABLED or not messages:
        return existing_summary, summary_message_count

    total = len(messages)
    recent_window_start = max(0, total - recent_count - 1)
    to_summarize = messages[summary_message_count:recent_window_start]

    if len(to_summarize) < min_batch:
        return existing_summary, summary_message_count

    transcript = format_messages_for_context(to_summarize)
    parts = []
    if existing_summary.strip():
        parts.append(f"Existing summary:\n{existing_summary.strip()}")
    parts.append(f"New messages to fold in:\n{transcript}")

    llm = _create_summary_llm()
    response = llm.invoke([
        SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
        HumanMessage(content="\n\n".join(parts)),
    ])
    new_summary = response.content if isinstance(response.content, str) else str(response.content)
    new_count = summary_message_count + len(to_summarize)
    return new_summary.strip(), new_count


def prepare_conversation_context(
    messages: list[tuple[str, str]],
    *,
    existing_summary: str = "",
    summary_message_count: int = 0,
) -> ConversationContext:
    """Summarize if needed, then build context fields for the agent."""
    summary, count = maybe_summarize(
        messages,
        existing_summary=existing_summary,
        summary_message_count=summary_message_count,
    )
    recent = build_recent_context(messages)
    return ConversationContext(
        conversation_summary=summary,
        recent_conversation=recent,
        summary_message_count=count,
    )
