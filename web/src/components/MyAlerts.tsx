import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtListed, fmtPct, fmtTime, stockPath, tone } from "../lib/format";
import { Price } from "../lib/currency";
import { useQuotes } from "../lib/quotes";
import type { AlertKind, PriceAlert, Watchlist } from "../lib/types";
import { Hint } from "./Hint";
import { Sparkline } from "./Sparkline";
import { Card, Empty, ErrorBox, Spinner } from "./ui";

const KIND_LABEL: Record<AlertKind, string> = { above: "Goes above", below: "Falls below", move: "Moves more than" };

function describe(a: PriceAlert) {
  return a.kind === "move" ? `${KIND_LABEL.move} ${a.value}% in a day` : `${KIND_LABEL[a.kind]} ${fmtListed(a.value, a.symbol)}`;
}

/** Inline form: "Tell me when SYMBOL goes above / falls below / moves X%". */
export function AlertForm({ symbol: fixed, price, onSaved }: { symbol?: string; price?: number; onSaved?: () => void }) {
  const [symbol, setSymbol] = useState(fixed ?? "");
  const [kind, setKind] = useState<AlertKind>("above");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {  // suggest a sensible level: +5% / -5% of today's price, or a 4% daily move
    if (kind === "move") setValue("4");
    else if (price) setValue((price * (kind === "above" ? 1.05 : 0.95)).toFixed(2));
    else setValue("");
  }, [kind, price]);

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const a = await api.addAlert({ symbol: (fixed ?? symbol).trim().toUpperCase(), kind, value: Number(value), note });
      setMsg({ ok: true, text: `Alert set: ${a.symbol} ${describe(a).toLowerCase()}. You'll get it here, in your browser, email and WhatsApp.` });
      setNote(""); onSaved?.();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  };

  return (
    <div className="alert-form">
      <div className="alert-form-row">
        {!fixed && <input aria-label="Symbol" placeholder="Symbol (AAPL, BTC/USDT)" value={symbol} onChange={(e) => setSymbol(e.target.value)} />}
        <select aria-label="Condition" value={kind} onChange={(e) => setKind(e.target.value as AlertKind)}>
          {(Object.keys(KIND_LABEL) as AlertKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
        </select>
        <input aria-label={kind === "move" ? "Percent" : "Price"} type="number" min="0" step="any" placeholder={kind === "move" ? "%" : "Price"} value={value} onChange={(e) => setValue(e.target.value)} />
        {kind === "move" && <span className="muted">%</span>}
        <input aria-label="Note (optional)" placeholder="Note (optional)" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
        <button className="btn primary" disabled={busy || !(Number(value) > 0) || !(fixed ?? symbol).trim()} onClick={save}>{busy ? <Spinner /> : "Set alert"}</button>
      </div>
      {msg && <p className={`small ${msg.ok ? "up" : "down"}`} role="status">{msg.text}</p>}
    </div>
  );
}

export function MyAlerts() {
  const [alerts, setAlerts] = useState<PriceAlert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.alerts().then((r) => setAlerts(r.alerts)).catch((e) => setError((e as Error).message)), []);
  useEffect(() => { load(); const id = setInterval(load, 60_000); return () => clearInterval(id); }, [load]);
  const { quotes } = useQuotes([...new Set((alerts ?? []).map((a) => a.symbol))], 60_000);

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); await load(); } catch (e) { setError((e as Error).message); }
  };

  return (
    <Card title={<>My price alerts<Hint>Pick a stock or coin and a level. The engine checks prices every few minutes and tells you once when the level is reached, then the alert switches off (press "Re-arm" to watch again). "Moves more than 4%" catches unusual days in either direction.</Hint></>}>
      <AlertForm onSaved={load} />
      <ErrorBox error={error} />
      {alerts === null ? <Spinner /> : alerts.length === 0 ? <Empty>No alerts yet. Set one above, or from any stock page.</Empty> : (
        <ul className="feed">
          {alerts.map((a) => {
            const q = quotes[a.symbol];
            return (
              <li key={a.id} className={`feed-row ${a.active ? "" : "fired"}`}>
                <span className={`alert-dot ${a.active ? "on" : ""}`} aria-hidden />
                <div className="feed-main">
                  <strong><Link className="link" to={stockPath(a.symbol)}>{a.symbol}</Link> <span className="muted small">{describe(a)}</span></strong>
                  <span className="muted small">
                    {a.active ? "Watching" : `Fired ${a.triggered_at ? fmtTime(a.triggered_at) : ""} at ${fmtListed(a.triggered_price, a.symbol)}`}
                    {a.note ? ` · ${a.note}` : ""}
                  </span>
                </div>
                <div className="feed-num">
                  <Price v={q?.price} symbol={a.symbol} alt="hover" />
                  <span className={`small ${tone(q?.change_pct)}`}>{q?.change_pct !== undefined ? fmtPct(q.change_pct, 2) : ""}</span>
                </div>
                <div className="row gap">
                  {!a.active && <button className="btn small" onClick={() => act(() => api.rearmAlert(a.id))}>Re-arm</button>}
                  <button className="btn small ghost" aria-label={`Delete alert on ${a.symbol}`} onClick={() => act(() => api.deleteAlert(a.id))}>✕</button>
                </div>
              </li>);
          })}
        </ul>
      )}
    </Card>
  );
}

