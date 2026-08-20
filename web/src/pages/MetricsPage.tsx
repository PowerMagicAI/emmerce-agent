import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { MetricDef } from "../types";

export function MetricsPage() {
  const [items, setItems] = useState<MetricDef[]>([]);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.metrics().then(setItems).catch(console.error);
  }, []);

  const filtered = useMemo(() => {
    const key = q.trim().toLowerCase();
    if (!key) return items;
    return items.filter(
      (m) =>
        m.metric_code.includes(key) ||
        m.name.toLowerCase().includes(key) ||
        m.aliases.some((a) => a.toLowerCase().includes(key)),
    );
  }, [items, q]);

  return (
    <div className="panel" style={{ padding: 20 }}>
      <input
        className="input"
        placeholder="搜索指标名 / 别名 / code"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        style={{ maxWidth: 420, marginBottom: 16 }}
      />
      <div className="grid-cards">
        {filtered.map((m) => (
          <div key={m.metric_code} className="card-row" style={{ flexDirection: "column", alignItems: "stretch" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <div>
                <div style={{ fontFamily: "var(--display)", fontSize: "1.2rem" }}>{m.name}</div>
                <div className="muted">{m.metric_code}</div>
              </div>
              <div className="chip">v{m.version}</div>
            </div>
            <div style={{ marginTop: 10 }}>
              <div>
                <strong>公式</strong>：{m.formula}
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                粒度 {m.grain} · 延迟 {m.latency} · 渠道 {m.channels.join("/")}
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                别名：{m.aliases.join("、")} · 误用提醒：{m.common_misuse}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
