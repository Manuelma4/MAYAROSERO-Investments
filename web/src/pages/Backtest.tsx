import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtDate, fmtNum, fmtPct, fmtPrice, tone } from "../lib/format";
import type { BacktestResult, StrategyInfo } from "../lib/types";
import { LinesChart, PriceChart, type Marker } from "../components/charts";
import { MarketPicker, type MarketSel } from "../components/MarketPicker";
import { Card, Empty, ErrorBox, Field, Spinner, Stat } from "../components/ui";

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

  useEffect(() => { api.strategies().then(setStrategies).catch((e) => setError(e.message)); }, []);
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
    } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };

  const markers = useMemo<Marker[]>(() => (res?.trades ?? []).flatMap((t) => [
    { time: t.entry_time, position: t.side === "long" ? "belowBar" : "aboveBar", color: t.side === "long" ? "#34d399" : "#f87171",
      shape: t.side === "long" ? "arrowUp" : "arrowDown", text: t.side === "long" ? "L" : "S" } as Marker,
    { time: t.exit_time, position: "aboveBar", color: t.pnl >= 0 ? "#34d399" : "#f87171", shape: "circle", text: `${t.R >= 0 ? "+" : ""}${t.R.toFixed(1)}R` } as Marker,
  ]), [res]);
  const curves = useMemo(() => res ? [
    { data: res.equity, color: "#34d399", title: "Strategy" },
    { data: res.buy_hold, color: "#94a3b8", dashed: true, title: "Buy & hold" },
  ] : [], [res]);

  const s = res?.stats as Record<string, number> | undefined;

  return (
    <div className="page">
      <div className="page-head"><div><h1>Backtest</h1>
        <p className="muted">Test a setup on historical charts. Signals fill at the next bar's open, stop is assumed before target, fees and slippage included.</p></div></div>
      <Card>
        <form className="form" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <MarketPicker value={sel} onChange={setSel} />
          <Field label="From"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Strategy">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}
            </select>
          </Field>
          <Field label="Risk / trade %"><input type="number" step="0.1" min="0.1" max="20" value={risk} onChange={(e) => setRisk(e.target.value)} /></Field>
          <Field label="Fee %"><input type="number" step="0.01" min="0" value={fee} onChange={(e) => setFee(e.target.value)} /></Field>
          <label className="check"><input type="checkbox" checked={allowShort} onChange={(e) => setAllowShort(e.target.checked)} /> Allow shorts</label>
          <button className="btn primary" disabled={loading}>{loading ? <Spinner /> : "Run backtest"}</button>
        </form>
        {current && (
          <div className="params">
            <p className="muted small">{current.description}</p>
            <div className="form">
              {Object.keys(current.defaults).map((k) => (
                <Field key={k} label={k}><input type="number" step="any" value={params[k] ?? ""} onChange={(e) => setParams({ ...params, [k]: e.target.value })} /></Field>))}
            </div>
          </div>
        )}
      </Card>
      <ErrorBox error={error} />

      {res && s && (
        <>
          <div className="stats">
            <Stat label="Total return" value={fmtPct(s["total_return_%"])} tone={tone(s["total_return_%"])} />
            <Stat label="Buy & hold" value={fmtPct(s["buy_hold_return_%"])} tone={tone(s["buy_hold_return_%"])} />
            <Stat label="CAGR" value={fmtPct(s["cagr_%"])} tone={tone(s["cagr_%"])} />
            <Stat label="Max drawdown" value={fmtPct(s["max_drawdown_%"])} tone="down" />
            <Stat label="Sharpe" value={fmtNum(s.sharpe)} />
            <Stat label="Trades" value={s.trades} />
            <Stat label="Win rate" value={fmtPct(s["win_rate_%"], 1, false)} />
            <Stat label="Profit factor" value={fmtNum(s.profit_factor)} />
            <Stat label="Expectancy" value={`${fmtNum(s.expectancy_R, 2)} R`} tone={tone(s.expectancy_R)} hint="Average result per trade in units of risk" />
          </div>
          <Card title="Equity curve"><LinesChart series={curves} /></Card>
          <Card title="Trades on chart"><PriceChart candles={res.candles} markers={markers} height={420} /></Card>
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
