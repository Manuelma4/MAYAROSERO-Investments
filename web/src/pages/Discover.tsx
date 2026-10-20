import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { fmtPct, fmtPrice, stockPath } from "../lib/format";
import { useQuotes } from "../lib/quotes";
import type { Quote, Universe, UniverseStock } from "../lib/types";
import { Sparkline } from "../components/Sparkline";
import { ErrorBox, Spinner } from "../components/ui";

type Mode = "themes" | "sectors" | "regions";
const REGIONS = ["US", "Europe", "Asia", "Global"];

function avgChange(stocks: UniverseStock[], quotes: Record<string, Quote>) {
  const xs = stocks.map((s) => quotes[s.symbol]?.change_pct).filter((x): x is number => x !== undefined);
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : undefined;
}

function heat(v: number | undefined) {
  if (v === undefined) return {};
  const a = Math.min(0.55, Math.abs(v) / 4);
  return { background: `color-mix(in srgb, var(${v >= 0 ? "--up" : "--down"}) ${Math.round(a * 100)}%, var(--surface))` };
}

function StockRow({ s, q }: { s: UniverseStock; q?: Quote }) {
  return (
    <Link to={stockPath(s.symbol)} className="srow">
      <span className="avatar">{s.symbol.replace(/[-.^/].*/, "").slice(0, 4)}</span>
      <span className="srow-name"><strong>{s.name}</strong><span className="muted small">{s.symbol} · {s.industry}</span></span>
      <Sparkline data={q?.spark} width={84} height={26} className="hide-sm" />
      <span className="srow-num">
        <span className="num">{q?.price !== undefined ? fmtPrice(q.price) : <span className="skeleton-line" />}</span>
        {q?.change_pct !== undefined && <span className={`small ${q.change_pct >= 0 ? "up" : "down"}`}>{fmtPct(q.change_pct, 2)}</span>}
      </span>
    </Link>
  );
}

export default function Discover() {
  const [uni, setUni] = useState<Universe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const mode = (params.get("by") as Mode) || "themes";
  const [query, setQuery] = useState("");

  useEffect(() => { api.universe().then(setUni).catch((e) => setError(e.message)); }, []);

  const all = useMemo(() => (uni ? [...uni.stocks, ...uni.crypto] : []), [uni]);
  const groups = useMemo(() => {
    if (!uni) return [] as { key: string; stocks: UniverseStock[] }[];
    const keys = mode === "themes" ? [...uni.themes, "Crypto"] : mode === "sectors" ? [...uni.sectors, "Crypto"] : REGIONS;
    return keys.map((k) => ({
      key: k,
      stocks: all.filter((s) => (mode === "themes" ? (k === "Crypto" ? s.sector === "Crypto" : s.themes.includes(k))
        : mode === "sectors" ? s.sector === k : s.region === k)),
    })).filter((g) => g.stocks.length);
  }, [uni, all, mode]);

  const selected = params.get("g") ?? groups[0]?.key;
  const current = groups.find((g) => g.key === selected) ?? groups[0];
  const q = query.trim().toLowerCase();
  const visible = q ? all.filter((s) => s.name.toLowerCase().includes(q) || s.symbol.toLowerCase().includes(q) || s.industry.toLowerCase().includes(q)) : current?.stocks ?? [];

  // One batched request for every symbol in the universe (cached server-side), refreshed every minute.
  // Group tiles need every quote (refreshed every 5 min); the cards on screen refresh every minute.
  const { quotes: allQuotes } = useQuotes(all.map((s) => s.symbol), 300_000);
  const { quotes: onScreen } = useQuotes(visible.slice(0, 200).map((s) => s.symbol), 60_000);
  const quotes = useMemo(() => ({ ...allQuotes, ...onScreen }), [allQuotes, onScreen]);

  const setMode = (m: Mode) => setParams({ by: m });
  const setGroup = (g: string) => setParams({ by: mode, g });

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Discover</p>
        <h1 className="display">The world's leading companies</h1>
        <p className="muted lead">{uni ? `${uni.stocks.length} stocks and ${uni.crypto.length} crypto assets` : "Stocks and crypto"}, organized by theme, sector and region. Prices update live.</p>
        <div className="discover-controls">
          <div className="segmented" role="tablist">
            {(["themes", "sectors", "regions"] as Mode[]).map((m) => (
              <button key={m} role="tab" aria-selected={mode === m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>{m}</button>))}
          </div>
          <input className="filter" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by name, ticker or industry" aria-label="Filter" />
        </div>
      </section>
      <ErrorBox error={error} />
      {!uni && !error && <div className="empty"><Spinner /></div>}

      {uni && !q && (
        <div className="tiles" role="tablist" aria-label="Groups">
          {groups.map((g) => {
            const v = avgChange(g.stocks, quotes);
            return (
              <button key={g.key} role="tab" aria-selected={g.key === current?.key} className={`tile ${g.key === current?.key ? "active" : ""}`} style={heat(v)} onClick={() => setGroup(g.key)}>
                <span className="tile-name">{g.key}</span>
                <span className="tile-meta"><span className="muted small">{g.stocks.length} assets</span>{v !== undefined && <span className={v >= 0 ? "up" : "down"}>{fmtPct(v, 2)}</span>}</span>
              </button>);
          })}
        </div>
      )}

      {uni && (
        <section>
          <h2 className="section-title">{q ? `Results for "${query}" · ${visible.length}` : `${current?.key} · ${visible.length}`}</h2>
          <div className="srows">
            {visible.map((s) => <StockRow key={s.symbol} s={s} q={quotes[s.symbol]} />)}
          </div>
        </section>
      )}
    </div>
  );
}
