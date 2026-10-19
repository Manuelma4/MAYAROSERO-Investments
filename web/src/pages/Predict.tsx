import { useState } from "react";
import { api } from "../lib/api";
import { fmtPct, fmtPrice, fmtTime } from "../lib/format";
import type { PredictResult } from "../lib/types";
import { MarketPicker, type MarketSel } from "../components/MarketPicker";
import { Badge, Card, ErrorBox, Field, Spinner, Stat } from "../components/ui";

const ACTION_TONE = { BUY: "up", SELL: "down", HOLD: "" } as const;

function ProbBar({ p }: { p: Record<string, number> }) {
  return (
    <div className="probbar" aria-label="Probabilities">
      {(["SELL", "HOLD", "BUY"] as const).map((k) => (
        <div key={k} className={`seg ${k.toLowerCase()}`} style={{ flexBasis: `${(p[k] ?? 0) * 100}%` }} title={`${k} ${((p[k] ?? 0) * 100).toFixed(0)}%`}>
          {(p[k] ?? 0) > 0.12 ? `${k} ${((p[k] ?? 0) * 100).toFixed(0)}%` : ""}
        </div>))}
    </div>
  );
}

export default function Predict() {
  const [sel, setSel] = useState<MarketSel>({ provider: "yahoo", exchange: "binance", symbol: "AAPL, MSFT, NVDA, GOOGL, AMZN", timeframe: "1d" });
  const [horizon, setHorizon] = useState("5");
  const [start, setStart] = useState("2012-01-01");
  const [res, setRes] = useState<PredictResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true); setError(null);
    try {
      setRes(await api.predict({
        provider: sel.provider, exchange: sel.exchange, timeframe: sel.timeframe, start: start || undefined,
        symbols: sel.symbol.split(",").map((s) => s.trim()).filter(Boolean), horizon: Number(horizon),
      }));
    } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  const v = res?.validation;

  return (
    <div className="page">
      <div className="page-head"><div><h1>Predict</h1>
        <p className="muted">A machine-learning model learns from history what usually happens next, then is tested on years it never saw (walk-forward). It only claims an edge if it beats the naive baseline out of sample.</p></div></div>
      <Card>
        <form className="form" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <MarketPicker value={sel} onChange={setSel} multi />
          <Field label="History from"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Horizon (bars ahead)"><input type="number" min="1" max="100" value={horizon} onChange={(e) => setHorizon(e.target.value)} /></Field>
          <button className="btn primary" disabled={loading}>{loading ? <><Spinner /> Training…</> : "Train & predict"}</button>
        </form>
      </Card>
      <ErrorBox error={error} />

      {v && res && (
        <>
          <Card title={<>Out-of-sample validation {v.has_edge ? <Badge tone="up">Statistical edge</Badge> : <Badge tone="down">No edge: do not trade these signals</Badge>}</>}>
            <div className="stats">
              <Stat label="Accuracy" value={fmtPct(v.accuracy * 100, 1, false)} hint="Share of correct BUY/HOLD/SELL calls on unseen data" />
              <Stat label="Naive baseline" value={fmtPct(v.baseline_accuracy * 100, 1, false)} hint="Always predicting the most common outcome" />
              <Stat label="Precision (confident calls)" value={fmtPct(v.confident_precision * 100, 1, false)} hint="When the model acts, how often it is right" />
              <Stat label="Confident calls" value={v.confident_calls} />
              <Stat label="Model strategy" value={fmtPct(v["strategy_return_%"])} tone={v["strategy_return_%"] >= 0 ? "up" : "down"} hint="Gross, before costs; non-overlapping holding periods" />
              <Stat label="Buy & hold (same period)" value={fmtPct(v["buy_hold_return_%"])} tone={v["buy_hold_return_%"] >= 0 ? "up" : "down"} />
              <Stat label="Test samples" value={v.samples} />
            </div>
            <p className="muted small">Professional quant funds consider 52–56% directional accuracy with strict risk management valuable. Very high numbers usually mean overfitting.</p>
          </Card>
          <div className="pred-grid">
            {res.predictions.map((p) => (
              <Card key={p.symbol} className="pred">
                <div className="pred-head">
                  <div><strong className="pred-sym">{p.symbol}</strong><span className="muted small">{fmtPrice(p.last_close)} · {fmtTime(p.time)}</span></div>
                  <span className={`action ${ACTION_TONE[p.action]}`}>{p.action}</span>
                </div>
                <ProbBar p={p.probabilities} />
                <p className="muted small">Next {horizon} bars · confidence {fmtPct(p.confidence * 100, 0, false)}{!p.has_edge && " · model has no validated edge"}</p>
              </Card>))}
          </div>
        </>
      )}
    </div>
  );
}
