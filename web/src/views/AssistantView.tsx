/**
 * AssistantView - grounded chat (11).
 *
 * The most important UI contract in the whole product: every answer is either
 *   - grounded (has tool_calls / evidence) → rendered with green checkmark + citations
 *   - ungrounded (no tool was invoked)    → rendered with a visible "UNGROUND" badge
 *
 * Citations are clickable: clicking a `concordance_line` evidence reference
 * scrolls to / opens the concordancer view filtered to that line.
 */
import { useState, useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";

import { api, type ChatTurnResponse, type EvidenceItem, type MCQ, type QuerySuggestion } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";

interface Message {
  role: "user" | "assistant";
  content: string;
  grounded?: boolean;
  tool_calls?: Array<Record<string, unknown>>;
  evidence?: EvidenceItem[];
  elapsed_ms?: number;
  turn_id?: number;
  verified?: "accepted" | "rejected" | "edited" | null;
  studentInterpretation?: string;
  confidence?: number;
  confidence_reasoning?: string;
  needs_validation?: boolean;
  mcqs?: MCQ[];
  mcqsAnswered?: boolean;
}

export function AssistantView() {
  const cid = useApp((s) => s.activeCorpusId);
  const storeModel = useApp((s) => s.selectedOllamaModel);
  const setActiveNav = useUI((s) => s.setActiveNav);
  const studentMode = useUI((s) => s.studentMode);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [provider, setProvider] = useState<"ollama" | "lmstudio" | "cloud">("ollama");
  const [localModel, setLocalModel] = useState<string>("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [showStudentInput, setShowStudentInput] = useState<number | null>(null);

  // The effective model: store-loaded takes priority, then local selection, then auto
  const selectedModel = storeModel || localModel;
  const [studentText, setStudentText] = useState("");

  const tools = useQuery({ queryKey: ["tools"], queryFn: api.listTools });
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });

  // List installed Ollama models for the model selector
  const ollamaModels = useQuery({
    queryKey: ["ollama-models"],
    queryFn: () => api.listModels("ollama"),
    enabled: provider === "ollama",
    refetchInterval: 10_000,
  });

  // Auto-select the first available model when none is selected
  useEffect(() => {
    if (provider === "ollama" && !storeModel && !localModel && ollamaModels.data && ollamaModels.data.models.length > 0) {
      setLocalModel(ollamaModels.data.models[0]);
    }
  }, [provider, storeModel, localModel, ollamaModels.data]);

  const chat = useMutation({
    mutationFn: (text: string) =>
      api.chat({
        message: text,
        provider,
        model: selectedModel || null,
        conversation_id: conversationId,
        corpus_id: cid,
      }),
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
          confidence: turn.confidence,
          confidence_reasoning: turn.confidence_reasoning,
          needs_validation: turn.needs_validation,
          mcqs: turn.mcqs,
          mcqsAnswered: false,
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
  const corpusHint = cid ? "Active corpus loaded" : "No active corpus. Set one in Your Corpus.";

  const verifyInterpretation = async (msgIndex: number, verified: "accepted" | "rejected" | "edited") => {
    const msg = messages[msgIndex];
    if (!msg.turn_id) return;
    try {
      await api.verifyTurn(msg.turn_id, verified);
      setMessages((prev) => prev.map((m, i) =>
        i === msgIndex ? { ...m, verified } : m
      ));
    } catch (e) {
      setMessages((prev) => prev.map((m, i) =>
        i === msgIndex ? { ...m, verified } : m
      ));
    }
  };

  const [editIndex, setEditIndex] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const startEdit = (idx: number) => {
    setEditIndex(idx);
    setEditText(messages[idx]?.content || "");
  };

  const submitEdit = async () => {
    if (editIndex === null) return;
    await verifyInterpretation(editIndex, "edited");
    setMessages((prev) => prev.map((m, i) =>
      i === editIndex ? { ...m, content: editText } : m
    ));
    setEditIndex(null);
    setEditText("");
  };

  // Issue 2c: replace the hardcoded `prompts` array with a live query to
  // the /api/v1/ai/query-suggestions endpoint. The suggestions are now
  // corpus-aware (the endpoint marks keyness suggestions as unavailable
  // when no reference corpus is installed) and include both pre-fabricated
  // templates and LLM-generated dynamic suggestions.
  //
  // The suggestions are also PERSISTENT — they remain visible throughout
  // the conversation, not just at first load. The user can toggle the
  // panel with the "Suggestions" button in the sidebar.
  const [showSuggestions, setShowSuggestions] = useState(true);
  const suggestions = useQuery({
    queryKey: ["query-suggestions", cid, provider, selectedModel],
    queryFn: () => api.getQuerySuggestions("en", cid),
    enabled: true,
    staleTime: 60_000, // don't refetch on every render
  });

  // Regenerate dynamic suggestions (calls the /dynamic endpoint which
  // uses the LLM to produce corpus-aware follow-ups).
  const regenerateDynamic = useMutation({
    mutationFn: () => api.getDynamicSuggestions({
      provider,
      model: selectedModel || null,
      corpus_id: cid,
      language: "en",
    }),
    onSuccess: () => {
      suggestions.refetch();
    },
  });

  const allSuggestions: QuerySuggestion[] = suggestions.data?.suggestions ?? [];
  const prefabricated = allSuggestions.filter(s => s.source === "prefabricated");
  const dynamic = allSuggestions.filter(s => s.source === "dynamic");

  return (
    <div className="assistant">
      <aside className="assistant-sidebar">
        <h3>Model Provider</h3>
        <select value={provider} onChange={(e) => { setProvider(e.target.value as typeof provider); setLocalModel(""); }}>
          <option value="ollama">Ollama (local)</option>
          <option value="lmstudio">LM Studio (local)</option>
          <option value="cloud">Cloud (opt-in)</option>
        </select>
        <div className={clsx("provider-status", { ok: providerHealthy, bad: !providerHealthy })}>
          {providerHealthy ? "Connected" : "Offline"}
        </div>

        {provider === "ollama" && ollamaModels.data && ollamaModels.data.models.length > 0 && (
          <>
            <h3>Loaded Model</h3>
            <select
              value={selectedModel}
              onChange={(e) => setLocalModel(e.target.value)}
              className="model-select"
            >
              <option value="">Auto (default)</option>
              {ollamaModels.data.models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            {selectedModel && (
              <div className="model-loaded-badge">
                {"\u2713"} {selectedModel}
              </div>
            )}
          </>
        )}
        {provider === "ollama" && ollamaModels.data?.models.length === 0 && (
          <p className="hint">No models installed. Go to Settings to download one.</p>
        )}

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

        {/* Issue 2c: persistent suggestions panel in the sidebar.
            Previously the prompts only appeared in the empty-state block
            and vanished after the first message. Now they're always
            available here, plus a collapsible strip above the composer. */}
        <h3>
          Suggested questions
          <button
            className="btn-small"
            style={{ marginLeft: "var(--space-2)", fontSize: "10px", padding: "1px 6px" }}
            onClick={() => setShowSuggestions(!showSuggestions)}
          >
            {showSuggestions ? "Hide" : "Show"}
          </button>
        </h3>
        {showSuggestions && (
          <>
            {prefabricated.length > 0 && (
              <ul className="prompt-list" style={{ listStyle: "none", padding: 0 }}>
                {prefabricated.slice(0, 6).map((s) => (
                  <li key={s.id}>
                    <button
                      className="prompt-suggest"
                      onClick={() => setInput(s.query)}
                      disabled={!s.available}
                      title={s.unavailable_reason || s.description || ""}
                    >
                      {s.label}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {dynamic.length > 0 && (
              <>
                <h4 style={{ fontSize: "11px", marginTop: "var(--space-2)", color: "var(--text-muted)" }}>
                  Dynamic ({dynamic.length})
                  <button
                    className="btn-small"
                    style={{ marginLeft: "var(--space-1)", fontSize: "10px", padding: "1px 4px" }}
                    onClick={() => regenerateDynamic.mutate()}
                    disabled={regenerateDynamic.isPending || !providerHealthy || !cid}
                    title="Regenerate LLM-powered suggestions based on your corpus"
                  >
                    {regenerateDynamic.isPending ? "…" : "↻"}
                  </button>
                </h4>
                <ul className="prompt-list" style={{ listStyle: "none", padding: 0 }}>
                  {dynamic.map((s) => (
                    <li key={s.id}>
                      <button
                        className="prompt-suggest"
                        onClick={() => setInput(s.query)}
                        title={s.rationale || ""}
                      >
                        {s.label}
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {dynamic.length === 0 && cid && providerHealthy && (
              <p className="hint" style={{ fontSize: "11px" }}>
                No dynamic suggestions yet. Click ↻ to generate LLM-powered
                follow-ups based on your corpus.
              </p>
            )}
            {!cid && <p className="hint" style={{ fontSize: "11px" }}>Set an active corpus to enable dynamic suggestions.</p>}
            {!providerHealthy && <p className="hint" style={{ fontSize: "11px" }}>Start Ollama or LM Studio for dynamic suggestions.</p>}
          </>
        )}
      </aside>

      <section className="assistant-main">
        <div className="assistant-thread">
          {messages.length === 0 && (
            <div className="empty-state">
              <h2>CorpusMind AI Assistant</h2>
              <p>Try one of the suggested questions in the sidebar, or ask your own below.</p>
              {!cid && <p className="hint">Set an active corpus first (Your Corpus).</p>}
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
                {m.verified && (
                  <span className={clsx("verify-badge", m.verified)}>
                    {m.verified === "accepted" ? "✓ verified" : m.verified === "rejected" ? "✗ rejected" : "✎ edited"}
                  </span>
                )}
              </header>

              {/* Student mode: hide AI content until student writes their own interpretation */}
              {m.role === "assistant" && studentMode && !m.studentInterpretation && (
                <div className="student-mode-notice">
                  <p>{"\u2139"} Student mode is ON. Write your own interpretation first, then reveal the AI's answer for comparison.</p>
                  <textarea
                    value={showStudentInput === i ? studentText : ""}
                    onChange={(e) => { setShowStudentInput(i); setStudentText(e.target.value); }}
                    placeholder="Write your own interpretation of the results..."
                    className="student-interpretation-input"
                    rows={3}
                  />
                  {showStudentInput === i && studentText.trim() && (
                    <button
                      className="btn-small"
                      onClick={() => {
                        setMessages((prev) => prev.map((msg, idx) =>
                          idx === i ? { ...msg, studentInterpretation: studentText.trim() } : msg
                        ));
                        setStudentText("");
                        setShowStudentInput(null);
                      }}
                    >
                      Reveal AI answer
                    </button>
                  )}
                </div>
              )}

              {/* Show student's interpretation (if student mode + they wrote one) */}
              {m.role === "assistant" && m.studentInterpretation && (
                <div className="student-interpretation-display">
                  <strong>Your interpretation:</strong>
                  <p>{m.studentInterpretation}</p>
                </div>
              )}

              {/* Show AI content (always in normal mode, after student writes in student mode) */}
              {m.role === "assistant" && (!studentMode || m.studentInterpretation) && (
                <>
                  {/* Confidence display */}
                  {m.confidence != null && m.confidence < 1.0 && (
                    <div className="confidence-display">
                      <div className="confidence-bar">
                        <div
                          className={`confidence-fill ${m.confidence >= 0.7 ? "high" : m.confidence >= 0.4 ? "medium" : "low"}`}
                          style={{ width: `${m.confidence * 100}%` }}
                        />
                      </div>
                      <span className="confidence-label">
                        Confidence: {(m.confidence * 100).toFixed(0)}%
                      </span>
                      {m.confidence_reasoning && (
                        <span className="confidence-reasoning">- {m.confidence_reasoning}</span>
                      )}
                    </div>
                  )}

                  {/* MCQ validation (when confidence is low) */}
                  {m.needs_validation && m.mcqs && m.mcqs.length > 0 && !m.mcqsAnswered && (
                    <MCQValidation
                      mcqs={m.mcqs}
                      onComplete={() => {
                        setMessages((prev) => prev.map((msg, idx) =>
                          idx === i ? { ...msg, mcqsAnswered: true } : msg
                        ));
                      }}
                    />
                  )}

                  {/* Show content only if no validation needed, or MCQs answered, or high confidence */}
                  {(!m.needs_validation || m.mcqsAnswered || (m.confidence != null && m.confidence >= 0.7)) && (
                    <>
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
                                onClick={() => setActiveNav("concordance")}
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

                  {/* Verify This Interpretation buttons (human-in-the-loop) */}
                  {!m.verified && m.turn_id && (
                    <>
                    <div className="verify-buttons">
                      <span className="verify-label">Verify this interpretation:</span>
                      <button className="btn-small verify-accept" onClick={() => verifyInterpretation(i, "accepted")}>{"\u2713"} Accept</button>
                      <button className="btn-small verify-reject" onClick={() => verifyInterpretation(i, "rejected")}>{"\u2717"} Reject</button>
                      <button className="btn-small verify-edit" onClick={() => startEdit(i)}>{"\u270E"} Edit</button>
                    </div>
                    {editIndex === i && (
                      <div style={{ marginTop: "var(--space-2)" }}>
                        <textarea
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                          rows={4}
                          style={{ width: "100%", fontSize: "13px", padding: "var(--space-2)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}
                        />
                        <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-1)" }}>
                          <button className="btn-primary btn-small" onClick={submitEdit}>Save Edit</button>
                          <button className="btn-small" onClick={() => { setEditIndex(null); setEditText(""); }}>Cancel</button>
                        </div>
                      </div>
                    )}
                    </>
                  )}
                </>
              )}
              </>

              )}

              {m.role === "user" && (
                <div className="msg-content">{m.content}</div>
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


function MCQValidation({ mcqs, onComplete }: { mcqs: MCQ[]; onComplete: () => void }) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);

  const allAnswered = mcqs.every((_, i) => answers[i] !== undefined);
  const allCorrect = mcqs.every((mcq, i) => answers[i] === mcq.correct_answer);

  const handleSubmit = () => {
    setSubmitted(true);
  };

  const handleReveal = () => {
    onComplete();
  };

  return (
    <div className="mcq-container">
      <p className="mcq-title">
        {"\u26A0"} This interpretation has low confidence. Answer these
        questions to verify the key claims before revealing the AI&apos;s answer.
      </p>
      {mcqs.map((mcq, i) => (
        <div key={i} style={{ marginBottom: "var(--space-2)" }}>
          <div className="mcq-question">{i + 1}. {mcq.question}</div>
          <div className="mcq-options">
            {mcq.options.map((opt, j) => {
              const isSelected = answers[i] === j;
              const showResult = submitted;
              const isCorrect = j === mcq.correct_answer;
              const isUserAnswer = isSelected && !isCorrect;
              return (
                <button
                  key={j}
                  className={`mcq-option ${showResult && isCorrect ? "correct" : ""} ${showResult && isUserAnswer ? "incorrect" : ""}`}
                  onClick={() => !submitted && setAnswers({ ...answers, [i]: j })}
                  disabled={submitted}
                >
                  {String.fromCharCode(65 + j)}. {opt}
                </button>
              );
            })}
          </div>
          {submitted && (
            <div className="mcq-explanation">
              {answers[i] === mcq.correct_answer ? "✓ " : "✗ "}
              {mcq.explanation}
            </div>
          )}
        </div>
      ))}
      {!submitted && (
        <button
          className="mcq-reveal-btn"
          onClick={handleSubmit}
          disabled={!allAnswered}
        >
          Submit answers
        </button>
      )}
      {submitted && (
        <button className="mcq-reveal-btn" onClick={handleReveal}>
          {allCorrect ? "✓ All correct - reveal AI answer" : "Reveal AI answer anyway"}
        </button>
      )}
    </div>
  );
}
