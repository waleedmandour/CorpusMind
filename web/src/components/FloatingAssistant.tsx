/**
 * FloatingAssistant (v1.2.0, Issue 7b) — in-window AI chat available from
 * every analysis tool.
 *
 * - A floating action button (bottom-right) opens a chat drawer that
 *   persists across view switches (mounted once in App, next to the
 *   CommandPalette) so conversations survive navigation.
 * - Reuses the same grounded engine endpoint as the full Assistant view
 *   (api.chat): tool calls, evidence, grounded badge, model from the
 *   app store.
 * - Context-aware: sends a short "the user is viewing X" context string
 *   with every turn so the user can ask "what does this mean?" about the
 *   screen they're on.
 * - Suggested queries: prefabricated + dynamic (corpus-stats-derived)
 *   suggestions rendered as clickable chips.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type ChatTurnResponse, type QuerySuggestion } from "@/lib/api";
import { useApp } from "@/store/app";
import { useUI } from "@/store/ui";
import { t } from "@/lib/i18n";

/** Human label per sidebar nav id (falls back to the raw id). */
function navLabel(nav: string, lang: "en" | "ar"): string {
  const key = `nav_${nav}` as const;
  const label = t(lang, key as Parameters<typeof t>[1]);
  return label || nav;
}

interface Msg {
  role: "user" | "assistant";
  content: string;
  grounded?: boolean;
  toolCalls?: number;
  error?: boolean;
}

export function FloatingAssistant() {
  const open = useUI((s) => s.floatingAssistantOpen);
  const setOpen = useUI((s) => s.setFloatingAssistantOpen);
  const activeNav = useUI((s) => s.activeNav);
  const lang = useUI((s) => s.lang);
  const activeCorpusId = useApp((s) => s.activeCorpusId);
  const model = useApp((s) => s.selectedOllamaModel);

  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const suggestions = useQuery({
    queryKey: ["ai-suggestions", lang, activeCorpusId],
    queryFn: () => api.getQuerySuggestions(lang, activeCorpusId),
    enabled: open,
  });

  const dynamicSuggestions = useQuery({
    queryKey: ["ai-dynamic-suggestions", lang, activeCorpusId, model],
    queryFn: () =>
      api.getDynamicSuggestions({
        provider: "ollama",
        model: model ?? null,
        corpus_id: activeCorpusId,
        language: lang,
      }),
    enabled: open && !!activeCorpusId,
  });

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [messages, pending, open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const send = async (text: string) => {
    const msg = text.trim();
    if (!msg || pending) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg }]);
    setPending(true);
    try {
      const context = `${lang === "ar" ? "المستخدم يعرض حاليًا" : "The user is currently viewing the"} "${navLabel(activeNav, lang)}" ${lang === "ar" ? "شاشة التحليل." : "analysis screen."}`;
      const resp: ChatTurnResponse = await api.chat({
        message: msg,
        provider: "ollama",
        model: model ?? undefined,
        conversation_id: conversationId,
        corpus_id: activeCorpusId,
        context,
      });
      setConversationId(resp.conversation_id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: resp.content,
          grounded: resp.grounded,
          toolCalls: resp.tool_calls?.length ?? 0,
        },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: (e as Error).message, error: true }]);
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  };

  // Hide entirely on the full Assistant view (it already IS the assistant).
  // NOTE: must come AFTER all hooks (rules of hooks) — activeNav only
  // affects rendering, and every query above is already gated on `open`.
  if (activeNav === "assistant") return null;

  const chips: QuerySuggestion[] = [
    ...(suggestions.data?.suggestions ?? []),
    ...(dynamicSuggestions.data?.suggestions ?? []),
  ]
    .filter((s) => s.available !== false)
    .slice(0, 8);

  return (
    <>
      {/* Floating action button */}
      <button
        className={`ai-fab ${open ? "open" : ""}`}
        onClick={() => setOpen(!open)}
        title={t(lang, "ai_fab_label")}
        aria-label={t(lang, "ai_fab_label")}
        aria-expanded={open}
      >
        {open ? "\u2715" : "\u2726"}
      </button>

      {/* Drawer */}
      {open && (
        <div className="ai-drawer" role="dialog" aria-label={t(lang, "ai_drawer_title")}>
          <div className="ai-drawer-header">
            <strong>{t(lang, "ai_drawer_title")}</strong>
            <span className="ai-drawer-model">{model || "auto"}</span>
            <button
              className="ai-drawer-close"
              onClick={() => setOpen(false)}
              aria-label={t(lang, "ai_close")}
            >
              {"\u2715"}
            </button>
          </div>

          <div className="ai-drawer-context">
            {t(lang, "ai_context_viewing")}: <strong>{navLabel(activeNav, lang)}</strong>
            {activeCorpusId ? ` · ${t(lang, "ai_corpus_attached")}` : ` · ${t(lang, "ai_no_corpus")}`}
          </div>

          <div className="ai-drawer-thread" ref={threadRef}>
            {messages.length === 0 && (
              <div className="ai-drawer-empty">{t(lang, "ai_drawer_empty")}</div>
            )}
            {messages.map((m, i) => (
              <article key={i} className={`ai-drawer-msg ${m.role} ${m.error ? "error" : ""}`}>
                <div className="ai-drawer-msg-head">
                  <strong>{m.role === "user" ? t(lang, "ai_you") : t(lang, "ai_assistant")}</strong>
                  {m.role === "assistant" && !m.error && (
                    <span className={m.grounded ? "ai-badge grounded" : "ai-badge ungrounded"}>
                      {m.grounded ? t(lang, "ai_grounded") : t(lang, "ai_ungrounded")}
                    </span>
                  )}
                </div>
                <div className="ai-drawer-msg-body">{m.content}</div>
              </article>
            ))}
            {pending && <div className="ai-drawer-thinking">{t(lang, "ai_thinking")}</div>}
          </div>

          {chips.length > 0 && (
            <div className="ai-drawer-chips">
              {chips.map((s) => (
                <button
                  key={s.id}
                  className="ai-chip"
                  onClick={() => void send(s.query)}
                  title={s.description || s.query}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}

          <div className="ai-drawer-composer">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(input);
                }
              }}
              placeholder={t(lang, "ai_input_placeholder")}
              rows={2}
            />
            <button
              className="btn-small ai-send"
              onClick={() => void send(input)}
              disabled={!input.trim() || pending}
            >
              {t(lang, "ai_send")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
