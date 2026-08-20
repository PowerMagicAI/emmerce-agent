import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "./api";
import type { Me } from "./types";

const titles: Record<string, string> = {
  "/": "对话工作台",
  "/memories": "记忆中心",
  "/exports": "报表中心",
  "/metrics": "指标字典",
  "/data-ops": "数据生产",
  "/alerts": "预警中心",
  "/settings": "设置与配额",
};

export function AppLayout() {
  const loc = useLocation();
  const [me, setMe] = useState<Me | null>(null);

  const loadMe = () => {
    api.me().then(setMe).catch(() => setMe(null));
  };

  useEffect(() => {
    loadMe();
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-row">
            <div className="brand-glyph" aria-hidden />
            <div className="brand-mark">Emmerce</div>
          </div>
          <div className="brand-sub">商家数据分析助手</div>
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            对话工作台
          </NavLink>
          <NavLink to="/memories">记忆中心</NavLink>
          <NavLink to="/exports">报表中心</NavLink>
          <NavLink to="/metrics">指标字典</NavLink>
          <NavLink to="/data-ops">数据生产</NavLink>
          <NavLink to="/alerts">预警中心</NavLink>
          <NavLink to="/settings">设置</NavLink>
        </nav>
        <div className="sidebar-foot">
          <span className="status-dot" aria-hidden />
          <span>系统在线 · 内网合规</span>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <h1>{titles[loc.pathname] || "Emmerce Agent"}</h1>
          {me && (
            <div className="chip">
              <span>{me.user_id}</span>
              <span>·</span>
              <span>{me.shop_ids[0]}</span>
              <span>·</span>
              <span>{me.is_owner ? "owner" : me.roles[0] || "user"}</span>
            </div>
          )}
        </header>
        <div className="content">
          <Outlet context={{ me }} />
        </div>
      </div>
    </div>
  );
}
