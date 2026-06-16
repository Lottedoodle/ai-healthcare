"use client";

import { Bot, Loader2, User } from "lucide-react";
import ReactMarkdown from "react-markdown";

import type { ChatMessage } from "@/lib/types";

type ChatMessagesProps = {
  messages: ChatMessage[];
  loading: boolean;
  streamStatus?: string | null;
  streamingMessageId?: string | null;
  onExampleClick?: (text: string) => void;
  examplesDisabled?: boolean;
};

const EXAMPLE_PROMPTS = [
  "ขอสูตรคำนวณ BMI",
  "ขอ lab ล่าสุด HN 123456",
  "คำนวณ dose vancomycin HN 123456 น้ำหนัก 70 kg Cr 1.2",
  "สรุป case HN 123456 สำหรับ morning round",
] as const;

function MetadataBadges({ metadata }: { metadata: ChatMessage["metadata"] }) {
  const badges: string[] = [];
  if (metadata.route_mode_label) badges.push(metadata.route_mode_label);
  else if (metadata.route_mode) badges.push(metadata.route_mode);
  if (metadata.intent) badges.push(metadata.intent);

  if (badges.length === 0 && !metadata.plan_summary && metadata.audit_log.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 space-y-2 border-t border-white/5 pt-3">
      {badges.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {badges.map((badge) => (
            <span
              key={badge}
              className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400"
            >
              {badge}
            </span>
          ))}
        </div>
      )}
      {metadata.route_reason && (
        <p className="text-xs text-zinc-500">{metadata.route_reason}</p>
      )}
      {metadata.plan_summary && (
        <p className="text-xs text-zinc-400">
          <span className="font-medium text-zinc-300">Plan: </span>
          {metadata.plan_summary}
        </p>
      )}
      {metadata.audit_log.length > 0 && (
        <details className="text-xs text-zinc-500">
          <summary className="cursor-pointer hover:text-zinc-300">Audit log</summary>
          <ul className="mt-1 list-inside list-disc space-y-0.5 pl-1">
            {metadata.audit_log.map((line, i) => (
              <li key={`${line}-${i}`}>{line}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function ChatMessages({
  messages,
  loading,
  streamStatus,
  streamingMessageId,
  onExampleClick,
  examplesDisabled,
}: ChatMessagesProps) {
  if (messages.length === 0 && !loading) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-4 text-center">
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-emerald-600/10 text-emerald-400">
          <Bot className="h-8 w-8" />
        </div>
        <h2 className="mb-2 text-xl font-medium text-white">Medical AI Assistant</h2>
        <p className="max-w-md text-sm text-zinc-400">
          ถามเรื่อง clinical support, lab, dose calculation หรือสรุป case ได้เลย
        </p>
        <div className="mt-8 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
          {EXAMPLE_PROMPTS.map((example) => (
            <button
              key={example}
              type="button"
              disabled={!onExampleClick || examplesDisabled}
              onClick={() => onExampleClick?.(example)}
              className="rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 text-left text-sm text-zinc-400 transition hover:border-emerald-500/40 hover:bg-emerald-500/5 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {example}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          const isStreaming = !isUser && msg.id === streamingMessageId;
          return (
            <div
              key={msg.id}
              className={`flex gap-4 ${isUser ? "flex-row-reverse" : ""}`}
            >
              <div
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                  isUser ? "bg-zinc-700 text-white" : "bg-emerald-600/20 text-emerald-400"
                }`}
              >
                {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
              </div>
              <div
                className={`min-w-0 flex-1 ${isUser ? "text-right" : "text-left"}`}
              >
                <div
                  className={`inline-block max-w-full rounded-2xl px-4 py-3 text-left text-[15px] leading-relaxed ${
                    isUser
                      ? "bg-emerald-600 text-white"
                      : "bg-[#2f2f2f] text-zinc-100"
                  }`}
                >
                  {isUser ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <div className="prose prose-invert prose-sm max-w-none prose-p:my-2 prose-pre:my-2 prose-ul:my-2">
                      <ReactMarkdown>{msg.content || (isStreaming ? " " : "")}</ReactMarkdown>
                      {isStreaming && (
                        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-emerald-400 align-middle" />
                      )}
                    </div>
                  )}
                  {!isUser && !isStreaming && <MetadataBadges metadata={msg.metadata} />}
                </div>
              </div>
            </div>
          );
        })}

        {loading && !streamingMessageId && (
          <div className="flex gap-4">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-600/20 text-emerald-400">
              <Bot className="h-4 w-4" />
            </div>
            <div className="flex items-center gap-2 rounded-2xl bg-[#2f2f2f] px-4 py-3 text-zinc-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="text-sm">{streamStatus ?? "กำลังประมวลผล..."}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
