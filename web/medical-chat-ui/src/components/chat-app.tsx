"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ChatInput } from "@/components/chat-input";
import { ChatMessages } from "@/components/chat-messages";
import { ChatSidebar } from "@/components/chat-sidebar";
import { useAuth } from "@/contexts/auth-context";
import { api, ApiError } from "@/lib/api";
import { emptyMetadata, sendMessageStream } from "@/lib/stream-api";
import type { ChatMessage, ChatSession } from "@/lib/types";

function tempId() {
  return `temp-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function ChatApp() {
  const router = useRouter();
  const { session, loading: authLoading, signOut, accessToken } = useAuth();

  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [sending, setSending] = useState(false);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !session) {
      router.replace("/login");
    }
  }, [authLoading, session, router]);

  const loadSessions = useCallback(async () => {
    if (!accessToken) return;
    try {
      const list = await api.listSessions(accessToken);
      setSessions(list);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "โหลด sessions ไม่สำเร็จ");
    }
  }, [accessToken]);

  useEffect(() => {
    if (accessToken) {
      void loadSessions();
    }
  }, [accessToken, loadSessions]);

  const loadSession = useCallback(
    async (sessionId: string) => {
      if (!accessToken) return;
      setLoadingSession(true);
      setError(null);
      try {
        const detail = await api.getSession(accessToken, sessionId);
        setMessages(detail.messages);
        setActiveId(sessionId);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "โหลดแชทไม่สำเร็จ");
      } finally {
        setLoadingSession(false);
      }
    },
    [accessToken],
  );

  const handleNewChat = useCallback(async () => {
    if (!accessToken) return;
    setError(null);
    try {
      const created = await api.createSession(accessToken);
      setSessions((prev) => [created, ...prev]);
      setActiveId(created.id);
      setMessages([]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "สร้างแชทไม่สำเร็จ");
    }
  }, [accessToken]);

  const handleDelete = useCallback(
    async (sessionId: string) => {
      if (!accessToken) return;
      try {
        await api.deleteSession(accessToken, sessionId);
        setSessions((prev) => prev.filter((s) => s.id !== sessionId));
        if (activeId === sessionId) {
          setActiveId(null);
          setMessages([]);
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "ลบแชทไม่สำเร็จ");
      }
    },
    [accessToken, activeId],
  );

  const handleSend = useCallback(
    async (content: string) => {
      if (!accessToken) return;

      let sessionId = activeId;
      if (!sessionId) {
        try {
          const created = await api.createSession(accessToken);
          setSessions((prev) => [created, ...prev]);
          sessionId = created.id;
          setActiveId(created.id);
        } catch (err) {
          setError(err instanceof ApiError ? err.message : "สร้างแชทไม่สำเร็จ");
          return;
        }
      }

      const userMessage: ChatMessage = {
        id: tempId(),
        role: "user",
        content,
        created_at: new Date().toISOString(),
        metadata: {
          intent: "",
          route_mode: "",
          route_mode_label: "",
          route_reason: "",
          plan_summary: "",
          audit_log: [],
          awaiting_user: false,
          done: false,
        },
      };

      setMessages((prev) => [...prev, userMessage]);
      setSending(true);
      setStreamStatus("กำลังเริ่มต้น...");
      setStreamingMessageId(null);
      setError(null);

      const assistantId = tempId();
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        created_at: new Date().toISOString(),
        metadata: { ...emptyMetadata },
      };

      try {
        const result = await sendMessageStream(accessToken, sessionId, content, (event) => {
          if (event.type === "status") {
            setStreamStatus(event.text);
            return;
          }
          if (event.type === "start") {
            setStreamingMessageId(assistantId);
            setMessages((prev) => {
              if (prev.some((m) => m.id === assistantId)) return prev;
              return [...prev, assistantPlaceholder];
            });
            return;
          }
          if (event.type === "token") {
            setStreamingMessageId(assistantId);
            setMessages((prev) => {
              const exists = prev.some((m) => m.id === assistantId);
              const base = exists ? prev : [...prev, assistantPlaceholder];
              return base.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + event.content } : m,
              );
            });
          }
        });

        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? result.message : m)),
        );
        setSessions((prev) => {
          const filtered = prev.filter((s) => s.id !== result.session.id);
          return [result.session, ...filtered];
        });
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "ส่งข้อความไม่สำเร็จ");
        setMessages((prev) =>
          prev.filter((m) => m.id !== userMessage.id && m.id !== assistantId),
        );
      } finally {
        setSending(false);
        setStreamStatus(null);
        setStreamingMessageId(null);
      }
    },
    [accessToken, activeId],
  );

  if (authLoading || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0d0d0d] text-zinc-400">
        กำลังโหลด...
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[#0d0d0d] text-white">
      <ChatSidebar
        sessions={sessions}
        activeId={activeId}
        collapsed={sidebarCollapsed}
        userEmail={session.user.email ?? null}
        onToggle={() => setSidebarCollapsed((v) => !v)}
        onNewChat={() => void handleNewChat()}
        onSelect={(id) => void loadSession(id)}
        onDelete={(id) => void handleDelete(id)}
        onSignOut={async () => {
          await signOut();
          router.replace("/login");
        }}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {error && (
          <div className="border-b border-red-500/20 bg-red-500/10 px-4 py-2 text-center text-sm text-red-400">
            {error}
          </div>
        )}

        {loadingSession ? (
          <div className="flex flex-1 items-center justify-center text-zinc-500">
            กำลังโหลดแชท...
          </div>
        ) : (
          <ChatMessages
            messages={messages}
            loading={sending}
            streamStatus={streamStatus}
            streamingMessageId={streamingMessageId}
            examplesDisabled={sending || loadingSession}
            onExampleClick={(text) => void handleSend(text)}
          />
        )}

        <ChatInput disabled={loadingSession} sending={sending} onSend={(c) => void handleSend(c)} />
      </main>
    </div>
  );
}
