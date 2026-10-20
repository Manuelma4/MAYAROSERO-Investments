import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtPct, fmtPrice, stockPath } from "../lib/format";
import { STATIC } from "../lib/snapshot";
import type { PredictionsResult, RankedItem } from "../lib/types";
import { ForecastPanel } from "../components/Forecast";
import { Hint } from "../components/Hint";
import { Badge, Card, ErrorBox, Field, Spinner } from "../components/ui";

const HORIZONS = [{ h: 1, label: "Tomorrow" }, { h: 5, label: "1 week" }, { h: 21, label: "1 month" }];

function Row({ it, side, horizon }: { it: RankedItem; side: "up" | "down"; horizon: number }) {
  const [open, setOpen] = useState(false);
  const p = side === "up" ? it.p_outperform : it.p_underperform;
  return (
    <li className={`pred-row ${open ? "open" : ""}`}>
      <button className="pred-row-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="pr-sym">{it.symbol}</span>
        <span className="pr-name"><strong>{it.name}</strong><span className="muted small">{it.reason}</span></span>
        <span className="pr-num"><span className={side === "up" ? "up" : "down"}>{side === "up" ? `Top ${(11 - it.decile) * 10}%` : `Bottom ${it.decile * 10}%`}</span><span className="muted small">{fmtPct(p * 100, 0, false)} chance · {fmtPrice(it.price)}</span></span>
      </button>
      {open && (
        <div className="pred-detail">
          <ForecastPanel symbol={it.symbol} horizon={horizon} />
          <Link className="link" to={stockPath(it.symbol)}>Open stock page</Link>
        </div>
      )}
    </li>
  );
}

export default function Predict() {
  const [horizon, setHorizon] = useState(5);
  const [count, setCount] = useState(10);
  const [dir, setDir] = useState<"both" | "up" | "down">("both");
  const [universe, setUniverse] = useState<"us" | "sp500" | "custom">("us");
  const [custom, setCustom] = useState("");
  const [res, setRes] = useState<PredictionsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const req = useRef(0);

  const run = async (h = horizon, u = universe) => {
    const id = ++req.current;
    setBusy(true); setErr(null);
    try {
      const r = u === "us" ? await api.predictions(h)
        : await api.predictionsCustom({ horizon: h, universe: u, symbols: custom.split(/[,\s]+/).filter(Boolean) });
      if (id === req.current) setRes(r);
    } catch (e) { if (id === req.current) setErr((e as Error).message); } finally { if (id === req.current) setBusy(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(horizon, universe === "us" ? "us" : universe); }, [horizon]);

  const items = res?.items ?? [];
  const risers = items.slice(0, count);
  const fallers = [...items].reverse().slice(0, count);
  const v = res?.validation;

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Predictions · ranked {res ? `on ${res.as_of}` : "daily"} · {res?.universe_size ?? "~130"} stocks</p>
        <h1 className="display">Predict</h1>
        <p className="muted lead">Which stocks are likely to do better, or worse, than the others over the coming days. A machine-learning model ranks them every day, the way quant funds do. Tap a stock to see its simulated price range.</p>
        <div className="segmented" role="radiogroup" aria-label="Time horizon">
          {HORIZONS.map((o) => <button key={o.h} role="radio" aria-checked={horizon === o.h} className={horizon === o.h ? "active" : ""} onClick={() => setHorizon(o.h)}>{o.label}</button>)}
        </div>
      </section>

      <details className="customize">
        <summary>Customize<span className="muted small"> · {count} per list · {dir === "both" ? "rises and falls" : dir === "up" ? "rises only" : "falls only"} · {universe === "us" ? "US stocks" : universe === "sp500" ? "S&P 500" : "my list"}</span></summary>
        <form className="form" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <Field label="Stocks to show"><select id="pr-count" value={count} onChange={(e) => setCount(Number(e.target.value))}>{[5, 10, 20, 50].map((n) => <option key={n}>{n}</option>)}</select></Field>
          <Field label="Direction"><select id="pr-dir" value={dir} onChange={(e) => setDir(e.target.value as typeof dir)}><option value="both">Rises and falls</option><option value="up">Rises only</option><option value="down">Falls only</option></select></Field>
          <Field label="Market"><select id="pr-uni" value={universe} onChange={(e) => setUniverse(e.target.value as typeof universe)}><option value="us">US stocks (default)</option><option value="sp500">S&amp;P 500 only</option><option value="custom">My own list</option></select></Field>
          {universe === "custom" && <Field label="Tickers (20 or more)" wide><input id="pr-syms" value={custom} onChange={(e) => setCustom(e.target.value.toUpperCase())} placeholder="AAPL, MSFT, NVDA, …" /></Field>}
          <button className="btn primary" disabled={busy || (STATIC && universe !== "us")}>{busy ? <><Spinner /> Ranking</> : "Update"}</button>
        </form>
        <ul className="hint-list muted small">
          <li><strong>Tomorrow / 1 week / 1 month:</strong> how far ahead the ranking looks. The 1-week ranking has shown the clearest edge so far.</li>
          <li><strong>Rises / falls:</strong> stocks expected to beat the others (ideas to buy) and to lag them (ideas to avoid or short).</li>
          <li><strong>My own list:</strong> rank any group of at least 20 US stocks against each other. Takes about 30 seconds.</li>
        </ul>
      </details>
      <ErrorBox error={err} />
      {!res && busy && <div className="empty"><Spinner /> Loading today's ranking…</div>}

      {res && v && (
        <Card title={<>How good is this ranking? {v.has_edge ? <Badge tone="up">Small real edge</Badge> : <Badge>Weak signal</Badge>}
          <Hint>Measured on years of past data the model never saw. Quant funds judge short-term models by whether their top picks beat their bottom picks; a small consistent gap is valuable, a big one is usually a mistake. Probabilities are calibrated: 52% means 52 of 100 similar past cases beat the typical stock.</Hint></>}>
          <p className="ai-summary">{res.edge_sentence}</p>
          <p className="muted small">{res.quality_sentence}</p>
        </Card>
      )}

      {res && (
        <div className="grid-2">
          {dir !== "down" && (
            <Card title={<>Expected to beat the others · {res.horizon_label}<Hint>"Top 10%" means the model ranks this stock among the best tenth of the list. The "chance" is how often similar past cases beat the typical stock: edges are small (a few points above 50%) but add up across many stocks and weeks.</Hint></>}>
              <ul className="pred-list">{risers.map((it) => <Row key={it.symbol} it={it} side="up" horizon={res.horizon} />)}</ul>
            </Card>
          )}
          {dir !== "up" && (
            <Card title={<>Expected to lag · {res.horizon_label}<Hint>The percentage is the chance this stock does worse than the typical stock. Useful to avoid, or as short ideas for experienced investors.</Hint></>}>
              <ul className="pred-list">{fallers.map((it) => <Row key={it.symbol} it={it} side="down" horizon={res.horizon} />)}</ul>
            </Card>
          )}
        </div>
      )}
      <p className="caveat"><strong>How to read this page.</strong> Rankings compare stocks with each other; they don't predict whether the whole market goes up. Edges this size pay off across many stocks and many weeks, not on a single trade. Use them alongside the monthly picks and stop-losses. Research, not advice.</p>
    </div>
  );
}
