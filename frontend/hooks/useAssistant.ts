"use client";

import { useState, useRef, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

export interface UseAssistantOptions {
  suspectedAttack?: string;
  userRole?: string;
  userId?: string;
  onSessionCreated?: (sessionId: string, title: string) => void;
}

export function useAssistant(options: UseAssistantOptions = {}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionTitle, setSessionTitle] = useState<string>("");
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  /** Load a saved session from Supabase (restores messages + metadata). */
  const loadSession = useCallback(async (sessionId: string) => {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/assist/sessions/${sessionId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      sessionIdRef.current = sessionId;
      setSessionTitle(data.title ?? "");
      setMessages(
        (data.messages ?? []).map((m: Message) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          created_at: m.created_at,
        }))
      );
      // Warm the in-memory history on the backend by loading the session
      return data;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load session");
    }
  }, []);

  const send = useCallback(
    async (userMessage: string, taskContext?: string) => {
      if (isStreaming) return;
      setError(null);
      setIsStreaming(true);

      setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      const params = new URLSearchParams({
        message: userMessage,
        ...(sessionIdRef.current   && { session_id:       sessionIdRef.current }),
        ...(taskContext            && { task_context:     taskContext }),
        ...(options.suspectedAttack && { suspected_attack: options.suspectedAttack }),
        ...(options.userRole       && { user_role:        options.userRole }),
        ...(options.userId         && { user_id:          options.userId }),
      });

      abortRef.current = new AbortController();

      try {
        const res = await fetch(`${API_BASE}/assist/stream?${params}`, {
          signal: abortRef.current.signal,
          headers: { Accept: "text/event-stream" },
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        if (!res.body) throw new Error("No response body");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let expectMeta = false;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (let i = 0; i < lines.length; i++) {
            const line = lines[i];

            if (line.startsWith("event: meta")) {
              expectMeta = true;
              continue;
            }
            if (line.startsWith("event: error")) {
              expectMeta = false;
              continue;
            }

            if (line.startsWith("data: ")) {
              const payload = line.slice(6);

              if (payload === "[DONE]") {
                setIsStreaming(false);
                break;
              }

              // Try JSON (meta or error payloads)
              if (expectMeta || payload.startsWith("{")) {
                try {
                  const parsed = JSON.parse(payload);
                  if (parsed.session_id) {
                    sessionIdRef.current = parsed.session_id;
                    if (parsed.title) setSessionTitle(parsed.title);
                    options.onSessionCreated?.(parsed.session_id, parsed.title ?? "");
                  }
                  if (parsed.error) setError(parsed.error);
                  expectMeta = false;
                  continue;
                } catch {
                  // fall through to text handling
                }
              }

              expectMeta = false;
              const text = payload.replace(/\\n/g, "\n");
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: "assistant",
                  content: updated[updated.length - 1].content + text,
                };
                return updated;
              });
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== "AbortError") {
          setError(err.message);
          setMessages((prev) => prev.slice(0, -1));
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [isStreaming, options]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
  }, []);

  const reset = useCallback(() => {
    sessionIdRef.current = null;
    setMessages([]);
    setSessionTitle("");
    setError(null);
  }, []);

  return {
    messages,
    isStreaming,
    error,
    sessionId: sessionIdRef.current,
    sessionTitle,
    send,
    stop,
    reset,
    loadSession,
  };
}
