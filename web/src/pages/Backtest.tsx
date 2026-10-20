import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { fmtDate, fmtDay, fmtNum, fmtPct, fmtPrice, tone } from "../lib/format";
import type { BacktestResult, StrategyInfo } from "../lib/types";
import { LinesChart, PriceChart, SERIES, downColor, upColor, type Marker } from "../components/charts";
import { MarketPicker, type MarketSel } from "../components/MarketPicker";
import { Card, Empty, ErrorBox, Field, Spinner, Stat } from "../components/ui";
import { Hint } from "../components/Hint";

// Plain names for the setup parameters (the engine's keys stay as they are).
const PARAM_LABEL: Record<string, string> = {
  swing: "Swing size", ema: "Average (EMA)", atr: "Range period (ATR)", buffer_atr: "Stop buffer (× ATR)", rr: "Target (× risk)", max_risk_atr: "Max stop (× ATR)",
  fast: "Fast average", slow: "Slow average", trend: "Trend average", rsi: "RSI period", atr_stop: "Stop (× ATR)",
  lookback: "Range length", max_width_atr: "Max range (× ATR)", min_volume_ratio: "Min volume (× normal)", min_rr: "Min target (× risk)",
};
const SETUP_NAME: Record<string, string> = { dow_pullback: "Trend pullback", ema_cross_rsi: "Moving-average cross", wyckoff_spring: "Range breakout (Wyckoff)" };
const label = (k: string) => PARAM_LABEL[k] ?? k.replace(/_/g, " ");

