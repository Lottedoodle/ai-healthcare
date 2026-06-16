"use client";

import { ArrowUp, Loader2 } from "lucide-react";
import { FormEvent, KeyboardEvent, useRef } from "react";

type ChatInputProps = {
  disabled?: boolean;
  sending?: boolean;
  onSend: (content: string) => void;
};

export function ChatInput({ disabled, sending, onSend }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function submit() {
    const el = textareaRef.current;
    if (!el || disabled || sending) return;
    const value = el.value.trim();
    if (!value) return;
    onSend(value);
    el.value = "";
    el.style.height = "auto";
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function handleInput() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  return (
    <div className="border-t border-white/10 bg-[#0d0d0d] px-4 py-4">
      <form onSubmit={handleSubmit} className="mx-auto max-w-3xl">
        <div className="relative flex items-end rounded-2xl border border-white/10 bg-[#2f2f2f] shadow-lg">
          <textarea
            ref={textareaRef}
            rows={1}
            disabled={disabled || sending}
            placeholder="พิมพ์คำถามทางการแพทย์..."
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            className="max-h-[200px] min-h-[52px] flex-1 resize-none bg-transparent px-4 py-3.5 text-[15px] text-white outline-none placeholder:text-zinc-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={disabled || sending}
            className="m-2 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-600 text-white transition hover:bg-emerald-500 disabled:opacity-40"
            aria-label="Send message"
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </button>
        </div>
        <p className="mt-2 text-center text-xs text-zinc-600">
          AI ให้ข้อมูลช่วยเหลือเท่านั้น — ไม่แทนการวินิจฉัยโดยแพทย์
        </p>
      </form>
    </div>
  );
}
