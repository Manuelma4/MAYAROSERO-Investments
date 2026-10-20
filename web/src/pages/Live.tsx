import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtListed, fmtNum, fmtPct, fmtTime, tone } from "../lib/format";
import { FxHint, Money } from "../lib/currency";
import type { LiveEvent, PaperState } from "../lib/types";
import { useLive } from "../lib/live";
import { Badge, Card, Empty, ErrorBox, Spinner, Stat } from "../components/ui";
import { Hint } from "../components/Hint";
import { MyAlerts, Watchlists } from "../components/MyAlerts";
import { alertText, earningsText } from "../lib/browserNotify";
import { fmtEarnDay } from "../lib/earnings";

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
        <span>{fmtListed(e.price, e.symbol)}</span>
        <span className="muted small">SL {fmtListed(e.stop, e.symbol)} · TP {fmtListed(e.target ?? null, e.symbol)}{rr ? ` · ${rr.toFixed(1)}R` : ""}</span>
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
  // Own alerts are fetched by type so busy days of market moves never push them out of the feed.
  const [own, setOwn] = useState<LiveEvent[]>([]);
  useEffect(() => {
    Promise.all([api.events("alert", 20), api.events("picks", 10), api.events("earnings", 10)])
      .then(([a, p, x]) => setOwn([...a, ...p, ...x])).catch(() => undefined);
  }, []);
  const fired = useMemo(() => {
    const byId = new Map([...own, ...events.filter((e) => e.type === "alert" || e.type === "picks" || e.type === "earnings")].map((e) => [e.id, e]));
    return [...byId.values()].sort((a, b) => b.id - a.id);
  }, [own, events]);
  const signals = events.filter((e) => e.type === "signal");

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Notifications · {status?.running ? "engine running" : "engine stopped"}</p>
        <h1 className="display">Alerts</h1>
        <p className="muted lead">Your price alerts and watchlists, plus real-time notifications when a stock suddenly surges or crashes. They also reach your browser, email and WhatsApp.</p>
        <div className="row gap wrap-row">
          <span className={`live-pill ${connected ? "on" : ""}`}><span className="dot" />{connected ? "Connected" : "Reconnecting"}</span>
          {status?.running
            ? <button className="btn" disabled={!!busy} onClick={() => act("stop", api.liveStop)}>Stop engine</button>
            : <button className="btn primary" disabled={!!busy} onClick={() => act("start", api.liveStart)}>Start engine</button>}
          <button className="btn" disabled={!!busy} onClick={() => act("scan", api.liveScan)}>
            {busy === "scan" ? <Spinner /> : "Scan now"}
          </button>
        </div>
      </section>
      <ErrorBox error={error ?? status?.last_error ?? null} />

      {fired.length > 0 && (
        <Card title={<>Alerts received <Badge>{fired.length}</Badge><Hint>Your own price alerts that fired, every change to the Beat-the-S&amp;P picks, and a reminder the day before a stock you hold, pick or watch publishes its results (earnings). Newest first.</Hint></>}>
          <ul className="feed">{fired.slice(0, 20).map((e) => (
            <li key={e.id} className="feed-row">
              <span className="feed-icon" aria-hidden>{e.type === "picks" ? "★" : e.type === "earnings" ? "◷" : <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3a6 6 0 0 0-6 6v4l-2 3h16l-2-3V9a6 6 0 0 0-6-6zM10 19a2 2 0 0 0 4 0" /></svg>}</span>
              {e.type === "earnings" ? <>
                <div className="feed-main"><strong>{e.symbol} reports {e.phase === "today" ? "today" : "tomorrow"}{e.date ? ` (${fmtEarnDay(e.date)})` : ""}</strong><span className="muted small">{earningsText(e)}</span></div>
                <div className="feed-num"><span className="muted small">Earnings</span><span className="muted small">{fmtTime(e.created_at)}</span></div>
              </> : e.type === "picks" ? <>
                <div className="feed-main"><strong>Beat-the-S&amp;P picks updated</strong><span className="muted small">Buy {e.buy?.join(", ") || "nothing new"} · Sell {e.sell?.join(", ") || "nothing"}</span></div>
                <div className="feed-num"><span className="muted small">{fmtTime(e.created_at)}</span></div>
              </> : <>
                <div className="feed-main"><strong>{e.symbol}</strong><span className="muted small">{alertText(e)}{e.note ? ` · ${e.note}` : ""}</span></div>
                <div className="feed-num"><span>{fmtListed(e.price, e.symbol)}</span><span className="muted small">{fmtTime(e.created_at)}</span></div>
              </>}
            </li>))}
          </ul>
        </Card>
      )}

      <div className="grid-2">
        <MyAlerts />
        <Watchlists />
      </div>

      <div className="grid-2">
        <Card title={<>Big movers <Badge>{moves.length}</Badge><Hint>Unusual moves on the markets the engine watches: "z" says how many times bigger than a normal move it is (3 = very unusual), "vol" compares volume with a normal day.</Hint></>}>
          {status && !status.movers_enabled && <p className="muted small">Movers detection is disabled in the config (movers.enabled).</p>}
          {moves.length ? <ul className="feed">{moves.slice(0, 60).map((e) => <MoveRow key={e.id} e={e} />)}</ul>
            : <Empty>No abnormal moves yet. They appear here the moment a stock or coin surges or crashes.</Empty>}
        </Card>
        <Card title={<>Setup signals <Badge>{signals.length}</Badge><Hint>A chart setup that just triggered: LONG means a possible rise, SHORT a possible fall. SL is the stop-loss, TP the target, and R how many times the risk the target could pay.</Hint></>}>
          {signals.length ? <ul className="feed">{signals.slice(0, 60).map((e) => <SignalRow key={e.id} e={e} />)}</ul>
            : <Empty>No setup has triggered yet. Signals appear here when one of the markets listed below forms a setup.</Empty>}
        </Card>
      </div>

      {paper?.enabled && (
        <Card title={<>Practice trades from signals<Hint>The engine trades its own setup signals with practice (paper) money, to show how they would do. No real money is involved.</Hint></>} actions={<span className="muted small">Cash <Money v={paper.cash} from="USD" /><FxHint from="USD" /></span>}>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Strategy</th><th>Side</th><th>Entry</th><th>Stop</th><th>Target</th><th>Opened</th></tr></thead>
              <tbody>
                {paper.positions.length ? paper.positions.map((p) => (
                  <tr key={`${p.symbol}${p.strategy}`}>
                    <td>{p.symbol}</td><td>{p.strategy}</td><td className={p.side === "long" ? "up" : "down"}>{p.side}</td>
                    <td>{fmtListed(p.entry, p.symbol)}</td><td>{fmtListed(p.stop, p.symbol)}</td><td>{fmtListed(p.target, p.symbol)}</td><td>{fmtTime(p.entry_time)}</td>
                  </tr>)) : <tr><td colSpan={7} className="muted">No open positions</td></tr>}
              </tbody>
            </table>
          </div>
          {paper.history.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Closed</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>Reason</th><th>PnL</th></tr></thead>
                <tbody>{paper.history.slice(0, 50).map((h, i) => (
                  <tr key={i}><td>{fmtTime(h.exit_time)}</td><td>{h.symbol}</td><td>{h.side}</td><td>{fmtListed(h.entry, h.symbol)}</td>
                    <td>{fmtListed(h.exit, h.symbol)}</td><td>{h.reason}</td><td className={tone(h.pnl)}><Money v={h.pnl} from="USD" digits={2} /></td></tr>))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      <section>
        <h2 className="section-title">Alert engine<Hint>The part of the app that watches prices and sends the alerts on this page. It normally starts by itself with the server.</Hint></h2>
        <div className="stats">
          <Stat label="Engine" value={status?.running ? "Running" : "Stopped"} tone={status?.running ? "up" : ""} hint="Running = prices are being watched and alerts are sent. If it is stopped, press Start engine at the top." />
          <Stat label="Checks every" value={status ? `${status.poll_seconds}s` : "–"} hint="How often the engine fetches new prices." />
          <Stat label="Scans" value={status?.scans ?? "–"} hint="How many times the engine has checked prices since the server started." />
          <Stat label="Last scan" value={status?.last_scan ? fmtTime(status.last_scan) : "–"} hint="When prices were last checked." />
          <Stat label="Setups watched" value={status?.watchlist.length ?? "–"} hint="Markets the engine checks for trading setups (listed at the bottom of this page)." />
          <Stat label="Alerts via" value={status?.notifiers.join(", ") || "–"} hint="Where alerts are delivered. 'console' means only inside this app; email and WhatsApp are set up on the server (see Settings)." />
        </div>
      </section>

      {status && status.watchlist.length > 0 && (
        <Card title={<>Markets scanned for setups<Hint>The markets and time frames (1h = hourly candles, 1d = daily) the engine checks for setup signals. Your own lists are under My watchlists above.</Hint></>}>
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
