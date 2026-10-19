import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtNum, fmtPct, fmtPrice, fmtTime, tone } from "../lib/format";
import type { LiveEvent, PaperState } from "../lib/types";
import { useLive } from "../lib/live";
import { Badge, Card, Empty, ErrorBox, Spinner, Stat } from "../components/ui";

function MoveRow({ e }: { e: LiveEvent }) {
  const up = e.direction === "SURGE";
  return (
    <li className={`feed-row ${up ? "up" : "down"}`}>
      <span className="feed-icon" aria-hidden>{up ? "▲" : "▼"}</span>
      <div className="feed-main">
        <strong>{e.symbol}</strong>
        <span className="muted">{fmtTime(e.time)}</span>
      </div>
      <div className="feed-num">
        <span className={tone(e.move_pct)}>{fmtPct(e.move_pct, 2)}</span>
        <span className="muted small">z {fmtNum(e.zscore, 1)} · vol {e.volume_ratio ? `${fmtNum(e.volume_ratio, 1)}x` : "–"}</span>
      </div>
    </li>
  );
}

function SignalRow({ e }: { e: LiveEvent }) {
  const long = e.side === "long";
  const rr = e.target && e.stop ? Math.abs(e.target - e.price) / Math.abs(e.price - e.stop) : null;
  return (
    <li className={`feed-row ${long ? "up" : "down"}`}>
      <Badge tone={long ? "up" : "down"}>{long ? "LONG" : "SHORT"}</Badge>
      <div className="feed-main">
        <strong>{e.symbol} <span className="muted small">{e.timeframe}</span></strong>
        <span className="muted small">{e.strategy} · {fmtTime(e.time)}</span>
      </div>
      <div className="feed-num">
        <span>{fmtPrice(e.price)}</span>
        <span className="muted small">SL {fmtPrice(e.stop)} · TP {fmtPrice(e.target ?? null)}{rr ? ` · ${rr.toFixed(1)}R` : ""}</span>
      </div>
    </li>
  );
}

export default function Live() {
  const { events, status, setStatus, connected } = useLive();
  const [paper, setPaper] = useState<PaperState | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.paper().then(setPaper).catch(() => undefined);
    load();
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, [status?.scans]);

  const act = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name); setError(null);
    try { await fn(); setStatus(await api.liveStatus()); } catch (e) { setError((e as Error).message); } finally { setBusy(null); }
  };

  const moves = events.filter((e) => e.type === "move");
  const signals = events.filter((e) => e.type === "signal");

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <p className="muted">Real-time notifications: sudden surges and crashes, and your setups triggering. Also delivered to your browser, email and WhatsApp.</p>
        </div>
        <div className="row gap">
          <span className={`live-pill ${connected ? "on" : ""}`}><span className="dot" />{connected ? "Connected" : "Reconnecting"}</span>
          {status?.running
            ? <button className="btn" disabled={!!busy} onClick={() => act("stop", api.liveStop)}>Stop engine</button>
            : <button className="btn primary" disabled={!!busy} onClick={() => act("start", api.liveStart)}>Start engine</button>}
          <button className="btn" disabled={!!busy} onClick={() => act("scan", api.liveScan)}>
            {busy === "scan" ? <Spinner /> : "Scan now"}
          </button>
        </div>
      </div>
      <ErrorBox error={error ?? status?.last_error ?? null} />

      <div className="stats">
        <Stat label="Engine" value={status?.running ? "Running" : "Stopped"} tone={status?.running ? "up" : ""} />
        <Stat label="Poll interval" value={status ? `${status.poll_seconds}s` : "–"} />
        <Stat label="Scans" value={status?.scans ?? "–"} />
        <Stat label="Last scan" value={status?.last_scan ? fmtTime(status.last_scan) : "–"} />
        <Stat label="Setups watched" value={status?.watchlist.length ?? "–"} />
        <Stat label="Alerts via" value={status?.notifiers.join(", ") || "–"} />
      </div>

      <div className="grid-2">
        <Card title={<>Big movers <Badge>{moves.length}</Badge></>}>
          {status && !status.movers_enabled && <p className="muted small">Movers detection is disabled in the config (movers.enabled).</p>}
          {moves.length ? <ul className="feed">{moves.slice(0, 60).map((e) => <MoveRow key={e.id} e={e} />)}</ul>
            : <Empty>No abnormal moves yet. They appear here the moment a stock or coin surges or crashes.</Empty>}
        </Card>
        <Card title={<>Setup signals <Badge>{signals.length}</Badge></>}>
          {signals.length ? <ul className="feed">{signals.slice(0, 60).map((e) => <SignalRow key={e.id} e={e} />)}</ul>
            : <Empty>No setup has triggered yet on the watchlist.</Empty>}
        </Card>
      </div>

      {paper?.enabled && (
        <Card title="Paper trading" actions={<span className="muted">Cash {fmtPrice(paper.cash)}</span>}>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Strategy</th><th>Side</th><th>Entry</th><th>Stop</th><th>Target</th><th>Opened</th></tr></thead>
              <tbody>
                {paper.positions.length ? paper.positions.map((p) => (
                  <tr key={`${p.symbol}${p.strategy}`}>
                    <td>{p.symbol}</td><td>{p.strategy}</td><td className={p.side === "long" ? "up" : "down"}>{p.side}</td>
                    <td>{fmtPrice(p.entry)}</td><td>{fmtPrice(p.stop)}</td><td>{fmtPrice(p.target)}</td><td>{fmtTime(p.entry_time)}</td>
                  </tr>)) : <tr><td colSpan={7} className="muted">No open positions</td></tr>}
              </tbody>
            </table>
          </div>
          {paper.history.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Closed</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Reason</th><th>PnL</th></tr></thead>
                <tbody>{paper.history.slice(0, 50).map((h, i) => (
                  <tr key={i}><td>{fmtTime(h.exit_time)}</td><td>{h.symbol}</td><td>{h.side}</td><td>{fmtPrice(h.entry)}</td>
                    <td>{fmtPrice(h.exit)}</td><td>{h.reason}</td><td className={tone(h.pnl)}>{fmtPrice(h.pnl)}</td></tr>))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {status && status.watchlist.length > 0 && (
        <Card title="Watchlist">
          <div className="chips">
            {status.watchlist.map((w) => (
              <span className="chip" key={`${w.symbol}${w.timeframe}`} title={w.strategies.join(", ")}>
                {w.symbol} <span className="muted">{w.timeframe}</span>
              </span>))}
          </div>
        </Card>
      )}
    </div>
  );
}
