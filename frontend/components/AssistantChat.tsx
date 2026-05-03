"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { useAssistant, Message } from "../hooks/useAssistant";

interface Props {
  /** Load an existing session by ID (restores messages from Supabase) */
  sessionId?: string | null;
  /** Pre-fill the task context for the first message */
  initialContext?: string;
  suspectedAttack?: string;
  userRole?: string;
  userId?: string;
  title?: string;
  /** Called when a new session is auto-created (gives parent the new ID) */
  onSessionCreated?: (sessionId: string, title: string) => void;
  /** Called after every completed AI turn (so sidebar can refresh) */
  onTurnComplete?: (sessionId: string) => void;
}

export default function AssistantChat({
  sessionId: externalSessionId,
  initialContext,
  suspectedAttack,
  userRole,
  userId,
  title: panelTitle = "CyberGuard AI",
  onSessionCreated,
  onTurnComplete,
}: Props) {
  const {
    messages,
    isStreaming,
    error,
    sessionId,
    sessionTitle,
    send,
    stop,
    reset,
    loadSession,
  } = useAssistant({
    suspectedAttack,
    userRole,
    userId,
    onSessionCreated,
  });

  const [input, setInput] = useState("");
  const [contextSent, setContextSent] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const prevStreamingRef = useRef(isStreaming);

  // Load session from Supabase when externalSessionId changes
  useEffect(() => {
    if (externalSessionId) {
      reset();
      loadSession(externalSessionId);
    } else {
      reset();
    }
    setContextSent(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalSessionId]);

  // Notify parent when a stream completes
  useEffect(() => {
    if (prevStreamingRef.current && !isStreaming && sessionId) {
      onTurnComplete?.(sessionId);
    }
    prevStreamingRef.current = isStreaming;
  }, [isStreaming, sessionId, onTurnComplete]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    const ctx = !contextSent && initialContext ? initialContext : undefined;
    if (ctx) setContextSent(true);
    send(text, ctx);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const displayTitle = sessionTitle || panelTitle;

  return (
    <div className="flex flex-col h-full bg-gray-950 text-gray-100">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-900 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-green-400 text-base shrink-0">⬡</span>
          <span className="font-semibold text-sm truncate">{displayTitle}</span>
          {suspectedAttack && (
            <span className="text-xs text-yellow-400 bg-yellow-400/10 px-2 py-0.5 rounded-full shrink-0 font-mono">
              {suspectedAttack}
            </span>
          )}
          {userRole && (
            <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full shrink-0">
              {userRole}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {sessionId && (
            <span className="text-xs text-gray-600 font-mono hidden sm:block">
              #{sessionId.slice(0, 8)}
            </span>
          )}
          <button
            onClick={reset}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-2 py-1 rounded hover:bg-gray-800"
          >
            New chat
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-600 py-16">
            <div className="text-4xl mb-3 text-green-800">⬡</div>
            <p className="text-sm text-gray-500 mb-1">
              Ask me anything about this security incident.
            </p>
            {suspectedAttack && (
              <p className="text-xs text-green-700 mt-2">
                RAG context: <span className="font-mono">{suspectedAttack}</span>
              </p>
            )}
            {initialContext && (
              <p className="text-xs text-gray-600 mt-1">
                Task context loaded — will be sent with your first message.
              </p>
            )}
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            isLast={i === messages.length - 1}
            isStreaming={isStreaming}
          />
        ))}

        {error && (
          <div className="flex items-start gap-2 text-red-400 text-xs bg-red-950/60 border border-red-800 rounded-lg px-3 py-2">
            <span>⚠</span>
            <span>{error}</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="px-4 py-3 bg-gray-900 border-t border-gray-800 shrink-0">
        {isStreaming && (
          <div className="flex items-center gap-1.5 text-xs text-green-400 mb-2">
            <span className="inline-flex gap-0.5">
              <span className="w-1 h-1 rounded-full bg-green-400 animate-bounce [animation-delay:0ms]" />
              <span className="w-1 h-1 rounded-full bg-green-400 animate-bounce [animation-delay:150ms]" />
              <span className="w-1 h-1 rounded-full bg-green-400 animate-bounce [animation-delay:300ms]" />
            </span>
            CyberGuard AI is typing…
          </div>
        )}
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isStreaming}
            placeholder="Ask about this incident… (Enter sends, Shift+Enter for newline)"
            rows={2}
            className="flex-1 resize-none bg-gray-800 text-gray-100 placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-green-600 disabled:opacity-50"
          />
          {isStreaming ? (
            <button
              onClick={stop}
              className="px-3 py-2 text-sm rounded-lg bg-red-700 hover:bg-red-600 transition-colors font-medium"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="px-3 py-2 text-sm rounded-lg bg-green-700 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Message bubble ──────────────────────────────────────────────────────────

function MessageBubble({
  message,
  isLast,
  isStreaming,
}: {
  message: Message;
  isLast: boolean;
  isStreaming: boolean;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-green-800 flex items-center justify-center text-xs shrink-0 mt-1 mr-2">
          ⬡
        </div>
      )}
      <div
        className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-green-800/70 text-green-50 rounded-tr-sm"
            : "bg-gray-800 text-gray-100 rounded-tl-sm"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <MarkdownContent content={message.content} />
        )}
        {isLast && isStreaming && !isUser && (
          <span className="inline-block w-1.5 h-4 bg-green-400 animate-pulse ml-0.5 align-middle rounded-sm" />
        )}
      </div>
      {isUser && (
        <div className="w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center text-xs shrink-0 mt-1 ml-2">
          U
        </div>
      )}
    </div>
  );
}

// ── Minimal markdown renderer ───────────────────────────────────────────────

function MarkdownContent({ content }: { content: string }) {
  if (!content) return null;

  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let codeBlock: string[] = [];
  let inCode = false;

  const renderInline = (text: string, key: number | string) => {
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    return (
      <span key={key}>
        {parts.map((p, i) => {
          if (p.startsWith("**") && p.endsWith("**"))
            return <strong key={i} className="text-gray-100">{p.slice(2, -2)}</strong>;
          if (p.startsWith("`") && p.endsWith("`"))
            return (
              <code key={i} className="bg-gray-700 px-1.5 py-0.5 rounded text-green-300 font-mono text-xs">
                {p.slice(1, -1)}
              </code>
            );
          return p;
        })}
      </span>
    );
  };

  lines.forEach((line, i) => {
    if (line.startsWith("```")) {
      if (!inCode) {
        inCode = true;
        codeBlock = [];
      } else {
        elements.push(
          <pre key={`code-${i}`} className="bg-gray-900 border border-gray-700 rounded-lg p-3 my-2 overflow-x-auto text-xs font-mono text-green-300 leading-relaxed">
            <code>{codeBlock.join("\n")}</code>
          </pre>
        );
        inCode = false;
        codeBlock = [];
      }
      return;
    }
    if (inCode) { codeBlock.push(line); return; }

    if (line.startsWith("### "))
      return elements.push(<h3 key={i} className="font-semibold text-green-400 mt-3 mb-1 text-sm">{renderInline(line.slice(4), i)}</h3>);
    if (line.startsWith("## "))
      return elements.push(<h2 key={i} className="font-bold text-green-300 mt-4 mb-1">{renderInline(line.slice(3), i)}</h2>);
    if (line.startsWith("# "))
      return elements.push(<h1 key={i} className="font-bold text-green-200 text-base mt-4 mb-2">{renderInline(line.slice(2), i)}</h1>);

    // Horizontal rule
    if (line.startsWith("---"))
      return elements.push(<hr key={i} className="border-gray-700 my-3" />);

    if (line.startsWith("- ") || line.startsWith("* "))
      return elements.push(
        <div key={i} className="flex gap-2 my-0.5">
          <span className="text-green-500 shrink-0 mt-0.5">•</span>
          <span>{renderInline(line.slice(2), i)}</span>
        </div>
      );
    if (/^\d+\. /.test(line)) {
      const [num, ...rest] = line.split(". ");
      return elements.push(
        <div key={i} className="flex gap-2 my-0.5">
          <span className="text-green-600 shrink-0 font-mono text-xs mt-0.5">{num}.</span>
          <span>{renderInline(rest.join(". "), i)}</span>
        </div>
      );
    }

    // Urgency badges
    if (/\b(Critical|High|Medium|Low)\b/.test(line)) {
      const colored = line.replace(
        /\b(Critical)\b/g, '<span class="text-red-400 font-bold">$1</span>'
      ).replace(
        /\b(High)\b/g, '<span class="text-orange-400 font-bold">$1</span>'
      ).replace(
        /\b(Medium)\b/g, '<span class="text-yellow-400 font-bold">$1</span>'
      ).replace(
        /\b(Low)\b/g, '<span class="text-green-400 font-bold">$1</span>'
      );
      return elements.push(
        <p key={i} className="my-0.5" dangerouslySetInnerHTML={{ __html: colored }} />
      );
    }

    if (line.trim() === "") return elements.push(<div key={i} className="h-2" />);
    elements.push(<p key={i} className="my-0.5">{renderInline(line, i)}</p>);
  });

  return <div>{elements}</div>;
}
