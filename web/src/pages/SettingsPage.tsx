import { useEffect, useState } from "react";
import { api } from "../api";

export function SettingsPage() {
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.getFlags().then(setFlags).catch(console.error);
  }, []);

  const toggle = async (key: string) => {
    const next = { ...flags, [key]: !flags[key] };
    setFlags(next);
    const saved = await api.putFlags({ [key]: next[key] });
    setFlags(saved);
    setMsg("能力开关已更新");
  };

  return (
    <div className="panel" style={{ padding: 20, display: "grid", gap: 16 }}>
      <div>
        <h2 style={{ margin: 0, fontFamily: "var(--display)" }}>能力降级开关</h2>
        <p className="muted">对应 PRD 管理能力最小集：故障时可关闭记忆 / RAG / 工具</p>
      </div>
      {Object.entries(flags).map(([k, v]) => (
        <label
          key={k}
          className="card-row"
          style={{ cursor: "pointer", alignItems: "center" }}
        >
          <span>{k}</span>
          <input type="checkbox" checked={v} onChange={() => void toggle(k)} />
        </label>
      ))}
      {msg && <div className="muted">{msg}</div>}
      <div className="card-row">
        <div>
          <div style={{ fontWeight: 600 }}>演示身份</div>
          <div className="muted" style={{ marginTop: 6 }}>
            服务端签发令牌；不能再靠请求头伪造租户。analyst 无管理接口权限。
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            className="btn ghost"
            type="button"
            onClick={async () => {
              await api.login("owner");
              window.location.reload();
            }}
          >
            owner
          </button>
          <button
            className="btn ghost"
            type="button"
            onClick={async () => {
              await api.login("analyst");
              window.location.reload();
            }}
          >
            analyst
          </button>
        </div>
      </div>
      <div className="card-row">
        <div>
          <div style={{ fontWeight: 600 }}>配额（演示）</div>
          <div className="muted" style={{ marginTop: 6 }}>
            MCP 查询：20 次/分钟 · 导出链接：24 小时有效
          </div>
        </div>
      </div>
    </div>
  );
}
