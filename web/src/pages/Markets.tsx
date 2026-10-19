import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtNum, fmtPrice } from "../lib/format";
import type { ChartData } from "../lib/types";
import { LinesChart, PriceChart, type Marker, type Overlay } from "../components/charts";
import { MarketPicker, PRESETS, type MarketSel } from "../components/MarketPicker";
import { Badge, Card, ErrorBox, Spinner, Stat } from "../components/ui";

const TREND = { 1: ["Uptrend", "up"], [-1]: ["Downtrend", "down"], 0: ["Range", ""] } as const;

export default function Markets() {
  const [sel, setSel] = useState<MarketSel>(PRESETS[0].sel);
  const [data, setData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState({ ema: true, bb: false, patterns: true, pivots: true });

  const load = useCallback(async (s: MarketSel) => {
    setLoading(true); setError(null);
    try { setData(await api.chart({ ...s, limit: 500 })); } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(PRESETS[0].sel); }, [load]);

  const overlays = useMemo<Overlay[]>(() => {
    if (!data) return [];
    const o: Overlay[] = [];
    if (show.ema) o.push(
      { data: data.overlays.ema20, color: "#60a5fa", title: "EMA20" },
      { data: data.overlays.ema50, color: "#f59e0b", title: "EMA50" },
      { data: data.overlays.ema200, color: "#a78bfa", width: 2, title: "EMA200" });
    if (show.bb) o.push(
      { data: data.overlays.bb_upper, color: "#64748b", dashed: true },
      { data: data.overlays.bb_lower, color: "#64748b", dashed: true });
    return o;
  }, [data, show]);

  const markers = useMemo<Marker[]>(() => {
    if (!data) return [];
    const m: Marker[] = [];
    // Only recent patterns, labelled with initials, so the chart stays readable.
    const recent = data.candles.length > 120 ? data.candles[data.candles.length - 120].time : 0;
    const initials = (s: string) => s.split("_").map((w) => w[0].toUpperCase()).join("");
    if (show.patterns) for (const p of data.patterns) if (p.time >= recent) m.push({
      time: p.time, position: p.kind === "bull" ? "belowBar" : "aboveBar", color: p.kind === "bull" ? "#34d399" : "#f87171",
      shape: p.kind === "bull" ? "arrowUp" : "arrowDown", text: initials(p.label),
    });
    if (show.pivots) for (const p of data.pivots) m.push({
      time: p.time, position: p.kind === "H" ? "aboveBar" : "belowBar", color: "#94a3b8", shape: "circle",
    });
    return m;
  }, [data, show]);

  const rsiSeries = useMemo<Overlay[]>(() => data ? [{ data: data.rsi, color: "#60a5fa", title: "RSI 14" }] : [], [data]);
  const a = data?.analysis;
  const [trendLabel, trendTone] = a ? TREND[a.trend] : ["–", ""];

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Charts</h1><p className="muted">Interactive charts with market structure: Dow trend, Wyckoff ranges, Elliott impulses and candlestick patterns (last 120 bars: H hammer, BE bullish / bearish engulfing, MS/ES morning/evening star, SS shooting star).</p></div>
      </div>
      <Card>
        <form className="form" onSubmit={(e) => { e.preventDefault(); load(sel); }}>
          <MarketPicker value={sel} onChange={setSel} />
          <button className="btn primary" disabled={loading}>{loading ? <Spinner /> : "Load"}</button>
        </form>
        <div className="chips">
          {PRESETS.map((p) => (
            <button key={p.label} className={`chip btn-chip ${p.sel.symbol === data?.symbol ? "active" : ""}`}
              onClick={() => { setSel(p.sel); load(p.sel); }}>{p.label}</button>))}
        </div>
      </Card>
      <ErrorBox error={error} />

      {data && a && (
        <div className="grid-main">
          <Card title={<>{data.symbol} <span className="muted">{data.timeframe}</span></>} actions={
            <div className="toggles">
              {(Object.keys(show) as (keyof typeof show)[]).map((k) => (
                <label key={k}><input type="checkbox" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} /> {k === "bb" ? "Bollinger" : k}</label>))}
            </div>}>
            <PriceChart candles={data.candles} overlays={overlays} markers={markers} />
            <LinesChart series={rsiSeries} height={140} />
          </Card>
          <Card title="Structure">
            <div className="stats tight">
              <Stat label="Last" value={fmtPrice(a.close)} />
              <Stat label="Dow trend" value={trendLabel} tone={trendTone} />
              <Stat label="RSI 14" value={fmtNum(a.rsi, 1)} tone={a.rsi > 70 ? "down" : a.rsi < 30 ? "up" : ""} hint="Above 70 overbought, below 30 oversold" />
              <Stat label="ATR" value={`${fmtNum(a.atr_pct, 2)}%`} hint="Average true range, as % of price" />
            </div>
            <dl className="kv">
              <dt>Swing high / low</dt><dd>{fmtPrice(a.swings.swing_high)} / {fmtPrice(a.swings.swing_low)}</dd>
              <dt>EMA 20 / 50 / 200</dt><dd>{fmtPrice(a.ema["20"])} / {fmtPrice(a.ema["50"])} / {fmtPrice(a.ema["200"])}</dd>
              <dt>Price vs EMA200</dt><dd className={a.close > a.ema["200"] ? "up" : "down"}>{a.close > a.ema["200"] ? "Above" : "Below"}</dd>
              <dt>MACD histogram</dt><dd className={a.macd_hist > 0 ? "up" : "down"}>{fmtNum(a.macd_hist, 4)}</dd>
              <dt>Wyckoff range</dt><dd>{fmtPrice(a.wyckoff_range.support)} – {fmtPrice(a.wyckoff_range.resistance)} {a.wyckoff_range.tight ? <Badge>tight range</Badge> : <Badge>wide / trending</Badge>}</dd>
              <dt>Recent candles</dt><dd>{a.recent_patterns.length ? a.recent_patterns.map((p) => <Badge key={p.time + p.pattern}>{p.pattern.replace(/_/g, " ")}</Badge>) : "none"}</dd>
              <dt>Elliott</dt><dd>{a.elliott ? <>Valid {a.elliott.direction} impulse {a.elliott.start.slice(0, 10)} → {a.elliott.end.slice(0, 10)} (w3/w1 {fmtNum(a.elliott.wave3_extension, 2)})</> : "No rule-valid 5-wave impulse recently"}</dd>
            </dl>
          </Card>
        </div>
      )}
    </div>
  );
}
