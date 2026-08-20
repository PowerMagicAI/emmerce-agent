import { useEffect, useState } from "react";
import { api, type AlertItem } from "../api";

export function AlertsPage() {
  const [items, setItems] = useState<AlertItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    const data = await api.listAlerts("shop_a1", "all");
    setItems(data.alerts || []);
  };

  useEffect(() => {
    load().catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="panel" style={{ padding: 20, display: "grid", gap: 16 }}>
      <p className="muted" style={{ margin: 0, maxWidth: 720 }}>
        演示预警中心：阈值来自退款率、广告 ROI、假 OCR 图文不一致。数据在{" "}
        <code>datasets/demo/alerts.csv</code>，扫描会按当前仓库重算。
      </p>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          className="btn"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setErr("");
            try {
              await api.scanAlerts("shop_a1");
              await load();
            } catch (e) {
              setErr(e instanceof Error ? e.message : String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          重新扫描
        </button>
      </div>
      {err && <div className="muted">{err}</div>}
      <div className="grid-cards">
        {items.length === 0 && <div className="muted">暂无预警</div>}
        {items.map((a) => (
          <div key={a.id} className="card-row">
            <div>
              <div style={{ fontWeight: 600 }}>
                {a.severity} · {a.rule}
              </div>
              <div className="muted" style={{ marginTop: 6 }}>
                {a.message}
              </div>
              <div className="muted" style={{ marginTop: 8, fontSize: "0.78rem" }}>
                {a.status} · {a.metric_code}={a.value} · {a.created_at}
              </div>
            </div>
            {a.status === "open" && (
              <button
                className="btn ghost"
                type="button"
                onClick={async () => {
                  await api.ackAlert(a.id);
                  await load();
                }}
              >
                标记已处理
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
