import { useState } from "react";
import { api } from "../api";

type RunState = {
  title: string;
  body: string;
};

export function DataOpsPage() {
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<RunState | null>(null);
  const [err, setErr] = useState("");

  const run = async (title: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr("");
    try {
      const data = await fn();
      setOut({ title, body: JSON.stringify(data, null, 2) });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel" style={{ padding: 20, display: "grid", gap: 16 }}>
      <p className="muted" style={{ margin: 0, maxWidth: 720 }}>
        数据生产与经营诊断：规则做抽取/分类/校验和无效单，统计做价格异常与销量基线。与对话 Agent
        共用同一套工具，也可 CLI 批跑。
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <button
          className="btn"
          disabled={busy}
          onClick={() => run("商品质检流水线", () => api.runPipeline("shop_a1"))}
        >
          跑质检流水线
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => run("商品质检工作流", () => api.runWorkflow("product_qc", "shop_a1"))}
        >
          工作流 product_qc
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => run("经营诊断工作流", () => api.runWorkflow("ops_diagnosis", "shop_a1"))}
        >
          工作流 ops_diagnosis
        </button>
        <button
          className="btn"
          disabled={busy}
          onClick={() => run("投放诊断工作流", () => api.runWorkflow("ad_diagnosis", "shop_a1"))}
        >
          工作流 ad_diagnosis
        </button>
        <button className="btn" disabled={busy} onClick={() => run("运营观测", () => api.getOps())}>
          查看 /admin/ops
        </button>
      </div>
      {err && <div className="muted">{err}</div>}
      {out && (
        <pre
          style={{
            margin: 0,
            padding: 16,
            borderRadius: 12,
            background: "var(--foam)",
            overflow: "auto",
            maxHeight: 520,
            fontSize: 12,
          }}
        >
          {out.title}
          {"\n"}
          {out.body}
        </pre>
      )}
    </div>
  );
}
