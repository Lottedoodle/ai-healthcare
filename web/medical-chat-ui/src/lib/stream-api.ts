import type { ChatMessage, ChatSession, MessageMetadata, SendMessageResponse } from "./types";
import { ApiError } from "./api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type StreamEvent =
  | { type: "status"; text: string }
  | { type: "start"; content: string }
  | { type: "token"; content: string }
  | { type: "done"; message: ChatMessage; session: ChatSession }
  | { type: "error"; detail: string };

function parseSseBlock(block: string): StreamEvent | null {
  let eventType = "message";
  let dataLine = "";

  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLine += line.slice(5).trim();
    }
  }

  if (!dataLine) return null;

  try {
    const data = JSON.parse(dataLine) as Record<string, unknown>;
    switch (eventType) {
      case "status":
        return { type: "status", text: String(data.text ?? "") };
      case "start":
        return { type: "start", content: String(data.content ?? "") };
      case "token":
        return { type: "token", content: String(data.content ?? "") };
      case "done":
        return {
          type: "done",
          message: data.message as ChatMessage,
          session: data.session as ChatSession,
        };
      case "error":
        return { type: "error", detail: String(data.detail ?? "Unknown error") };
      default:
        return null;
    }
  } catch {
    return null;
  }
}

const emptyMetadata: MessageMetadata = {
  intent: "",
  route_mode: "",
  route_mode_label: "",
  route_reason: "",
  plan_summary: "",
  audit_log: [],
  awaiting_user: false,
  done: false,
};

export async function sendMessageStream(
  token: string,
  sessionId: string,
  content: string,
  onEvent: (event: StreamEvent) => void,
): Promise<SendMessageResponse> {
  const response = await fetch(`${API_URL}/api/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ content }),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, String(detail));
  }

  if (!response.body) {
    throw new ApiError(500, "Streaming not supported");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: SendMessageResponse | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const event = parseSseBlock(part.trim());
      if (!event) continue;
      onEvent(event);
      if (event.type === "error") {
        throw new ApiError(503, event.detail);
      }
      if (event.type === "done") {
        result = { message: event.message, session: event.session };
      }
    }
  }

  if (!result) {
    throw new ApiError(500, "Stream ended without response");
  }

  return result;
}

export { emptyMetadata };
