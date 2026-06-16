"use client";

import {
  LogOut,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Stethoscope,
  Trash2,
} from "lucide-react";

import type { ChatSession } from "@/lib/types";

type ChatSidebarProps = {
  sessions: ChatSession[];
  activeId: string | null;
  collapsed: boolean;
  userEmail: string | null;
  onToggle: () => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onSignOut: () => void;
};

export function ChatSidebar({
  sessions,
  activeId,
  collapsed,
  userEmail,
  onToggle,
  onNewChat,
  onSelect,
  onDelete,
  onSignOut,
}: ChatSidebarProps) {
  return (
    <aside
      className={`flex h-full shrink-0 flex-col border-r border-white/10 bg-[#171717] transition-all duration-200 ${
        collapsed ? "w-[52px]" : "w-64"
      }`}
    >
      <div className="flex items-center gap-2 border-b border-white/10 p-3">
        <button
          type="button"
          onClick={onToggle}
          className="rounded-lg p-2 text-zinc-400 hover:bg-white/5 hover:text-white"
          aria-label="Toggle sidebar"
        >
          {collapsed ? (
            <PanelLeftOpen className="h-5 w-5" />
          ) : (
            <PanelLeftClose className="h-5 w-5" />
          )}
        </button>
        {!collapsed && (
          <div className="flex items-center gap-2 overflow-hidden">
            <Stethoscope className="h-4 w-4 shrink-0 text-emerald-400" />
            <span className="truncate text-sm font-medium text-white">Medical AI</span>
          </div>
        )}
      </div>

      <div className="p-2">
        <button
          type="button"
          onClick={onNewChat}
          className={`flex w-full items-center gap-2 rounded-lg border border-white/10 bg-transparent px-3 py-2.5 text-sm text-white transition hover:bg-white/5 ${
            collapsed ? "justify-center px-2" : ""
          }`}
        >
          <MessageSquarePlus className="h-4 w-4 shrink-0" />
          {!collapsed && <span>แชทใหม่</span>}
        </button>
      </div>

      {!collapsed && (
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          <p className="px-2 py-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
            ประวัติแชท
          </p>
          {sessions.length === 0 ? (
            <p className="px-2 py-4 text-center text-xs text-zinc-500">ยังไม่มีแชท</p>
          ) : (
            <ul className="space-y-0.5">
              {sessions.map((session) => (
                <li key={session.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(session.id)}
                    className={`w-full rounded-lg px-3 py-2.5 pr-9 text-left text-sm transition ${
                      activeId === session.id
                        ? "bg-white/10 text-white"
                        : "text-zinc-300 hover:bg-white/5"
                    }`}
                  >
                    <span className="line-clamp-2">{session.title}</span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(session.id);
                    }}
                    className="absolute right-1 top-1/2 hidden -translate-y-1/2 rounded p-1.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-400 group-hover:block"
                    aria-label="Delete chat"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-auto border-t border-white/10 p-2">
        {!collapsed && userEmail && (
          <p className="truncate px-2 py-1 text-xs text-zinc-500">{userEmail}</p>
        )}
        <button
          type="button"
          onClick={onSignOut}
          className={`flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-sm text-zinc-400 transition hover:bg-white/5 hover:text-white ${
            collapsed ? "justify-center px-2" : ""
          }`}
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span>ออกจากระบบ</span>}
        </button>
      </div>
    </aside>
  );
}
