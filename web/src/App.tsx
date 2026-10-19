import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { BrandLockup } from "./components/Brand";
import { TickerTape } from "./components/TickerTape";
import { TopBar } from "./components/TopBar";
import { useEffect, useState } from "react";
import { LiveProvider, useLive } from "./lib/live";
import { STATIC, snapshotMeta } from "./lib/snapshot";
import Backtest from "./pages/Backtest";
import Discover from "./pages/Discover";
import Live from "./pages/Live";
import Markets from "./pages/Markets";
import Overview from "./pages/Overview";
import Picks from "./pages/Picks";
import Predict from "./pages/Predict";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "Overview", mobile: true, icon: "M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" },
  { to: "/discover", label: "Discover", mobile: true, icon: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM15.5 8.5l-2 5-5 2 2-5z" },
  { to: "/picks", label: "Beat the S&P", short: "Picks", mobile: true, icon: "M5 19V9m7 10V5m7 14v-7" },
  { to: "/alerts", label: "Alerts", mobile: true, badge: true, icon: "M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6zM10 19a2 2 0 0 0 4 0" },
  { to: "/charts", label: "Charts", icon: "M4 19h16M6 15l4-5 3 3 5-7" },
  { to: "/predict", label: "Predict", icon: "M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z" },
  { to: "/backtest", label: "Backtest", icon: "M4 4v16h16M8 14l3-3 3 2 5-6" },
  { to: "/settings", label: "Settings", short: "More", mobile: true, icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12l2-1-1-3-2 .2-1.3-1.3L17 5l-3-1-1 2h-2L10 4 7 5l.3 1.9L6 8.2 4 8l-1 3 2 1v0l-2 1 1 3 2-.2 1.3 1.3L7 19l3 1 1-2h2l1 2 3-1-.3-1.9 1.3-1.3 2 .2 1-3z" },
];

function Icon({ d }: { d: string }) {
  return <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>;
}

function PreviewBanner() {
  const [asOf, setAsOf] = useState<string | null>(null);
  useEffect(() => { snapshotMeta().then((m) => setAsOf(m.as_of)).catch(() => undefined); }, []);
  return (
    <div className="preview-banner" role="note">
      Preview · real market data captured {asOf ? new Date(asOf).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "recently"} · live prices and alerts run on the full app
    </div>
  );
}

function Shell() {
  const { unread } = useLive();
  return (
    <div className="shell">
      <aside className="sidebar">
        <BrandLockup />
        <nav aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => `nav-item ${isActive ? "active" : ""} ${n.mobile ? "" : "desktop-only"}`}>
              <Icon d={n.icon} />
              <span className="nav-label">{n.label}</span>
              <span className="nav-short">{n.short ?? n.label}</span>
              {n.badge && unread > 0 && <span className="nav-badge">{unread > 99 ? "99+" : unread}</span>}
            </NavLink>))}
        </nav>
        <p className="disclaimer">Market information and analysis. Not financial advice.</p>
      </aside>
      <div className="main">
        {STATIC && <PreviewBanner />}
        <TopBar />
        <TickerTape />
        <main className="content">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/discover" element={<Discover />} />
            <Route path="/picks" element={<Picks />} />
            <Route path="/alerts" element={<Live />} />
            <Route path="/charts" element={<Markets />} />
            <Route path="/predict" element={<Predict />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return <LiveProvider><Shell /></LiveProvider>;
}