function WatchlistCard({ w, onChange }: { w: Watchlist; onChange: () => void }) {
  const { quotes } = useQuotes(w.symbols, 60_000);
  const [adding, setAdding] = useState("");
  const [error, setError] = useState<string | null>(null);
  const save = async (symbols: string[]) => {
    setError(null);
    try { await api.saveWatchlist({ id: w.id, name: w.name, symbols }); onChange(); } catch (e) { setError((e as Error).message); }
  };
  return (
    <div className="watchlist">
      <div className="row between">
        <h3>{w.name} <span className="muted small">{w.symbols.length}</span></h3>
        <button className="btn small ghost" onClick={() => api.deleteWatchlist(w.id).then(onChange).catch((e) => setError((e as Error).message))}>Delete list</button>
      </div>
      <ErrorBox error={error} />
      {w.symbols.length === 0 ? <p className="muted small">Empty. Add a symbol below.</p> : (
        <ul className="feed">
          {w.symbols.map((s) => {
            const q = quotes[s];
            return (
              <li key={s} className="feed-row">
                <div className="feed-main"><strong><Link className="link" to={stockPath(s)}>{s}</Link></strong></div>
                {q?.spark && <Sparkline data={q.spark} />}
                <div className="feed-num">
                  <Price v={q?.price} symbol={s} alt="hover" />
                  <span className={`small ${tone(q?.change_pct)}`}>{q?.change_pct !== undefined ? fmtPct(q.change_pct, 2) : ""}</span>
                </div>
                <button className="btn small ghost" aria-label={`Remove ${s}`} onClick={() => save(w.symbols.filter((x) => x !== s))}>✕</button>
              </li>);
          })}
        </ul>
      )}
      <form className="row gap" onSubmit={(e) => { e.preventDefault(); if (adding.trim()) { save([...w.symbols, adding.trim().toUpperCase()]); setAdding(""); } }}>
        <input aria-label={`Add a symbol to ${w.name}`} placeholder="Add symbol" value={adding} onChange={(e) => setAdding(e.target.value)} />
        <button className="btn small" type="submit">Add</button>
      </form>
    </div>
  );
}

export function Watchlists() {
  const [lists, setLists] = useState<Watchlist[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.watchlists().then(setLists).catch((e) => setError((e as Error).message)), []);
  useEffect(() => { load(); }, [load]);
  const create = async () => {
    setError(null);
    try { await api.saveWatchlist({ name: name.trim(), symbols: [] }); setName(""); await load(); } catch (e) { setError((e as Error).message); }
  };
  return (
    <Card title={<>My watchlists<Hint>Lists of stocks you want to keep an eye on, with live prices. Tap a symbol to open its page, where you can also set a price alert.</Hint></>}>
      <ErrorBox error={error} />
      {lists === null ? <Spinner /> : lists.length === 0 && <Empty>No watchlists yet. Create one below, or use "Add to watchlist" on any stock page.</Empty>}
      <div className="watchlists">{lists?.map((w) => <WatchlistCard key={w.id} w={w} onChange={load} />)}</div>
      <form className="row gap new-list" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create(); }}>
        <input aria-label="New watchlist name" placeholder="New list name (e.g. Tech I like)" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        <button className="btn" type="submit" disabled={!name.trim()}>Create list</button>
      </form>
    </Card>
  );
}

/** Stock page: add this symbol to a watchlist (creates "My watchlist" the first time). */
export function AddToWatchlist({ symbol }: { symbol: string }) {
  const [lists, setLists] = useState<Watchlist[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { api.watchlists().then(setLists).catch(() => setLists([])); }, []);
  const inList = lists?.find((w) => w.symbols.includes(symbol));
  const add = async (w?: Watchlist) => {
    try {
      const saved = await api.saveWatchlist(w ? { ...w, symbols: [...w.symbols, symbol] } : { name: "My watchlist", symbols: [symbol] });
      setLists((prev) => [...(prev ?? []).filter((x) => x.id !== saved.id), saved]);
      setMsg(`Added to ${saved.name}`);
    } catch (e) { setMsg((e as Error).message); }
  };
  if (lists === null) return null;
  return (
    <div className="row gap">
      {inList ? <span className="badge in-list">In watchlist · {inList.name}</span>
        : lists.length <= 1 ? <button className="btn" onClick={() => add(lists[0])}>Add to watchlist</button>
        : (
          <select aria-label="Add to watchlist" value="" onChange={(e) => add(lists.find((w) => w.id === Number(e.target.value)))}>
            <option value="" disabled>Add to watchlist…</option>
            {lists.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>)}
      {msg && <span className="muted small" role="status">{msg}</span>}
    </div>
  );
}
