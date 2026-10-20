import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { STATIC } from "../lib/snapshot";
import { isCrypto, marketName } from "../lib/markets";
import { api } from "../lib/api";
import { fmtNum, fmtPrice } from "../lib/format";
import { Price } from "../lib/currency";
import type { ChartData } from "../lib/types";
import { LinesChart, PriceChart, SERIES, downColor, upColor, type Marker, type Overlay } from "../components/charts";
import { MarketPicker, PRESETS, type MarketSel } from "../components/MarketPicker";
import { Badge, Card, ErrorBox, Spinner, Stat } from "../components/ui";
import { AIDesk } from "../components/AIDesk";
import { ForecastPanel } from "../components/Forecast";
import { Hint } from "../components/Hint";

const TREND = { 1: ["Uptrend", "up"], [-1]: ["Downtrend", "down"], 0: ["Range", ""] } as const;

export default function Markets() {
  const [params, setParams] = useSearchParams();
  const fromUrl = (): MarketSel => {
    const symbol = params.get("symbol");
    if (!symbol) return PRESETS[0].sel;
    const crypto = isCrypto(symbol);
    return { provider: crypto ? "ccxt" : "yahoo", exchange: "binance", symbol, timeframe: params.get("tf") ?? (crypto ? "4h" : "1d") };
  };
  const [sel, setSel] = useState<MarketSel>(fromUrl);
  const [data, setData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState({ ema: true, bb: false, patterns: true, pivots: false });

  const load = useCallback(async (s: MarketSel, silent = false) => {
    if (!silent) { setLoading(true); setError(null); }
    try { setData(await api.chart({ ...s, limit: 500 })); } catch (e) { if (!silent) setError(`The chart for ${s.symbol} could not be loaded. ${(e as Error).message}`); } finally { if (!silent) setLoading(false); }
  }, []);
  const intraday = /^[0-9]+(m|h)$/.test(sel.timeframe) && sel.timeframe !== "4h";
  // The URL (?symbol=&tf=) is the source of truth: search, presets and the form all navigate.
  const urlKey = `${params.get("symbol")}|${params.get("tf")}`;
  useEffect(() => {
    const s = fromUrl();
    setSel(s);
    load(s);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlKey]);
  const open = (s: MarketSel) => setParams({ symbol: s.symbol, tf: s.timeframe });
  // Intraday charts refresh every minute (stock data is ~15 min delayed on the free feed).
  useEffect(() => {
    if (!intraday || STATIC) return;
    const id = setInterval(() => load(fromUrl(), true), 60_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlKey, intraday]);

  const overlays = useMemo<Overlay[]>(() => {
    if (!data) return [];
    const o: Overlay[] = [];
    if (show.ema) o.push(
      { data: data.overlays.ema20, color: SERIES.ema20, title: "EMA20" },
      { data: data.overlays.ema50, color: SERIES.ema50, title: "EMA50" },
      { data: data.overlays.ema200, color: SERIES.ema200, width: 2, title: "EMA200" });
    if (data.vwap?.length) o.push({ data: data.vwap, color: "#e5c07b", width: 2, title: "VWAP" });
    if (show.bb) o.push(
      { data: data.overlays.bb_upper, color: SERIES.band, dashed: true },
      { data: data.overlays.bb_lower, color: SERIES.band, dashed: true });
    return o;
  }, [data, show]);

  const markers = useMemo<Marker[]>(() => {
    if (!data) return [];
    const m: Marker[] = [];
    // Only recent patterns, labelled with initials, so the chart stays readable.
    const recent = data.candles.length > 120 ? data.candles[data.candles.length - 120].time : 0;
    const initials = (s: string) => s.split("_").map((w) => w[0].toUpperCase()).join("");
    if (show.patterns) for (const p of data.patterns) if (p.time >= recent) m.push({
      time: p.time, position: p.kind === "bull" ? "belowBar" : "aboveBar", color: p.kind === "bull" ? upColor() : downColor(),
      shape: p.kind === "bull" ? "arrowUp" : "arrowDown", text: initials(p.label),
    });
    if (show.pivots) for (const p of data.pivots) m.push({
      time: p.time, position: p.kind === "H" ? "aboveBar" : "belowBar", color: SERIES.band, shape: "circle",
    });
    return m;
  }, [data, show]);

  const rsiSeries = useMemo<Overlay[]>(() => data ? [{ data: data.rsi, color: SERIES.ema20, title: "RSI 14" }] : [], [data]);
  const a = data?.analysis;
  const [trendLabel, trendTone] = a ? TREND[a.trend] : ["–", ""];

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Charts · {data ? `${marketName(data.symbol)} · ${data.timeframe}` : sel.symbol}</p>
        <h1 className="display">Charts</h1>
        <p className="muted lead">Any stock, index or coin on an interactive chart. The Structure panel reads the chart for you: is it trending up or down, is it stretched, and which candle patterns just appeared.
          <Hint>Letters on the chart mark candle patterns from the last 120 candles: H hammer, BE bullish or bearish engulfing, MS / ES morning or evening star, SS shooting star. Green arrows hint at a rise, red ones at a fall. Lines: EMA 20 (blue), 50 (orange) and 200 (violet) are moving averages of the price.</Hint></p>
      </section>
      <Card>
        <form className="form" onSubmit={(e) => { e.preventDefault(); if (`${sel.symbol}|${sel.timeframe}` === urlKey) load(sel); else open(sel); }}>
          <MarketPicker value={sel} onChange={setSel} />
          <button className="btn primary" disabled={loading}>{loading ? <Spinner /> : "Load"}</button>
        </form>
        <div className="chips">
          {PRESETS.map((p) => (
            <button key={p.label} className={`chip btn-chip ${p.sel.symbol === data?.symbol ? "active" : ""}`}
              onClick={() => open(p.sel)} type="button">{p.label}</button>))}
        </div>
      </Card>
      <ErrorBox error={error} />
      {loading && !data && <div className="empty"><Spinner /> Loading the chart…</div>}

      {data && a && (
        <div className="grid-main">
          <Card title={<>{marketName(data.symbol)} <span className="muted">{data.symbol !== marketName(data.symbol) && data.symbol} · {data.timeframe}</span>{intraday && !STATIC && <span className="live-pill on" title="Refreshes every minute"><span className="dot" />Live</span>}</>} actions={
            <div className="toggles">
              {(Object.keys(show) as (keyof typeof show)[]).map((k) => (
                <label key={k}><input type="checkbox" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} /> {k === "bb" ? "Bollinger" : k}</label>))}
            </div>}>
            <PriceChart candles={data.candles} overlays={overlays} markers={markers} />
            <LinesChart series={rsiSeries} height={140} />
          </Card>
          <Card title={<>Structure<Hint>An automatic reading of the chart. The quickest check: trend "Uptrend" and price above the 200-day average (EMA200) means the long-term wind is at its back.</Hint></>}>
            <div className="stats tight">
              <Stat label="Last" value={<Price v={a.close} symbol={data.symbol} alt="stack" />} hint="The latest price on this chart, in the currency it trades in (indices are in points)." />
              <Stat label="Trend" term="uptrend" value={trendLabel} tone={trendTone} hint="Uptrend = higher highs and higher lows; downtrend = the opposite; range = neither (Dow theory)." />
              <Stat label="RSI 14" term="rsi" value={fmtNum(a.rsi, 1)} tone={a.rsi > 70 ? "down" : a.rsi < 30 ? "up" : ""} hint="Momentum from 0 to 100. Above 70 = stretched after a strong rise (overbought), below 30 = stretched after a fall (oversold)." />
              <Stat label="Daily range" term="atr" value={`${fmtNum(a.atr_pct, 2)}%`} hint="ATR: how much the price typically moves in one candle, as a % of the price. Useful to place a stop-loss outside normal noise." />
            </div>
            <dl className="kv">
              <dt>Swing high / low<Hint>The last turning points: the recent peak and the recent dip.</Hint></dt><dd>{fmtPrice(a.swings.swing_high)} / {fmtPrice(a.swings.swing_low)}</dd>
              <dt>EMA 20 / 50 / 200<Hint>Average prices over the last 20, 50 and 200 candles (recent prices count more). Price above them = healthy trend.</Hint></dt><dd>{fmtPrice(a.ema["20"])} / {fmtPrice(a.ema["50"])} / {fmtPrice(a.ema["200"])}</dd>
              <dt>Price vs EMA200<Hint term="200-day-average">Above the 200-candle average = long-term uptrend; below = long-term downtrend.</Hint></dt><dd className={a.close > a.ema["200"] ? "up" : "down"}>{a.close > a.ema["200"] ? "Above" : "Below"}</dd>
              <dt>MACD histogram<Hint>Short-term momentum: positive = gaining speed upward, negative = losing speed or falling.</Hint></dt><dd className={a.macd_hist > 0 ? "up" : "down"}>{a.macd_hist > 0 ? "Positive" : "Negative"} <span className="muted">({fmtNum(a.macd_hist, 2)})</span></dd>
              <dt>Wyckoff range<Hint>The recent trading range: support (floor) and resistance (ceiling). A tight range often comes before a bigger move.</Hint></dt><dd>{fmtPrice(a.wyckoff_range.support)} – {fmtPrice(a.wyckoff_range.resistance)} {a.wyckoff_range.tight ? <Badge>tight range</Badge> : <Badge>wide / trending</Badge>}</dd>
              <dt>Recent candles<Hint>Candle patterns that often appear at turning points. One pattern alone is a weak signal.</Hint></dt><dd>{a.recent_patterns.length ? a.recent_patterns.map((p) => <Badge key={p.time + p.pattern}>{p.pattern.replace(/_/g, " ")}</Badge>) : "None"}</dd>
              <dt>AI desk</dt><dd><AIDesk symbol={data.symbol} /></dd>
              <dt>Elliott<Hint>Whether the price recently made a clean 5-wave move (Elliott wave theory). Advanced; ignore it if unsure.</Hint></dt><dd>{a.elliott ? <>Valid {a.elliott.direction} impulse {a.elliott.start.slice(0, 10)} → {a.elliott.end.slice(0, 10)} (w3/w1 {fmtNum(a.elliott.wave3_extension, 2)})</> : "No rule-valid 5-wave impulse recently"}</dd>
            </dl>
          </Card>
        </div>
      )}
      {data && (
        <Card title={<>Forecast · next 5 trading days<Hint>5,000 simulated futures built from this market's real daily moves and today's volatility (a method used by bank risk desks), plus where most shares changed hands. It shows the likely range, not a promise.</Hint></>}>
          <ForecastPanel symbol={data.symbol} horizon={5} />
        </Card>
      )}
    </div>
  );
}
