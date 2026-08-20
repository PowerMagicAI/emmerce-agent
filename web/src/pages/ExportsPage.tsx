import { useEffect, useState } from "react";
import { api } from "../api";
import type { ExportItem } from "../types";

async function downloadWithAuth(url: string, filename: string) {
  const res = await fetch(url, {
    headers: {
      "X-Tenant-Id": "tenant_a",
      "X-User-Id": "user_a_owner",
      "X-Shop-Ids": "shop_a1,shop_a2",
      "X-Roles": "owner",
      "X-Is-Owner": "true",
    },
  });
  if (!res.ok) throw new Error(await res.text());
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function ExportsPage() {
  const [items, setItems] = useState<ExportItem[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .exports()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"));
  }, []);

  return (
    <div className="panel" style={{ padding: 20 }}>
      <p className="muted">导出文件默认 24 小时有效，仅本人可下载</p>
      {error && <div className="block error">{error}</div>}
      <div className="grid-cards" style={{ marginTop: 16 }}>
        {items.length === 0 && <div className="muted">暂无导出。可在对话中请求「导出 Excel」。</div>}
        {items.map((f) => (
          <div key={f.id} className="card-row">
            <div>
              <div style={{ fontWeight: 600 }}>{f.name}</div>
              <div className="muted" style={{ marginTop: 6, fontSize: "0.8rem" }}>
                生成 {new Date(f.created_at).toLocaleString()} · 过期{" "}
                {new Date(f.expires_at).toLocaleString()} · {f.status}
              </div>
            </div>
            <button
              className="btn amber"
              type="button"
              onClick={() =>
                void downloadWithAuth(f.download_url, f.name).catch((e) =>
                  alert(e instanceof Error ? e.message : "下载失败"),
                )
              }
            >
              下载
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
