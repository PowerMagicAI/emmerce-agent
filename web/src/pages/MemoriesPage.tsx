import { useEffect, useState } from "react";
import { api } from "../api";
import type { MemoryItem } from "../types";

export function MemoriesPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [error, setError] = useState("");

  const load = async () => {
    try {
      setItems(await api.memories());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  return (
    <div className="panel" style={{ padding: 20 }}>
      <p className="muted">商家私有情景记忆 · 可删除 / 标记重要以提升召回权重</p>
      {error && <div className="block error">{error}</div>}
      <div className="grid-cards" style={{ marginTop: 16 }}>
        {items.length === 0 && <div className="muted">暂无记忆。先在对话工作台完成一次分析。</div>}
        {items.map((m) => (
          <div key={m.id} className="card-row">
            <div>
              <div style={{ fontWeight: 600 }}>{m.topic}</div>
              <div className="muted" style={{ marginTop: 6 }}>
                {m.conclusion}
              </div>
              <div className="muted" style={{ marginTop: 8, fontSize: "0.78rem" }}>
                {m.time_range} · 店铺 {m.shop_ids.join(",")} · 重要度 {m.importance} ·{" "}
                {new Date(m.created_at).toLocaleString()}
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="btn ghost"
                type="button"
                onClick={async () => {
                  await api.starMemory(m.id);
                  await load();
                }}
              >
                标为重要
              </button>
              <button
                className="btn danger"
                type="button"
                onClick={async () => {
                  if (!confirm("确认删除该记忆？")) return;
                  await api.deleteMemory(m.id);
                  await load();
                }}
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
