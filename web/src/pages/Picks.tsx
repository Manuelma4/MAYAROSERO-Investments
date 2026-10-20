import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtDay, fmtNum, fmtPct, stockPath } from "../lib/format";
import { Price } from "../lib/currency";
import { useQuotes } from "../lib/quotes";
import { STATIC } from "../lib/snapshot";
import type { PicksResult } from "../lib/types";
import { LinesChart, SERIES, type Overlay } from "../components/charts";
import { Card, Empty, ErrorBox, Field, Spinner } from "../components/ui";
import { Hint } from "../components/Hint";
import { TrackRecordCard } from "../components/TrackRecord";
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

function nextRebalance(rebalance: string): string {
  const d = new Date();
  if (rebalance === "W-FRI") { d.setDate(d.getDate() + ((5 - d.getDay() + 7) % 7 || 7)); }
  else if (rebalance === "QE") { const m = Math.floor(d.getMonth() / 3) * 3 + 3; d.setMonth(m, 0); }
  else { d.setMonth(d.getMonth() + 1, 0); }
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
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
  const [showHistory, setShowHistory] = useState(false);
  const { resolved } = useTheme();

  const isDefault = topN === "10" && start === "2015-01-01" && rebalance === "ME" && trend && !regime;
  const reqId = useRef(0);
  const run = async () => {
    const id = ++reqId.current; // ignore responses from older requests (fast preset switching)
    setLoading(true); setError(null);
    const custom = () => api.picks({ preset, top_n: Number(topN), start, rebalance, trend_filter: trend, regime_filter: regime });
    try {
      // Default settings: instant precomputed result. Custom settings (or not ready yet): compute now.
      const r = isDefault ? await api.picksLatest(preset).catch(custom) : await custom();
      if (id === reqId.current) setRes(r);
    } catch (e) { if (id === reqId.current) setError(`The picks could not be computed. ${(e as Error).message}`); } finally { if (id === reqId.current) setLoading(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, [preset]);

  // Live prices for today's picks (refreshed every 30 s on the live app).
  const { quotes } = useQuotes(res?.picks.map((p) => p.symbol) ?? [], 30_000);
  const live = (res?.picks ?? []).map((p) => quotes[p.symbol]?.change_pct).filter((x): x is number => x !== undefined);
  const basketToday = live.length ? live.reduce((a, b) => a + b, 0) / live.length : undefined;

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
        <p className="eyebrow">{STATIC ? "Picks" : "Live picks"} · next rebalance {nextRebalance(rebalance)}</p>
        <h1 className="display">Beat the S&amp;P&nbsp;500</h1>
        <p className="muted lead">The stocks to hold right now: the S&amp;P&nbsp;500 stocks with the strongest momentum, trend and relative strength today, ranked by the engine and refreshed with live prices.</p>
        <div className="segmented wrap" role="radiogroup" aria-label="Strategy">
          {PRESETS.map((p) => (
            <button key={p.id} role="radio" aria-checked={preset === p.id} className={preset === p.id ? "active" : ""} onClick={() => setPreset(p.id)}>{p.label}</button>))}
        </div>
        {res && <p className="muted small">{res.preset_info[preset]}</p>}
      </section>
      <details className="customize">
        <summary>Customize<span className="muted small"> · {topN} stocks · {rebalance === "ME" ? "monthly" : rebalance === "QE" ? "quarterly" : "weekly"} review{trend ? " · uptrends only" : ""}{regime ? " · cash in bear markets" : ""}</span></summary>
        <form className="form" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <Field label="Stocks to hold"><select id="pk-topn" value={topN} onChange={(e) => setTopN(e.target.value)}>{[5, 8, 10, 15, 20].map((n) => <option key={n}>{n}</option>)}</select></Field>
          <Field label="Review every"><select id="pk-rebal" value={rebalance} onChange={(e) => setRebalance(e.target.value)}>
            <option value="ME">Month</option><option value="QE">Quarter</option><option value="W-FRI">Week</option></select></Field>
          <Field label="Test history from"><input id="pk-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <label className="check"><input id="pk-trend" type="checkbox" checked={trend} onChange={(e) => setTrend(e.target.checked)} /> Only uptrends</label>
          <label className="check"><input id="pk-regime" type="checkbox" checked={regime} onChange={(e) => setRegime(e.target.checked)} /> Cash in bear markets</label>
          <button className="btn primary" disabled={loading}>{loading ? <><Spinner /> Computing</> : "Update picks"}</button>
        </form>
        <ul className="hint-list muted small">
          <li><strong>Stocks to hold:</strong> fewer stocks means more concentrated (bigger ups and downs); 10 is a good balance.</li>
          <li><strong>Review every:</strong> how often the list is refreshed. Monthly is the standard for momentum; weekly trades more and costs more.</li>
          <li><strong>Only uptrends:</strong> skip stocks below their 200-day average (their long-term trend is down).</li>
          <li><strong>Cash in bear markets:</strong> sell everything when the S&amp;P 500 falls below its 200-day average; it avoids big crashes but can miss rebounds.</li>
        </ul>
      </details>
      <ErrorBox error={error} />
      {loading && !res && <div className="empty"><Spinner /> Ranking the ~500 S&amp;P 500 stocks on today's prices…</div>}

      {res?.changes?.date && (
        <Card title={<>Changes at the last review · {fmtDay(res.changes.date)}<Hint term="rebalance">What changed at the last completed review: buy the new names, sell the ones that dropped out, keep the rest. Reviews happen at the end of each period; the ranking below is today's and becomes official at the next review.</Hint></>}>
          <div className="changes inline">
            {([["Buy", res.changes.buy, "up"], ["Sell", res.changes.sell, "down"], ["Keep", res.changes.keep, ""]] as const).map(([label, list, tone]) => (
              <div key={label} className="change-row"><span className={`badge ${tone}`}>{label}</span><span className="change-syms">{list.length ? list.join(" · ") : <span className="muted">None</span>}</span></div>))}
          </div>
        </Card>
      )}

      {res && (
        <Card title={<>{res.risk_off ? "Signal: stay in cash" : `Hold now · ${res.picks.length} stocks`}<Hint term="equal-weight">The stocks to own today, best first. Put the same amount of money in each ("equal weight") and check back at the next review for changes. "Basket today" is how the whole list is doing since yesterday's close.</Hint></>}
          actions={<span className="muted small">{basketToday !== undefined && <>Basket today <Delta v={basketToday} digits={2} /> · </>}equal weight · ranked {fmtDay(res.as_of)}</span>}>
          {res.risk_off ? (
            <div className="notice">The S&amp;P 500 is below its 200-day average, so the bear-market filter says to hold cash until the trend recovers.</div>
          ) : !res.picks.length ? <Empty>No stock passes the engine's rules today (strong trend, beating the index). Holding cash until one does is part of the plan.</Empty> : (
            <>
            <ul className="pick-cards">
              {res.picks.map((p, i) => {
                const q = quotes[p.symbol];
                return (
                  <li key={p.symbol}>
                    <div className="pc-top">
                      <span className="muted small">{String(i + 1).padStart(2, "0")}</span>
                      <Link to={stockPath(p.symbol)} className="pc-name"><strong>{p.name}</strong><span className="muted small">{p.symbol} · {fmtNum(100 / res.picks.length, 1)}% of the money</span></Link>
                      <span className="pc-num"><Price className="num" v={q?.price ?? p.price} symbol={p.symbol} alt="stack" />{q?.change_pct !== undefined && <Delta v={q.change_pct} digits={2} />}</span>
                    </div>
                    {p.reason && <p className="muted small">{p.reason}</p>}
                  </li>);
              })}
            </ul>
            <div className="table-wrap picks-table">
              <table className="picks">
                <thead><tr><th>#</th><th>Company</th><th className="hide-sm">Sector</th><th>Score<Hint>The engine's overall grade combining momentum, trend, strength vs the S&amp;P 500 and calmness. Longer bar = stronger candidate.</Hint></th><th className="r">Price</th><th className="r">Today</th><th className="r">1M</th><th className="r hide-sm">12M ex-1M<Hint term="momentum">Return over the last 12 months, leaving out the most recent month (recent moves often reverse briefly). The core momentum signal.</Hint></th><th className="r hide-sm">vs S&amp;P 6M<Hint term="relative-strength">How much better (or worse) the stock did than the S&amp;P 500 over 6 months.</Hint></th><th className="r">Weight<Hint>Share of your money for this stock. Equal weights keep the portfolio diversified.</Hint></th></tr></thead>
                <tbody>
                  {res.picks.map((p, i) => {
                    const q = quotes[p.symbol];
                    return (
                      <tr key={p.symbol}>
                        <td className="muted">{String(i + 1).padStart(2, "0")}</td>
                        <td><Link className="asset" to={stockPath(p.symbol)}><span className="avatar">{p.symbol.slice(0, 2)}</span><span><strong>{p.name}</strong><span className="muted small">{p.symbol}</span></span></Link>
                          {p.reason && <div className="muted small pick-reason">{p.reason}</div>}</td>
                        <td className="muted hide-sm">{p.sector}</td>
                        <td><ScoreBar v={p.score} /></td>
                        <td className="r num"><Price v={q?.price ?? p.price} symbol={p.symbol} alt="stack" /></td>
                        <td className="r num">{q?.change_pct !== undefined ? <Delta v={q.change_pct} digits={2} /> : "–"}</td>
                        <td className="r num"><Delta v={p["return_1m_%"]} /></td>
                        <td className="r num hide-sm"><Delta v={p["momentum_12_1_%"]} /></td>
                        <td className="r num hide-sm"><Delta v={p["rel_strength_%"]} /></td>
                        <td className="r num">{fmtNum(100 / res.picks.length, 1)}%</td>
                      </tr>);
                  })}
                </tbody>
              </table>
            </div>
            </>
          )}
        </Card>
      )}

      {preset === "quality_momentum" && <TrackRecordCard />}

      {res && (
        <>
          <Card title={<>Rising candidates · top {Math.min(30, res.ranking.length)}<Hint>The full ranking behind the picks: the top of the list is held, the next names are the most likely to join at the next review. The bar is the engine's score; the % is the 12-month gain (leaving out the last month). Faded names are in a downtrend, so the uptrend filter skips them.</Hint></>}>
            <ol className="ranking cols">
              {res.ranking.slice(0, 30).map((p) => (
                <li key={p.symbol} className={p.eligible ? "" : "ineligible"} title={p.eligible ? "" : "Below its 200-day average: excluded by the uptrend filter"}>
                  <Link to={stockPath(p.symbol)}>{p.symbol}</Link>
                  <span className="muted small ellipsis">{p.name}</span>
                  <ScoreBar v={p.score} />
                  <Delta v={p["momentum_12_1_%"]} digits={0} />
                </li>))}
            </ol>
          </Card>
          <details className="fold">
            <summary>Picks history<span className="muted small"> · what changed at each of the last {Math.min(12, res.holdings.length)} reviews</span></summary>
            <p className="muted small">At every review the engine re-ranks all stocks. "+" = bought (entered the list), "−" = sold (left it); the rest were kept. You get a notification each time the list changes.</p>
            <ul className="timeline">
              {res.holdings.slice(0, 12).map((h, i) => {
                const prev = res.holdings[i + 1];
                const bought = prev ? h.symbols.filter((x) => !prev.symbols.includes(x)) : h.symbols;
                const sold = prev ? prev.symbols.filter((x) => !h.symbols.includes(x)) : [];
                return (
                  <li key={h.date}>
                    <span className="tl-date">{fmtDay(h.date)}</span>
                    <span className="tl-body">
                      {h.risk_off ? <em className="muted">Cash (bear-market filter)</em>
                        : !bought.length && !sold.length ? <span className="muted">No change · {h.symbols.length} kept</span>
                        : <>
                            {bought.map((x) => <span key={`b${x}`} className="pill up">+ {x}</span>)}
                            {sold.map((x) => <span key={`s${x}`} className="pill down">− {x}</span>)}
                            <span className="muted small"> {h.symbols.length - bought.length} kept</span>
                          </>}
                    </span>
                  </li>);
              })}
            </ul>
          </details>
        </>
      )}

      {res && s && (
        <section className="history">
          <button className="history-toggle" aria-expanded={showHistory} onClick={() => setShowHistory(!showHistory)}>
            <span>Track record: how this strategy would have done since {s.start} ({topN} stocks, {rebalance === "ME" ? "monthly" : rebalance === "QE" ? "quarterly" : "weekly"} review)</span>
            <span className="muted">{fmtPct(s["cagr_%"], 1)} / yr vs S&amp;P 500 {fmtPct(s["benchmark_cagr_%"], 1)} · {showHistory ? "Hide" : "Show"}</span>
          </button>
          {showHistory && (
            <div className="history-body">
              <p className="muted small">History is only used to test and tune the engine. The picks above are what it recommends today. Settings are in Customize at the top.</p>
              <div className="kpis">
                <div className="kpi"><span className="kpi-label">Annual return<Hint term="cagr">The average yearly growth of the picks over the test, compared with the S&amp;P 500 (SPY, dividends included) below.</Hint></span><span className="kpi-value">{fmtPct(s["cagr_%"], 1)}</span><span className="kpi-sub">S&amp;P 500 {fmtPct(s["benchmark_cagr_%"], 1)}</span></div>
                <div className="kpi"><span className="kpi-label">Edge vs index / year<Hint term="benchmark">How many percentage points a year the picks did better (or worse) than the S&amp;P 500.</Hint></span><span className={`kpi-value ${beat ? "up" : "down"}`}>{fmtPct(s["excess_cagr_%"], 1)}</span><span className="kpi-sub">{beat ? "Outperformed" : "Underperformed"} since {s.start}</span></div>
                <div className="kpi"><span className="kpi-label">Selection skill / year<Hint term="selection-skill">Compared with the same stocks held equally with no selection (each counted only while it was in the S&amp;P 500). This gap is the engine's own contribution.</Hint></span><span className={`kpi-value ${s["skill_vs_universe_%"] >= 0 ? "up" : "down"}`}>{fmtPct(s["skill_vs_universe_%"], 1)}</span><span className="kpi-sub">vs same stocks equal-weight {fmtPct(s["universe_cagr_%"], 1)}</span></div>
                <div className="kpi"><span className="kpi-label">Worst drawdown<Hint term="drawdown">The biggest fall from a peak before recovering. Expect to live through a drop like this again.</Hint></span><span className="kpi-value">{fmtPct(s["max_drawdown_%"], 1)}</span><span className="kpi-sub">S&amp;P 500 {fmtPct(s["benchmark_max_drawdown_%"], 1)}</span></div>
                <div className="kpi"><span className="kpi-label">Sharpe ratio<Hint term="sharpe">Return per unit of ups and downs. Higher is a smoother ride; around 1 is good.</Hint></span><span className="kpi-value">{fmtNum(s.sharpe, 2)}</span><span className="kpi-sub">S&amp;P 500 {fmtNum(s.benchmark_sharpe, 2)}</span></div>
                <div className="kpi"><span className="kpi-label">Months beating index<Hint term="turnover">How often a single month beat the S&amp;P 500. Turnover is the share of the portfolio traded at each review.</Hint></span><span className="kpi-value">{fmtNum(s["months_beating_benchmark_%"], 0)}%</span><span className="kpi-sub">Turnover {fmtNum(s["avg_turnover_%"], 0)}% / rebalance</span></div>
              </div>
              <Card title={<>Growth of 100 <span className="muted small">· log scale · portfolio · S&amp;P 500 (SPY, dividends included) · same stocks equal-weight</span></>}>
                <LinesChart series={curves} height={340} log />
              </Card>
              <p className="caveat">
                <strong>Read this before investing.</strong> The test uses today's S&amp;P 500 members ({res.universe_size} companies), but each one only counts from the day it joined the index. Without that rule the engine would "buy" stocks like Palantir or Super Micro during the big run-up that got them into the index, which nobody could have known in advance: the same test would then show {fmtPct(s["todays_members_cagr_%"], 1)} a year and a selection skill of {fmtPct(s["todays_members_skill_%"], 1)}, instead of the {fmtPct(s["cagr_%"], 1)} and {fmtPct(s["skill_vs_universe_%"], 1)} shown here. Some bias remains: companies that dropped out of the index are missing and the join dates are approximate, so even these figures are probably a bit flattering. The orange line holds the same index members with no selection; the gap to it ("selection skill") is the most honest measure of the engine. Trades are filled at the next day's opening price; costs of 0.10% per trade are included, taxes are not. This is research, not financial advice.
              </p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
