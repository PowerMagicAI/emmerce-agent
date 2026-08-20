import type { MessageBlock, ResponseMeta } from "../types";

export function BlockRenderer({
  blocks,
  meta,
  onClarify,
}: {
  blocks: MessageBlock[];
  meta?: ResponseMeta | null;
  onClarify?: (option: string) => void;
}) {
  return (
    <div className="blocks">
      {blocks.map((b, i) => {
        if (b.type === "step") {
          return (
            <div key={i} className="block step">
              {b.content}
            </div>
          );
        }
        if (b.type === "metric") {
          return (
            <div key={i} className="block metric">
              <div className="metric-code">{b.metric_code}</div>
              <div className="metric-value">
                {b.value?.toLocaleString()} <span>{b.unit}</span>
              </div>
              {b.content && <div className="muted">{b.content}</div>}
            </div>
          );
        }
        if (b.type === "table" && b.columns && b.rows) {
          return (
            <div key={i} className="block table-wrap">
              <table>
                <thead>
                  <tr>
                    {b.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, ri) => (
                    <tr key={ri}>
                      {row.map((cell, ci) => (
                        <td key={ci}>{String(cell)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (b.type === "file") {
          return (
            <div key={i} className="block file">
              <div>{b.name || "报表文件"}</div>
              {b.url && (
                <button
                  className="btn amber"
                  type="button"
                  style={{ marginTop: 8 }}
                  onClick={() => {
                    void (async () => {
                      const res = await fetch(b.url!, {
                        headers: {
                          "X-Tenant-Id": "tenant_a",
                          "X-User-Id": "user_a_owner",
                          "X-Shop-Ids": "shop_a1,shop_a2",
                          "X-Roles": "owner",
                          "X-Is-Owner": "true",
                        },
                      });
                      if (!res.ok) {
                        alert(await res.text());
                        return;
                      }
                      const blob = await res.blob();
                      const a = document.createElement("a");
                      a.href = URL.createObjectURL(blob);
                      a.download = b.name || "report.xlsx";
                      a.click();
                      URL.revokeObjectURL(a.href);
                    })();
                  }}
                >
                  下载
                </button>
              )}
            </div>
          );
        }
        if (b.type === "clarification") {
          return (
            <div key={i} className="block clarify">
              <div style={{ fontWeight: 600, marginBottom: 10 }}>{b.question}</div>
              <div className="clarify-options">
                {(b.options || []).map((opt) => (
                  <button key={opt} className="btn ghost" type="button" onClick={() => onClarify?.(opt)}>
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          );
        }
        if (b.type === "citation") {
          return (
            <div key={i} className="block citation">
              引用 · {b.kind} · {b.title}
            </div>
          );
        }
        if (b.type === "warning") {
          return (
            <div key={i} className="block warning">
              {b.content}
            </div>
          );
        }
        if (b.type === "error") {
          return (
            <div key={i} className="block error">
              <div>{b.content}</div>
              {b.actions && (
                <div className="muted" style={{ marginTop: 8 }}>
                  {b.actions.join(" / ")}
                </div>
              )}
            </div>
          );
        }
        return (
          <div key={i} className="block text">
            {b.content}
          </div>
        );
      })}
      {meta && (
        <div className="meta-bar">
          <span>截至 {meta.data_as_of}</span>
          <span>店铺 {meta.shops.join(",") || "-"}</span>
          <span>渠道 {meta.channels.join(",")}</span>
          <span>trace {meta.trace_id}</span>
        </div>
      )}
    </div>
  );
}
