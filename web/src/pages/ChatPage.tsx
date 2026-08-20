import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { api, chatStream } from "../api";
import { BlockRenderer } from "../components/BlockRenderer";
import type { AgentResponse, Me, MessageBlock, Session } from "../types";
import "./chat.css";

type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content?: string;
  blocks?: MessageBlock[];
  meta?: AgentResponse["meta"];
  runId?: string;
};

const SUGGESTIONS = [
  "今日支付GMV是多少",
  "有效订单量是多少",
  "对比8月3日和8月4日支付GMV",
  "帮我看一下价格异常",
  "有没有无效订单或刷单",
  "做一次经营诊断",
  "广告投放 ROI 怎么样",
  "扫描一下店铺预警",
  "对主图做OCR",
];

export function ChatPage() {
  const { me } = useOutletContext<{ me: Me | null }>();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [shopId, setShopId] = useState("shop_a1");
  const [busy, setBusy] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const shops = me?.shop_ids || ["shop_a1"];

  const refreshSessions = async () => {
    const list = await api.listSessions();
    setSessions(list);
    return list;
  };

  useEffect(() => {
    refreshSessions().catch(console.error);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, steps, busy]);

  const loadSession = async (id: string) => {
    const detail = await api.getSession(id);
    setActiveId(id);
    setShopId(detail.shop_id || shops[0]);
    setMessages(
      detail.messages.map((m, idx) => ({
        id: `${id}-${idx}`,
        role: m.role as "user" | "assistant",
        content: m.content,
        blocks: m.blocks,
        runId: m.run_id || undefined,
      })),
    );
  };

  const ensureSession = async () => {
    if (activeId) return activeId;
    const created = await api.createSession(shopId);
    await refreshSessions();
    setActiveId(created.session_id);
    return created.session_id;
  };

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    setBusy(true);
    setSteps([]);
    setDraft("");
    setInput("");
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", content: message }]);

    try {
      const sid = await ensureSession();
      const ac = new AbortController();
      abortRef.current = ac;
      await chatStream(
        sid,
        message,
        shopId,
        {
          onStep: (content) => setSteps((s) => [...s, content]),
          onToken: (chunk) => setDraft((d) => d + chunk),
          onResult: (resp) => {
            setDraft("");
            setMessages((prev) => [
              ...prev,
              {
                id: resp.run_id,
                role: "assistant",
                blocks: resp.blocks,
                meta: resp.meta,
                runId: resp.run_id,
              },
            ]);
            setSteps([]);
          },
        },
        ac.signal,
      );
      await refreshSessions();
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          blocks: [{ type: "error", content: err instanceof Error ? err.message : "请求失败", actions: ["重试"] }],
        },
      ]);
      setSteps([]);
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  const onCancel = async () => {
    abortRef.current?.abort();
    if (activeId) await api.cancel(activeId).catch(() => undefined);
    setBusy(false);
    setSteps([]);
    setDraft("");
  };

  const empty = useMemo(() => messages.length === 0 && !busy, [messages, busy]);

  return (
    <div className="chat-layout">
      <aside className="panel session-list">
        <button
          className="btn"
          type="button"
          onClick={async () => {
            const s = await api.createSession(shopId);
            await refreshSessions();
            setActiveId(s.session_id);
            setMessages([]);
          }}
        >
          新对话
        </button>
        {sessions.map((s) => (
          <button
            key={s.session_id}
            type="button"
            className={`session-item ${s.session_id === activeId ? "active" : ""}`}
            onClick={() => void loadSession(s.session_id)}
          >
            <div style={{ fontWeight: 600 }}>{s.title}</div>
            <div className="muted" style={{ fontSize: "0.75rem" }}>
              {new Date(s.updated_at).toLocaleString()}
            </div>
          </button>
        ))}
      </aside>

      <section className="panel chat-panel">
        <div className="messages">
          {empty && (
            <div className="empty-hero">
              <div className="brand-mark" style={{ fontSize: "2.4rem" }}>
                Emmerce
              </div>
              <h2>用自然语言问经营问题</h2>
              <p className="muted">自动完成取数、口径对齐、记忆召回与报表导出</p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="btn ghost" type="button" onClick={() => void send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className={`bubble ${m.role}`}>
              {m.role === "user" ? (
                m.content
              ) : (
                <>
                  <BlockRenderer
                    blocks={m.blocks || []}
                    meta={m.meta}
                    onClarify={(opt) => void send(opt)}
                  />
                  {m.runId && (
                    <div className="feedback-row">
                      <button
                        className="btn ghost"
                        type="button"
                        onClick={() =>
                          void api.feedback({ session_id: activeId!, thumbs_up: true })
                        }
                      >
                        有用
                      </button>
                      <button
                        className="btn danger"
                        type="button"
                        onClick={() =>
                          void api.feedback({
                            session_id: activeId!,
                            thumbs_down: true,
                            error_type: "data_error",
                          })
                        }
                      >
                        数据有误
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          ))}

          {draft && <div className="block step">{draft}</div>}
          {steps.map((s, i) => (
            <div key={`${s}-${i}`} className="block step">
              {s}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <form className="composer" onSubmit={onSubmit}>
          <div style={{ display: "grid", gap: 8 }}>
            <select
              className="input"
              value={shopId}
              onChange={(e) => setShopId(e.target.value)}
              style={{ maxWidth: 220 }}
            >
              {shops.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <textarea
              className="textarea"
              placeholder="例如：今日支付GMV是多少"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(input);
                }
              }}
            />
          </div>
          {busy ? (
            <button className="btn danger" type="button" onClick={() => void onCancel()}>
              停止
            </button>
          ) : (
            <button className="btn" type="submit" disabled={!input.trim()}>
              发送
            </button>
          )}
        </form>
      </section>
    </div>
  );
}
