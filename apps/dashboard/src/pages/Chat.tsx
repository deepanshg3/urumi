import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  ClipboardList,
  MessageSquarePlus,
  PackageSearch,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
  Truck,
} from "lucide-react";

import { agentApi, ApiError } from "../api";
import type { AgentConfig, Conversation, ToolCall } from "../types";
import { Button, ErrorNotice } from "../components/ui";
import { formatLatency, formatRelative } from "../lib/format";
import { renderMarkdown } from "../lib/markdown";

interface ChatEntry {
  id: string;
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCall[];
  warning?: string | null;
  error?: string | null;
}

const STARTER_PROMPTS: { prompt: string; icon: typeof PackageSearch }[] = [
  { prompt: "Show me the products in my store.", icon: PackageSearch },
  { prompt: "Which products are running low on stock?", icon: Boxes },
  { prompt: "Check the shipment status for an order.", icon: Truck },
  { prompt: "Summarize recent inventory activity.", icon: ClipboardList },
];

let entryCounter = 0;
function nextEntryId(): string {
  entryCounter += 1;
  return `entry-${entryCounter}`;
}

export default function Chat() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [toolCount, setToolCount] = useState<number | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<number | undefined>(undefined);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAttempt, setLastAttempt] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  async function refreshConversations() {
    try {
      setConversations(await agentApi.conversations());
    } catch {
      // non-fatal: the chat itself still works
    }
  }

  useEffect(() => {
    agentApi.config().then(setConfig).catch((err) => setError(String(err)));
    agentApi.tools().then((tools) => setToolCount(tools.length)).catch(() => setToolCount(null));
    void refreshConversations();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [entries, sending]);

  async function send(messageOverride?: string) {
    const message = (messageOverride ?? input).trim();
    if (!message || sending) return;
    setError(null);
    setInput("");
    setLastAttempt(message);
    setEntries((prev) => [...prev, { id: nextEntryId(), role: "user", content: message }]);
    setSending(true);
    try {
      const result = await agentApi.chat(message, conversationId);
      setConversationId(result.conversation_id);
      const warning = result.truncated
        ? `Stopped early (${result.truncated_reason ?? "limit"}).`
        : result.model_error
          ? `Model error: ${result.model_error}.`
          : null;
      setEntries((prev) => [
        ...prev,
        {
          id: nextEntryId(),
          role: "assistant",
          content: result.reply,
          tool_calls: result.tool_calls,
          warning,
        },
      ]);
      setLastAttempt(null);
      void refreshConversations();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : String(err);
      setError(message);
      setEntries((prev) => [
        ...prev,
        {
          id: nextEntryId(),
          role: "assistant",
          content: "",
          error: message,
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  async function openConversation(id: number) {
    setError(null);
    try {
      const detail = await agentApi.conversation(id);
      setConversationId(id);
      setEntries(
        detail.messages.map((message) => ({
          id: `stored-${message.id}`,
          role: message.role === "user" ? "user" : "assistant",
          content: message.content,
          tool_calls: message.tool_summary ?? undefined,
        })),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  async function deleteConversation(id: number) {
    setError(null);
    try {
      await agentApi.deleteConversation(id);
      if (conversationId === id) {
        setConversationId(undefined);
        setEntries([]);
      }
      await refreshConversations();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  function newConversation() {
    setConversationId(undefined);
    setEntries([]);
    setError(null);
    setLastAttempt(null);
    window.location.hash = "#/chat";
  }

  function applyStarter(prompt: string) {
    setInput(prompt);
    inputRef.current?.focus();
  }

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === conversationId) ?? null,
    [conversations, conversationId],
  );

  return (
    <div className="chat-page">
      <aside className="chat-rail">
        <div className="chat-rail-head">
          <span className="chat-rail-title">Conversations</span>
          <Button
            size="sm"
            variant="secondary"
            icon={<MessageSquarePlus aria-hidden="true" />}
            onClick={newConversation}
          >
            New
          </Button>
        </div>

        {conversations.length === 0 ? (
          <p className="inline-note">
            Saved conversations appear here once you send your first message.
          </p>
        ) : (
          <div className="conversation-list">
            {conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={`conversation-item${conversation.id === conversationId ? " is-active" : ""}`}
              >
                <button
                  type="button"
                  className="conversation-open"
                  onClick={() => void openConversation(conversation.id)}
                >
                  <span className="conversation-title">
                    {conversation.title || `Conversation ${conversation.id}`}
                  </span>
                  <span className="conversation-meta">
                    {formatRelative(conversation.updated_at)} · #{conversation.id}
                  </span>
                </button>
                <div className="row-actions" style={{ justifyContent: "flex-start", marginTop: 6 }}>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Trash2 aria-hidden="true" />}
                    onClick={() => void deleteConversation(conversation.id)}
                    aria-label={`Delete conversation ${conversation.id}`}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </aside>

      <section className="chat-panel" aria-label="Conversation">
        <header className="chat-panel-head">
          <div>
            <div className="chat-panel-title">
              {activeConversation
                ? activeConversation.title || `Conversation ${activeConversation.id}`
                : "New conversation"}
            </div>
            <div className="chat-panel-meta">
              <span>
                {config ? `Model ${config.model}` : "Connecting to agent…"}
              </span>
              {toolCount !== null && <span>{toolCount} authorized tool(s)</span>}
              {config && <span>max {config.max_iterations} steps</span>}
              {config && <span>tracing {config.tracing_enabled ? "on" : "off"}</span>}
            </div>
          </div>
          {conversationId !== undefined && (
            <Button size="sm" variant="secondary" onClick={newConversation}>
              Start new
            </Button>
          )}
        </header>

        <div className="chat-log">
          {entries.length === 0 ? (
            <div className="chat-empty">
              <span className="chat-empty-icon">
                <Sparkles aria-hidden="true" />
              </span>
              <p className="chat-empty-title">Ask Urumi about your store</p>
              <p className="chat-empty-text">
                The assistant calls the gateway&apos;s MCP tools on your behalf — every call is
                authorized against your role and recorded in the audit log.
              </p>
              <div className="starter-grid">
                {STARTER_PROMPTS.map((starter) => {
                  const Icon = starter.icon;
                  return (
                    <button
                      key={starter.prompt}
                      type="button"
                      className="starter-prompt"
                      onClick={() => applyStarter(starter.prompt)}
                    >
                      <Icon aria-hidden="true" />
                      <span>{starter.prompt}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="chat-thread">
              {entries.map((entry) => (
                <article
                  key={entry.id}
                  className={`message is-${entry.role}`}
                  aria-label={entry.role === "user" ? "Your message" : "Assistant reply"}
                >
                  <div className="message-meta">
                    {entry.role === "user" ? (
                      <>You</>
                    ) : (
                      <>
                        <Sparkles aria-hidden="true" /> Urumi assistant
                      </>
                    )}
                  </div>
                  <div
                    className={`bubble is-${entry.role}${entry.error ? " is-error" : ""}`}
                  >
                    {entry.error ? (
                      <>
                        <p>{entry.error}</p>
                        {lastAttempt && (
                          <div className="row-actions" style={{ justifyContent: "flex-start" }}>
                            <Button
                              size="sm"
                              variant="danger-soft"
                              icon={<RotateCcw aria-hidden="true" />}
                              onClick={() => void send(lastAttempt)}
                              disabled={sending}
                            >
                              Retry request
                            </Button>
                          </div>
                        )}
                      </>
                    ) : (
                      renderMarkdown(entry.content)
                    )}
                  </div>
                  {entry.tool_calls && entry.tool_calls.length > 0 && (
                    <div className="tool-strip">
                      {entry.tool_calls.map((call, index) => (
                        <span
                          key={`${call.tool}-${index}`}
                          className={`tool-chip ${call.status === "ok" ? "is-ok" : "is-error"}`}
                          title={`${call.tool} — ${call.status} — ${formatLatency(call.latency_ms)}`}
                        >
                          {call.tool} · {call.status} · {formatLatency(call.latency_ms)}
                        </span>
                      ))}
                    </div>
                  )}
                  {entry.warning && (
                    <div className="notice is-warn">
                      <AlertTriangle aria-hidden="true" />
                      <div className="notice-body">{entry.warning}</div>
                    </div>
                  )}
                </article>
              ))}

              {sending && (
                <div className="thinking" role="status" aria-live="polite">
                  <span className="dots" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </span>
                  Urumi is working — it may call several tools before replying.
                </div>
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && entries.length === 0 && (
          <div style={{ padding: "0 var(--space-5) var(--space-3)" }}>
            <ErrorNotice message={error} />
          </div>
        )}

        <form
          className="chat-composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <div className="composer-input">
            <textarea
              ref={inputRef}
              value={input}
              placeholder="Ask about products, stock levels, orders or shipments…"
              rows={1}
              aria-label="Message the Urumi assistant"
              onChange={(event) => {
                setInput(event.target.value);
                event.target.style.height = "auto";
                event.target.style.height = `${Math.min(event.target.scrollHeight, 190)}px`;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <button
              type="submit"
              className="composer-send"
              disabled={sending || !input.trim()}
              aria-label="Send message"
            >
              {sending ? (
                <span className="spinner" aria-hidden="true" />
              ) : (
                <Send aria-hidden="true" />
              )}
            </button>
          </div>
          <div className="composer-hint">
            <span>
              <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line
            </span>
            <span>Tools are authorized by your role — read-only tools stay read-only.</span>
          </div>
        </form>
      </section>
    </div>
  );
}
