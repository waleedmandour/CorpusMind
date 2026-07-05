/**
 * AssistantView — grounded chat (§11).
 *
 * The most important UI contract in the whole product: every answer is either
 *   - grounded (has tool_calls / evidence) → rendered with green checkmark + citations
 *   - ungrounded (no tool was invoked)    → rendered with a visible "UNGROUND" badge
 *
 * Citations are clickable: clicking a `concordance_line` evidence reference
 * scrolls to / opens the concordancer view filtered to that line.
 */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api, type ChatTurnResponse, type EvidenceItem } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";

interface Message {
  role: "user" | "assistant";
  content: string;
  grounded?: boolean;
  tool_calls?: Array<Record<string, unknown>>;
  evidence?: EvidenceItem[];
  elapsed_ms?: number;
}

export function AssistantView() {
  const cid = useApp((s) => s.activeCorpusId);
  const setActiveTab = useUI((s) => s.setActiveTab);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [provider, setProvider] = useState<"ollama" | "lmstudio" | "cloud">("ollama");
  const [conversationId, setConversationId] = useState<string | null>(null);

  const tools = useQuery({ queryKey: ["tools"], queryFn: api.listTools });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });

  const chat = useMutation({
    mutationFn: (text: string) =>
      api.chat({ message: text, provider, conversation_id: conversationId, corpus_id: cid }),
    onSuccess: (turn: ChatTurnResponse) => {
      setConversationId(turn.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: turn.content,
          grounded: turn.grounded,
          tool_calls: turn.tool_calls,
          evidence: turn.evidence,
          elapsed_ms: turn.elapsed_ms,
        },
      ]);
    },
    onError: (err: Error) => {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `[error] ${err.message}`, grounded: false },
      ]);
    },
  });

  const send = () => {
    const text = input.trim();
    if (!text || chat.isPending) return;
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    chat.mutate(text);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const providerHealthy = providers.data?.providers.find((p) => p.name === provider)?.healthy ?? false;
  const corpusHint = cid ? `Active corpus: ${cid.slice(0, 8)}…` : "No active corpus — set one in Text → Manage.";

  const prompts = [
    "What are the top 10 most frequent words in this corpus?",
    "Find all occurrences of 'fox' and show me their contexts.",
    "What are the strongest collocates of 'dog' within ±5 tokens?",
    "Compare this corpus against the reference — what are the top keywords?",
    "How evenly is 'the' distributed across the documents?",
  ];

  return (
    <div className="assistant">
      <aside className="assistant-sidebar">
        <h3>Model</h3>
        <select value={provider} onChange={(e) => setProvider(e.target.value as typeof provider)}>
          <option value="ollama">Ollama (local)</option>
          <option value="lmstudio">LM Studio (local)</option>
          <option value="cloud">Cloud (opt-in)</option>
        </select>
        <div className={clsx("provider-status", { ok: providerHealthy, bad: !providerHealthy })}>
          {providerHealthy ? "● connected" : "○ offline — start Ollama or LM Studio"}
        </div>

        <div className="corpus-hint">{corpusHint}</div>

        <h3>Grounded Tools</h3>
        <ul className="tool-list">
          {tools.data?.tools.map((t) => (
            <li key={t.name}>
              <code>{t.name}</code>
              <p>{t.description}</p>
            </li>
          ))}
        </ul>

        <div className="grounding-notice">
          <strong>Grounding policy.</strong> Every empirical claim the Assistant
          makes must come from a tool call. Answers with no tool calls are
          rendered with a visible <em>UNGROUND</em> badge.
        </div>
      </aside>

      <section className="assistant-main">
        <div className="assistant-thread">
          {messages.length === 0 && (
            <div className="empty-state">
              <h2>CorpusMind AI Assistant</h2>
              <p>Try one of these grounded questions:</p>
              <ul className="prompt-list">
                {prompts.map((p) => (
                  <li key={p}>
                    <button className="prompt-suggest" onClick={() => setInput(p)} disabled={!cid}>
                      {p}
                    </button>
                  </li>
                ))}
              </ul>
              {!cid && <p className="hint">Set an active corpus first (Text → Manage).</p>}
              {!providerHealthy && <p className="hint">Start Ollama or LM Studio to enable grounded answers.</p>}
            </div>
          )}

          {messages.map((m, i) => (
            <article key={i} className={clsx("msg", `msg-${m.role}`)}>
              <header>
                <span className="msg-role">{m.role === "user" ? "You" : "Assistant"}</span>
                {m.role === "assistant" && (
                  <span className={clsx("grounded-badge", { grounded: m.grounded, unground: !m.grounded })}>
                    {m.grounded ? "✓ grounded" : "⚠ unground"}
                  </span>
                )}
                {m.elapsed_ms != null && <span className="msg-meta">{m.elapsed_ms} ms</span>}
              </header>
              <div className="msg-content">{m.content}</div>
              {m.evidence && m.evidence.length > 0 && (
                <div className="evidence-list">
                  <strong>Evidence cited:</strong>
                  <ul>
                    {m.evidence.map((ev, j) => (
                      <li key={j} className={clsx("evidence-item", ev.kind)}>
                        <span className="evidence-kind">{ev.kind}</span>
                        <code className="evidence-ref" title={ev.snippet}>{ev.ref}</code>
                        {ev.kind === "concordance_line" && (
                          <button
                            className="evidence-link"
                            onClick={() => setActiveTab("text")}
                            title="Open concordancer"
                          >→ open</button>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {m.tool_calls && m.tool_calls.length > 0 && (
                <details className="tool-calls">
                  <summary>{m.tool_calls.length} tool call(s)</summary>
                  <pre>{JSON.stringify(m.tool_calls, null, 2)}</pre>
                </details>
              )}
            </article>
          ))}

          {chat.isPending && <div className="msg msg-assistant pending">Thinking…</div>}
        </div>

        <div className="composer">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask the Assistant about your corpus… (Enter to send, Shift+Enter for newline)"
            rows={2}
          />
          <button onClick={send} disabled={!input.trim() || chat.isPending}>
            Send
          </button>
        </div>
      </section>
    </div>
  );
}
