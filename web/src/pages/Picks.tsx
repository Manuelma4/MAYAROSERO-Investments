import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtNum, fmtPct, fmtPrice } from "../lib/format";
import type { PicksResult } from "../lib/types";
import { LinesChart, SERIES, type Overlay } from "../components/charts";
import { Card, ErrorBox, Field, Spinner } from "../components/ui";
import { cssVar, useTheme } from "../lib/theme";

const PRESETS = [
  { id: "quality_momentum", label: "Quality momentum" },
  { id: "momentum", label: "Momentum" },
  { id: "trend_following", label: "Trend" },
  { id: "low_volatility", label: "Low volatility" },
];

function Delta({ v, digits = 1 }: { v: number | undefined; digits?: number }) {
  return <span className={(v ?? 0) >= 0 ? "up" : "down"}>{fmtPct(v, digits)}</span>;
}

function ScoreBar({ v }: { v: number }) {
  const pct = Math.max(4, Math.min(100, ((v + 1.5) / 3) * 100));
  return <span className="scorebar" title={`Score ${v.toFixed(2)}`}><span style={{ width: `${pct}%` }} /></span>;
}

export default function Picks() {
  const [preset, setPreset] = useState("quality_momentum");
  const [topN, setTopN] = useState("10");
  const [start, setStart] = useState("2015-01-01");
  const [rebalance, setRebalance] = useState("ME");
  const [trend, setTrend] = useState(true);
  const [regime, setRegime] = useState(false);
  const [res, setRes] = useState<PicksResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { resolved } = useTheme();

  const run = async () => {
    setLoading(true); setError(null);
    try {
      setRes(await api.picks({ preset, top_n: Number(topN), start, rebalance, trend_filter: trend, regime_filter: regime }));
    } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, [preset]);

  const curves = useMemo<Overlay[]>(() => res ? [
    { data: res.equity, color: cssVar("--text"), width: 2, title: "Portfolio" },
    { data: res.benchmark, color: SERIES.band, dashed: true, title: "S&P 500" },
    { data: res.universe, color: SERIES.ema50, dashed: true, width: 1, title: "Same stocks, equal weight" },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ] : [], [res, resolved]);
  const s = res?.stats as Record<string, number> | undefined;
  const beat = s ? s["excess_cagr_%"] > 0 : false;

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Stock selection engine</p>
        <h1 className="display">Beat the S&amp;P&nbsp;500</h1>
        <p className="muted lead">Every month the engine ranks the S&amp;P&nbsp;500's leading companies on momentum, trend, relative strength and volatility, holds the best ones and measures itself against the index, net of trading costs.</p>
        <div className="segmented wrap" role="radiogroup" aria-label="Strategy">
          {PRESETS.map((p) => (
            <button key={p.id} role="radio" aria-checked={preset === p.id} className={preset === p.id ? "active" : ""} onClick={() => setPreset(p.id)}>{p.label}</button>))}
        </div>
        {res && <p className="muted small">{res.preset_info[preset]}</p>}
      </section>

      <Card>
        <form className="form" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <Field label="Stocks held"><select value={topN} onChange={(e) => setTopN(e.target.value)}>{[5, 8, 10, 15, 20].map((n) => <option key={n}>{n}</option>)}</select></Field>
          <Field label="Rebalance"><select value={rebalance} onChange={(e) => setRebalance(e.target.value)}>
            <option value="ME">Monthly</option><option value="QE">Quarterly</option><option value="W-FRI">Weekly</option></select></Field>
          <Field label="Backtest from"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <label className="check"><input type="checkbox" checked={trend} onChange={(e) => setTrend(e.target.checked)} /> Only uptrends</label>
          <label className="check" title="Move to cash when the S&P 500 is below its 200-day average"><input type="checkbox" checked={regime} onChange={(e) => setRegime(e.target.checked)} /> Cash in bear markets</label>
          <button className="btn primary" disabled={loading}>{loading ? <><Spinner /> Computing</> : "Run"}</button>
        </form>
      </Card>
      <ErrorBox error={error} />
      {loading && !res && <div className="empty"><Spinner /> Loading 10+ years of prices for {"~120"} companies…</div>}

      {res && s && (
        <>
          <div className="kpis">
            <div className="kpi">
              <span className="kpi-label">Annual return</span>
              <span className="kpi-value">{fmtPct(s["cagr_%"], 1)}</span>
              <span className="kpi-sub">S&amp;P 500 {fmtPct(s["benchmark_cagr_%"], 1)}</span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Edge vs index / year</span>
              <span className={`kpi-value ${beat ? "up" : "down"}`}>{fmtPct(s["excess_cagr_%"], 1)}</span>
              <span className="kpi-sub">{beat ? "Outperformed" : "Underperformed"} since {s.start}</span>
            </div>
            <div className="kpi" title="Return over the same stocks held equally with no selection. Both share the survivorship bias, so this gap is the engine's own contribution.">
              <span className="kpi-label">Selection skill / year</span>
              <span className={`kpi-value ${s["skill_vs_universe_%"] >= 0 ? "up" : "down"}`}>{fmtPct(s["skill_vs_universe_%"], 1)}</span>
              <span className="kpi-sub">vs same stocks equal-weight {fmtPct(s["universe_cagr_%"], 1)}</span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Worst drawdown</span>
              <span className="kpi-value">{fmtPct(s["max_drawdown_%"], 1)}</span>
              <span className="kpi-sub">S&amp;P 500 {fmtPct(s["benchmark_max_drawdown_%"], 1)}</span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Sharpe ratio</span>
              <span className="kpi-value">{fmtNum(s.sharpe, 2)}</span>
              <span className="kpi-sub">S&amp;P 500 {fmtNum(s.benchmark_sharpe, 2)}</span>
            </div>
            <div className="kpi">
              <span className="kpi-label">Months beating index</span>
              <span className="kpi-value">{fmtNum(s["months_beating_benchmark_%"], 0)}%</span>
              <span className="kpi-sub">Turnover {fmtNum(s["avg_turnover_%"], 0)}% / rebalance</span>
            </div>
          </div>

          <Card title={<>Growth of 100 <span className="muted small">· log scale · portfolio · S&amp;P 500 (SPY, dividends included) · same stocks equal-weight</span></>}>
            <LinesChart series={curves} height={360} log />
          </Card>

          <Card title={<>{res.risk_off ? "Signal: stay in cash" : `Current picks · ${res.picks.length} stocks`}</>}
            actions={<span className="muted small">As of {res.as_of.slice(0, 10)} · equal weight</span>}>
            {res.risk_off ? (
              <div className="notice">The S&amp;P 500 is below its 200-day average, so the bear-market filter says to hold cash until the trend recovers.</div>
            ) : (
              <div className="table-wrap">
                <table className="picks">
                  <thead><tr><th>#</th><th>Company</th><th className="hide-sm">Sector</th><th>Score</th><th className="r">Price</th><th className="r">1M</th><th className="r">12M ex-1M</th><th className="r hide-sm">vs S&amp;P 6M</th><th className="r hide-sm">Volatility</th><th className="r">Weight</th></tr></thead>
                  <tbody>
                    {res.picks.map((p, i) => (
                      <tr key={p.symbol}>
                        <td className="muted">{String(i + 1).padStart(2, "0")}</td>
                        <td><Link className="asset" to={`/charts?symbol=${encodeURIComponent(p.symbol)}`}><span className="avatar">{p.symbol.slice(0, 2)}</span><span><strong>{p.name}</strong><span className="muted small">{p.symbol}</span></span></Link></td>
                        <td className="muted hide-sm">{p.sector}</td>
                        <td><ScoreBar v={p.score} /></td>
                        <td className="r num">{fmtPrice(p.price)}</td>
                        <td className="r num"><Delta v={p["return_1m_%"]} /></td>
                        <td className="r num"><Delta v={p["momentum_12_1_%"]} /></td>
                        <td className="r num hide-sm"><Delta v={p["rel_strength_%"]} /></td>
                        <td className="r num hide-sm">{fmtNum(p["volatility_%"], 0)}%</td>
                        <td className="r num">{fmtNum(100 / res.picks.length, 1)}%</td>
                      </tr>))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="grid-2">
            <Card title="Full ranking">
              <ol className="ranking">
                {res.ranking.slice(0, 30).map((p) => (
                  <li key={p.symbol} className={p.eligible ? "" : "ineligible"} title={p.eligible ? "" : "Below its 200-day average: excluded by the uptrend filter"}>
                    <Link to={`/charts?symbol=${encodeURIComponent(p.symbol)}`}>{p.symbol}</Link>
                    <span className="muted small ellipsis">{p.name}</span>
                    <ScoreBar v={p.score} />
                    <Delta v={p["momentum_12_1_%"]} digits={0} />
                  </li>))}
              </ol>
            </Card>
            <Card title="Rebalance history">
              <ul className="timeline">
                {res.holdings.slice(0, 12).map((h) => (
                  <li key={h.date}>
                    <span className="tl-date">{h.date}</span>
                    <span className="tl-body">{h.risk_off ? <em className="muted">Cash (bear-market filter)</em> : h.symbols.join(" · ")}</span>
                  </li>))}
              </ul>
            </Card>
          </div>

          <p className="caveat">
            <strong>Read this before investing.</strong> The universe is today's S&amp;P 500 leaders ({res.universe_size} companies), so the backtest carries survivorship bias: companies that fell out of the index are missing, which flatters past results. The orange line holds those same stocks with no selection; the gap between it and the portfolio ("selection skill") is the most honest measure of the engine. Factor strategies beat the market on average over long periods but can lag it for years. Costs of {"0.10%"} per trade are included; taxes are not. This is research, not financial advice.
          </p>
        </>
      )}
    </div>
  );
}
