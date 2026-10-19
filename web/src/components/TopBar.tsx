import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fmtPct, fmtTime } from "../lib/format";
import { useLive } from "../lib/live";
import { MARKETS, STOCKS } from "../lib/markets";
import { BrandMark } from "./Brand";

const ALL = [...MARKETS, ...STOCKS];

function SymbolSearch() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const matches = q
    ? ALL.filter((m) => m.symbol.toLowerCase().includes(q.toLowerCase()) || m.name.toLowerCase().includes(q.toLowerCase())).slice(0, 7)
    : [];
  const go = (symbol: string) => { nav(`/charts?symbol=${encodeURIComponent(symbol)}`); setQ(""); setOpen(false); };
  return (
    <form className="search" role="search" onSubmit={(e) => { e.preventDefault(); if (q.trim()) go(matches[0]?.symbol ?? q.trim().toUpperCase()); }}>
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.8" /><path d="M16 16l4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
      <input value={q} placeholder="Search a stock, index or crypto (AAPL, ^GSPC, BTC/USDT)" aria-label="Search symbol"
        onChange={(e) => { setQ(e.target.value); setOpen(true); }} onBlur={() => setTimeout(() => setOpen(false), 150)} onFocus={() => setOpen(true)} />
      {open && matches.length > 0 && (
        <ul className="search-pop">
          {matches.map((m) => (
            <li key={m.symbol}><button type="button" onMouseDown={() => go(m.symbol)}>
              <strong>{m.symbol}</strong><span className="muted">{m.name}</span><span className="muted small">{m.group}</span>
            </button></li>))}
        </ul>
      )}
    </form>
  );
}

function Bell() {
  const { events, unread, markRead } = useLive();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div className="bell-wrap" ref={ref}>
      <button className="icon-btn" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} onClick={() => { setOpen(!open); if (!open) markRead(); }}>
        <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6zM10 19a2 2 0 0 0 4 0" /></svg>
        {unread > 0 && <span className="bell-count">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-pop">
          <div className="bell-head"><strong>Notifications</strong><Link to="/alerts" onClick={() => setOpen(false)}>View all</Link></div>
          {events.length ? (
            <ul>
              {events.slice(0, 8).map((e) => (
                <li key={e.id} className={e.type === "move" ? (e.direction === "SURGE" ? "up" : "down") : e.side === "long" ? "up" : "down"}>
                  <span className="bell-dot" />
                  <div>
                    <strong>{e.symbol}</strong>{" "}
                    {e.type === "move" ? <>{e.direction === "SURGE" ? "surged" : "dropped"} {fmtPct(e.move_pct, 2)}</> : <>{e.side} setup · {e.strategy}</>}
                    <div className="muted small">{fmtTime(e.time)}</div>
                  </div>
                </li>))}
            </ul>
          ) : <p className="muted small" style={{ padding: 16 }}>No notifications yet.</p>}
        </div>
      )}
    </div>
  );
}

export function TopBar() {
  const { connected, status } = useLive();
  return (
    <header className="topbar">
      <Link to="/" className="topbar-brand" aria-label="Home"><BrandMark size={30} /></Link>
      <SymbolSearch />
      <div className="topbar-right">
        <span className={`live-pill ${connected ? "on" : ""}`} title={connected ? "Real-time connection open" : "Reconnecting…"}>
          <span className="dot" />{connected ? (status?.running ? "Live" : "Connected") : "Offline"}
        </span>
        <Bell />
      </div>
    </header>
  );
}
