"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface SessionSummary {
  id: string;
  title: string;
  suspected_attack: string | null;
  user_role: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
  last_message: string | null;
  last_role: string | null;
}

export function useChatSessions(userId?: string) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
      const res = await fetch(`${API_BASE}/assist/sessions${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: SessionSummary[] = await res.json();
      setSessions(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch sessions");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const deleteSession = useCallback(
    async (sessionId: string) => {
      await fetch(`${API_BASE}/assist/sessions/${sessionId}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    },
    []
  );

  const renameSession = useCallback(async (sessionId: string, title: string) => {
    await fetch(`${API_BASE}/assist/sessions/${sessionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    setSessions((prev) =>
      prev.map((s) => (s.id === sessionId ? { ...s, title } : s))
    );
  }, []);

  /** Call after a new message is sent so the sidebar reflects the latest state. */
  const refreshSession = useCallback(
    async (sessionId: string) => {
      try {
        const res = await fetch(`${API_BASE}/assist/sessions/${sessionId}`);
        if (!res.ok) return;
        const updated = await res.json();
        setSessions((prev) => {
          const exists = prev.find((s) => s.id === sessionId);
          const next: SessionSummary = {
            id: updated.id,
            title: updated.title,
            suspected_attack: updated.suspected_attack,
            user_role: updated.user_role,
            message_count: updated.message_count,
            created_at: updated.created_at,
            updated_at: updated.updated_at,
            last_message: null,
            last_role: null,
          };
          if (exists) {
            return prev.map((s) => (s.id === sessionId ? next : s));
          }
          return [next, ...prev];
        });
      } catch {
        // non-blocking
      }
    },
    []
  );

  return { sessions, loading, error, fetchSessions, deleteSession, renameSession, refreshSession };
}
