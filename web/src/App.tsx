import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { getToken, setToken } from "./lib/api";
import { browserNotifyEnabled, browserNotifySupported, setBrowserNotify } from "./lib/browserNotify";
import Backtest from "./pages/Backtest";
import Live from "./pages/Live";
import Markets from "./pages/Markets";
import Predict from "./pages/Predict";

const NAV = [
  { to: "/alerts", label: "Alerts", icon: "M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6zM10 19a2 2 0 0 0 4 0" },
  { to: "/charts", label: "Charts", icon: "M4 19h16M6 15l4-5 3 3 5-7" },
  { to: "/predict", label: "Predict", icon: "M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z" },
  { to: "/backtest", label: "Backtest", icon: "M4 4v16h16M8 14l3-3 3 2 5-6" },
];

function Icon({ d }: { d: string }) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>;
}

export default function App() {
  const [notify, setNotify] = useState(browserNotifyEnabled());
  const [hasToken, setHasToken] = useState(!!getToken());

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden><rect width="32" height="32" rx="8" fill="var(--accent-faint)" /><path d="M5 18h5l3-8 5 14 3-6h6" stroke="var(--accent)" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          <span className="brand-name">MAYAROSERO<small>Investments</small></span>
        </div>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon d={n.icon} /><span>{n.label}</span>
            </NavLink>))}
        </nav>
        <div className="sidebar-foot">
          {browserNotifySupported() && (
            <button className={`btn small ${notify ? "on" : ""}`} onClick={async () => setNotify(await setBrowserNotify(!notify))}>
              {notify ? "Browser alerts on" : "Enable browser alerts"}
            </button>)}
          <button className="btn small ghost" onClick={() => {
            const t = prompt("API access token (leave empty to clear)", getToken() ?? "");
            if (t !== null) { setToken(t.trim() || null); setHasToken(!!t.trim()); location.reload(); }
          }}>{hasToken ? "Access token set" : "Set access token"}</button>
          <p className="disclaimer">Information only, not financial advice.</p>
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/alerts" replace />} />
          <Route path="/alerts" element={<Live />} />
          <Route path="/charts" element={<Markets />} />
          <Route path="/predict" element={<Predict />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="*" element={<Navigate to="/alerts" replace />} />
        </Routes>
      </main>
    </div>
  );
}