export default function Backtest() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [sel, setSel] = useState<MarketSel>({ provider: "yahoo", exchange: "binance", symbol: "^GSPC", timeframe: "1d" });
  const [strategy, setStrategy] = useState("dow_pullback");
  const [params, setParams] = useState<Record<string, string>>({});
  const [start, setStart] = useState("2015-01-01");
  const [risk, setRisk] = useState("1");
  const [fee, setFee] = useState("0.1");
  const [allowShort, setAllowShort] = useState(true);
  const [res, setRes] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.strategies().then(setStrategies).catch((e) => setError(`The list of setups could not be loaded. ${(e as Error).message}`)); }, []);
  const current = strategies.find((s) => s.name === strategy);
  useEffect(() => {
    if (current) setParams(Object.fromEntries(Object.entries(current.defaults).map(([k, v]) => [k, String(v)])));
  }, [current]);

  const run = async () => {
    setLoading(true); setError(null);
    try {
      setRes(await api.backtest({
        ...sel, start: start || undefined, strategy,
        params: Object.fromEntries(Object.entries(params).map(([k, v]) => [k, Number(v)])),
        risk_per_trade: Number(risk) / 100, fee: Number(fee) / 100, allow_short: allowShort,
      }));
    } catch (e) { setError(`The backtest could not run. ${(e as Error).message}`); } finally { setLoading(false); }
  };

  // Show a result immediately with the default setup; the form is for customizing.
  const ranOnce = useRef(false);
  useEffect(() => {
    if (!ranOnce.current && current && Object.keys(params).length) { ranOnce.current = true; run(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const markers = useMemo<Marker[]>(() => (res?.trades ?? []).flatMap((t) => [
    { time: t.entry_time, position: t.side === "long" ? "belowBar" : "aboveBar", color: t.side === "long" ? upColor() : downColor(),
      shape: t.side === "long" ? "arrowUp" : "arrowDown", text: t.side === "long" ? "L" : "S" } as Marker,
    { time: t.exit_time, position: "aboveBar", color: t.pnl >= 0 ? upColor() : downColor(), shape: "circle", text: `${t.R >= 0 ? "+" : ""}${t.R.toFixed(1)}R` } as Marker,
  ]), [res]);
  const curves = useMemo(() => res ? [
    { data: res.equity, color: SERIES.ema20, title: "Strategy" },
    { data: res.buy_hold, color: SERIES.band, dashed: true, title: "Buy & hold" },
  ] : [], [res]);

  const s = res?.stats as Record<string, number> | undefined;

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Backtest · {sel.symbol} · {SETUP_NAME[strategy] ?? strategy} · since {fmtDay(start)}</p>
        <h1 className="display">Backtest</h1>
        <p className="muted lead">How a trading setup would have done on past prices. A result is shown right away; open Customize to try another market, period or setup.
          <Hint term="look-ahead">Realistic on purpose: each order fills at the next candle (no peeking at the future), and fees and slippage are included. Past results do not guarantee future ones.</Hint></p>
      </section>
      <details className="customize">
        <summary>Customize<span className="muted small"> · {sel.symbol} · {sel.timeframe} · {SETUP_NAME[strategy] ?? strategy} · {risk}% risk per trade{allowShort ? " · longs and shorts" : " · longs only"}</span></summary>
        <form className="form" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <MarketPicker value={sel} onChange={setSel} />
          <Field label="From"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Setup">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.map((x) => <option key={x.name} value={x.name}>{SETUP_NAME[x.name] ?? x.name}</option>)}
            </select>
          </Field>
          <Field label="Risk per trade %"><input type="number" step="0.1" min="0.1" max="20" value={risk} onChange={(e) => setRisk(e.target.value)} /></Field>
          <Field label="Fee %"><input type="number" step="0.01" min="0" value={fee} onChange={(e) => setFee(e.target.value)} /></Field>
          <label className="check"><input type="checkbox" checked={allowShort} onChange={(e) => setAllowShort(e.target.checked)} /> Allow shorts
            <Hint>Shorts are bets on a fall: they profit when the price drops. Untick to test buying only.</Hint></label>
          <button className="btn primary" disabled={loading}>{loading ? <Spinner /> : "Update"}</button>
        </form>
        {current && (
          <div className="params">
            <p className="muted small">{current.description}</p>
            <div className="form">
              {Object.keys(current.defaults).map((k) => (
                <Field key={k} label={label(k)}><input type="number" step="any" value={params[k] ?? ""} onChange={(e) => setParams({ ...params, [k]: e.target.value })} /></Field>))}
            </div>
          </div>
        )}
        <ul className="hint-list muted small">
          <li><strong>Risk per trade:</strong> the share of the account lost if a trade hits its stop-loss. 1% is a common, careful choice.</li>
          <li><strong>Fee:</strong> the broker cost per trade, as a % of the amount traded.</li>
          <li><strong>Setup settings:</strong> fine-tuning for the chosen setup. The defaults are a sensible start.</li>
        </ul>
      </details>
      <ErrorBox error={error} />
      {loading && !res && <div className="empty"><Spinner /> Replaying the setup on past prices…</div>}

      {res && s && (
        <>
          <p className={`verdict-line ${s["total_return_%"] > s["buy_hold_return_%"] ? "" : "behind"}`}>
            {s["total_return_%"] > s["buy_hold_return_%"]
              ? <>This setup made <strong className={tone(s["total_return_%"])}>{fmtPct(s["total_return_%"])}</strong>, more than simply buying and holding (<strong>{fmtPct(s["buy_hold_return_%"])}</strong>).</>
              : <>This setup made <strong className={tone(s["total_return_%"])}>{fmtPct(s["total_return_%"])}</strong>, less than simply buying and holding (<strong>{fmtPct(s["buy_hold_return_%"])}</strong>). On this market, holding would have been better.</>}
          </p>
          <div className="stats">
            <Stat label="Total return" value={fmtPct(s["total_return_%"])} tone={tone(s["total_return_%"])} hint="Gain or loss of the account over the whole test, trading this setup." />
            <Stat label="Buy & hold" value={fmtPct(s["buy_hold_return_%"])} tone={tone(s["buy_hold_return_%"])} hint="What you would have made by buying at the start and doing nothing. The bar to beat." />
            <Stat label="Per year" value={fmtPct(s["cagr_%"])} tone={tone(s["cagr_%"])} hint="CAGR: the average yearly growth rate over the test." term="cagr" />
            <Stat label="Worst drop" value={fmtPct(s["max_drawdown_%"])} tone="down" term="drawdown" hint="Max drawdown: the biggest fall from a peak before recovering. Tells you how painful the bad patch was." />
            <Stat label="Sharpe" term="sharpe" value={fmtNum(s.sharpe)} hint="Return per unit of risk. Below 0.5 is weak, around 1 is good, above 2 is rare." />
            <Stat label="Trades" value={s.trades} hint="How many trades the setup took. Fewer than about 30 makes the result unreliable." />
            <Stat label="Win rate" term="win-rate" value={fmtPct(s["win_rate_%"], 1, false)} hint="Share of trades that made money. A setup can win less than half the time and still profit if winners are bigger than losers." />
            <Stat label="Profit factor" value={fmtNum(s.profit_factor)} hint="Total gains ÷ total losses. Above 1 = profitable; 1.5+ is solid." />
            <Stat label="Expectancy" term="expectancy" value={`${fmtNum(s.expectancy_R, 2)} R`} tone={tone(s.expectancy_R)} hint="Average result per trade in units of risk (R). +0.3 R means each trade made 0.3 times what it risked, on average." />
          </div>
          <Card title={<>Equity curve<Hint>The account value over time trading the setup (blue) versus simply holding (dashed). Log scale: equal % moves look equal.</Hint></>}><LinesChart series={curves} log /></Card>
          <Card title={<>Trades on chart<Hint>Arrows mark entries (L = long, a bet on a rise; S = short, a bet on a fall). Dots mark exits with the result in R: +2.0R = won twice the risk, −1.0R = lost the risk.</Hint></>}><PriceChart candles={res.candles} markers={markers} height={420} /></Card>
          <Card title={`Trades (${res.trades.length})`}>
            {res.trades.length ? (
              <div className="table-wrap"><table>
                <thead><tr><th>Entry</th><th>Side</th><th>Entry price</th><th>Exit</th><th>Exit price</th><th>Reason</th><th>Bars</th><th>R</th><th>PnL</th></tr></thead>
                <tbody>{[...res.trades].reverse().map((t, i) => (
                  <tr key={i}><td>{fmtDate(t.entry_time)}</td><td className={t.side === "long" ? "up" : "down"}>{t.side}</td>
                    <td>{fmtPrice(t.entry)}</td><td>{fmtDate(t.exit_time)}</td><td>{fmtPrice(t.exit)}</td><td>{t.reason}</td>
                    <td>{t.bars}</td><td className={tone(t.R)}>{t.R.toFixed(2)}</td><td className={tone(t.pnl)}>{fmtPrice(t.pnl)}</td></tr>))}
                </tbody></table></div>
            ) : <Empty>No trades: the setup never triggered on this history.</Empty>}
          </Card>
        </>
      )}
    </div>
  );
}
