"use client";

import { useState } from "react";
import { SessionSummary } from "../hooks/useChatSessions";

interface Props {
  sessions: SessionSummary[];
  activeId: string | null;
  loading: boolean;
  onSelect: (session: SessionSummary) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}

const ATTACK_COLORS: Record<string, string> = {
  xss:             "text-yellow-400",
  sql_injection:   "text-red-400",
  csrf:            "text-orange-400",
  rce:             "text-red-500",
  ssrf:            "text-purple-400",
  authentication:  "text-blue-400",
  brute_force:     "text-pink-400",
  default:         "text-gray-400",
};

function attackColor(attack: string | null) {
  if (!attack) return ATTACK_COLORS.default;
  return ATTACK_COLORS[attack] ?? ATTACK_COLORS.default;
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function ChatSidebar({
  sessions,
  activeId,
  loading,
  onSelect,
  onNew,
  onDelete,
  onRename,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const startEdit = (s: SessionSummary) => {
    setEditingId(s.id);
    setEditValue(s.title);
  };

  const commitEdit = (id: string) => {
    if (editValue.trim()) onRename(id, editValue.trim());
    setEditingId(null);
  };

  return (
    <aside className="flex flex-col w-64 h-full bg-gray-900 border-r border-gray-800 text-gray-200">
      {/* Header */}
      <div className="px-4 py-4 border-b border-gray-800">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold text-gray-300">Chat History</span>
          {loading && <span className="text-xs text-gray-500 animate-pulse">loading…</span>}
        </div>
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-green-700 hover:bg-green-600 text-sm font-medium transition-colors"
        >
          <span className="text-lg leading-none">+</span>
          New conversation
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto py-2">
        {sessions.length === 0 && !loading && (
          <p className="text-center text-gray-600 text-xs mt-8 px-4">
            No saved conversations yet.
          </p>
        )}

        {sessions.map((s) => (
          <div
            key={s.id}
            className={`group relative mx-2 mb-1 rounded-lg cursor-pointer transition-colors ${
              s.id === activeId
                ? "bg-gray-700"
                : "hover:bg-gray-800"
            }`}
          >
            {editingId === s.id ? (
              <div className="px-3 py-2">
                <input
                  autoFocus
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onBlur={() => commitEdit(s.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitEdit(s.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                  className="w-full bg-gray-600 text-gray-100 text-xs rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-green-500"
                />
              </div>
            ) : (
              <button
                onClick={() => onSelect(s)}
                className="w-full text-left px-3 py-2.5"
              >
                {/* Title row */}
                <div className="flex items-start justify-between gap-1 mb-1">
                  <span className="text-xs font-medium text-gray-200 line-clamp-1 flex-1">
                    {s.title}
                  </span>
                  <span className="text-xs text-gray-500 shrink-0">{timeAgo(s.updated_at)}</span>
                </div>

                {/* Attack badge + message count */}
                <div className="flex items-center gap-2">
                  {s.suspected_attack && (
                    <span className={`text-xs font-mono ${attackColor(s.suspected_attack)}`}>
                      {s.suspected_attack}
                    </span>
                  )}
                  <span className="text-xs text-gray-600">
                    {s.message_count} msg{s.message_count !== 1 ? "s" : ""}
                  </span>
                </div>

                {/* Last message preview */}
                {s.last_message && (
                  <p className="text-xs text-gray-500 line-clamp-1 mt-0.5">
                    {s.last_role === "assistant" ? "AI: " : "You: "}
                    {s.last_message}
                  </p>
                )}
              </button>
            )}

            {/* Hover actions */}
            {editingId !== s.id && (
              <div className="absolute right-2 top-2 hidden group-hover:flex items-center gap-1">
                <button
                  onClick={(e) => { e.stopPropagation(); startEdit(s); }}
                  className="p-1 rounded hover:bg-gray-600 text-gray-400 hover:text-gray-200 text-xs"
                  title="Rename"
                >
                  ✏
                </button>
                {confirmDelete === s.id ? (
                  <>
                    <button
                      onClick={(e) => { e.stopPropagation(); onDelete(s.id); setConfirmDelete(null); }}
                      className="p-1 rounded bg-red-700 hover:bg-red-600 text-white text-xs"
                    >
                      ✓
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setConfirmDelete(null); }}
                      className="p-1 rounded hover:bg-gray-600 text-gray-400 text-xs"
                    >
                      ✕
                    </button>
                  </>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); setConfirmDelete(s.id); }}
                    className="p-1 rounded hover:bg-gray-600 text-gray-400 hover:text-red-400 text-xs"
                    title="Delete"
                  >
                    🗑
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
