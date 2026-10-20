import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { fmtBig, fmtNum, fmtPct, fmtPrice, stockPath } from "../lib/format";
import { useQuotes } from "../lib/quotes";
import { EARNINGS_HINT, TIMING_SHORT, daysUntil, fmtEarnDay, whenText } from "../lib/earnings";
import type { ChartData, EarningsRecord, StockInfo } from "../lib/types";
import { AIDesk } from "../components/AIDesk";
import { ForecastPanel } from "../components/Forecast";
import { Hint } from "../components/Hint";
import type { TermId } from "../lib/glossary";
import { PriceChart, SERIES, type Overlay } from "../components/charts";
import { Sparkline } from "../components/Sparkline";
import { Badge, Card, ErrorBox, Spinner } from "../components/ui";
import { AddToWatchlist, AlertForm } from "../components/MyAlerts";

const VERDICT_TONE = { pick: "up", ranked: "", excluded: "down", not_covered: "", unknown: "" } as const;
const VERDICT_LABEL = { pick: "In the picks", ranked: "Ranked, not held", excluded: "Excluded (downtrend)", not_covered: "Not covered", unknown: "…" } as const;

const FIELDS: { key: string; label: string; fmt: (v: number) => string; hint: string; term?: TermId }[] = [
  { key: "marketCap", term: "market-cap", label: "Market value", fmt: (v) => `$${fmtBig(v)}`, hint: "What the whole company is worth on the stock market (price × number of shares)." },
  { key: "trailingPE", term: "pe-ratio", label: "P/E (last 12 months)", fmt: (v) => fmtNum(v, 1), hint: "Price ÷ profit per share. How many years of current profits you pay for. The S&P 500 average is usually around 20-25; high means the market expects strong growth." },
  { key: "forwardPE", label: "P/E (next 12 months)", fmt: (v) => fmtNum(v, 1), hint: "Same ratio using analysts' expected profits. Lower than the current P/E means profits are expected to grow." },
  { key: "priceToSalesTrailing12Months", label: "Price / sales", fmt: (v) => fmtNum(v, 1), hint: "Company value ÷ yearly revenue. Useful when profits are small or negative." },
  { key: "revenueGrowth", label: "Revenue growth", fmt: (v) => fmtPct(v * 100, 1), hint: "How much sales grew versus a year earlier (latest quarter)." },
  { key: "earningsGrowth", label: "Profit growth", fmt: (v) => fmtPct(v * 100, 1), hint: "How much profit grew versus a year earlier (latest quarter)." },
  { key: "profitMargins", label: "Profit margin", fmt: (v) => fmtPct(v * 100, 1, false), hint: "Share of each dollar of sales that ends up as profit." },
  { key: "debtToEquity", label: "Debt / equity", fmt: (v) => fmtNum(v, 0), hint: "Debt compared with the owners' money (×100). Above ~150 means a lot of debt." },
  { key: "dividendYield", term: "dividend-yield", label: "Dividend yield", fmt: (v) => fmtPct(v, 2, false), hint: "Yearly cash dividend as a share of the price (Yahoo reports it in percent)." },
];

const hasEarnings = (s: string) => !!s && !s.includes("/") && !s.startsWith("^") && !s.includes("=");

/** Next / last quarterly results, in plain English. */
function EarningsCard({ symbol }: { symbol: string }) {
  const [rec, setRec] = useState<EarningsRecord | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    setRec(null); setFailed(false);
    api.earnings([symbol]).then((d) => alive && setRec(d.items[0] ?? null)).catch(() => alive && setFailed(true));
    return () => { alive = false; };
  }, [symbol]);
  if (failed || rec?.status === "none") return null;
  const n = rec?.next;
  const l = rec?.last;
  const move = rec?.avg_move;
  return (
    <Card title={<>Earnings<Hint>{EARNINGS_HINT}</Hint></>}>
      {!rec ? <div className="muted small"><Spinner /> Loading…</div> : (
        <dl className="kv earnings-kv">
          <dt>Next earnings<Hint>The day the company publishes its results; prices often jump or drop that day or the next.</Hint></dt>
          <dd>{n ? <><strong>{fmtEarnDay(n.date)}</strong> <span className="muted">· {whenText(daysUntil(n.date))} · {TIMING_SHORT[n.timing]}</span></>
            : <span className="muted">Not announced yet</span>}</dd>
          {n?.eps_estimate != null && <>
            <dt>Analysts expect<Hint>Expected profit per share for that quarter (EPS). Beating or missing this number is what usually moves the price.</Hint></dt>
            <dd>{fmtNum(n.eps_estimate, 2)} per share</dd>
          </>}
          {l && <>
            <dt>Last results<Hint>The latest published results: actual profit per share against what analysts expected. "Beat" means better than expected.</Hint></dt>
            <dd>{fmtEarnDay(l.date)}{l.eps_actual != null && <> · {fmtNum(l.eps_actual, 2)} per share{l.eps_estimate != null && <> vs {fmtNum(l.eps_estimate, 2)} expected</>}</>}
              {l.surprise_pct != null && <span className={l.surprise_pct >= 0 ? "up" : "down"}> ({l.surprise_pct >= 0 ? "beat" : "missed"} by {fmtPct(Math.abs(l.surprise_pct), 1, false)})</span>}</dd>
          </>}
          {move && <>
            <dt>Typical move<Hint>How much the price moved, up or down, on the trading day that reacted to each of the last reports (average size of the move, ignoring direction). Past moves don't predict the next one's direction.</Hint></dt>
            <dd>±{fmtNum(move["avg_abs_move_%"], 1)}% <span className="muted small">(last {move.moves.length} report{move.moves.length > 1 ? "s" : ""})</span></dd>
          </>}
        </dl>
      )}
    </Card>
  );
}

export default function Stock() {
  const { symbol: raw = "" } = useParams();
  const symbol = raw.toUpperCase();  // react-router already decodes the path segment
  const [info, setInfo] = useState<StockInfo | null>(null);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [chartErr, setChartErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;  // a late answer for the previous stock must not land on this page
    setInfo(null); setChart(null); setErr(null); setChartErr(null);
    api.stock(symbol).then((d) => alive && setInfo(d)).catch((e) => alive && setErr((e as Error).message));
    api.chart({ provider: "auto", symbol, timeframe: "1d", limit: 260 }).then((d) => alive && setChart(d)).catch((e) => alive && setChartErr((e as Error).message));
    return () => { alive = false; };
  }, [symbol]);
  const { quotes } = useQuotes(info?.similar.map((s) => s.symbol) ?? [], 60_000);

  const overlays = useMemo<Overlay[]>(() => chart ? [
    { data: chart.overlays.ema50, color: SERIES.ema50, title: "EMA50" },
    { data: chart.overlays.ema200, color: SERIES.ema200, width: 2, title: "EMA200" },
  ] : [], [chart]);

  if (err) return (
    <div className="page">
      <section className="hero-x"><p className="eyebrow">Stock</p><h1 className="display">{symbol}</h1></section>
      <ErrorBox error={`This page could not be loaded. ${err}`} />
      <p className="muted">Check the ticker (for example AAPL, MC.PA, ^GSPC or BTC/USDT) with the search box at the top, or go back to <Link className="link" to="/">Today</Link>.</p>
    </div>
  );
  const q = info?.quote;
  const f = info?.fundamentals ?? {};
  const target = typeof f.targetMeanPrice === "number" ? f.targetMeanPrice : null;
  const upside = target && q?.price ? (target / q.price - 1) * 100 : null;

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">{info ? [info.sector, info.industry, info.region].filter(Boolean).join(" · ") : symbol}</p>
        <h1 className="display">{info?.name ?? symbol}</h1>
        <div className="stock-price">
          <span className="sp-price">{fmtPrice(q?.price)}</span>
          {q?.change_pct !== undefined && <span className={`pill ${q.change_pct >= 0 ? "up" : "down"}`}>{fmtPct(q.change_pct, 2)} today</span>}
          <span className="muted">{symbol}</span>
        </div>
        {info && info.themes.length > 0 && <div className="chips">{info.themes.map((t) => <span className="chip" key={t}>{t}</span>)}</div>}
        <div className="stock-actions">
          <AddToWatchlist key={symbol} symbol={symbol} />
          <details className="alert-details">
            <summary className="btn">Set price alert</summary>
            <AlertForm key={symbol} symbol={symbol} price={q?.price} />
          </details>
        </div>
      </section>

      <div className="grid-main stock-main">
        <Card title={<>Price · 1 year<Hint>Daily candles with the 50-day (orange) and 200-day (violet) averages. Price above the 200-day line = long-term uptrend.</Hint></>} actions={<Link className="link" to={`/charts?symbol=${encodeURIComponent(symbol)}`}>Full chart</Link>}>
          {chart ? <PriceChart candles={chart.candles} overlays={overlays} height={360} />
            : chartErr ? <div className="empty">The price history is not available right now. {chartErr}</div>
            : <div className="empty"><Spinner /> Loading one year of prices…</div>}
        </Card>
        <div className="stack">
          <Card title={<>The engine's view<Hint>What this app's stock-selection engine thinks of this stock today: whether it is in the Beat-the-S&amp;P picks, how it ranks, and any live idea on it.</Hint></>}>
            {!info ? <div className="muted small"><Spinner /> Loading…</div> : (
              <div className="verdict">
                <Badge tone={VERDICT_TONE[info.verdict.status]}>{VERDICT_LABEL[info.verdict.status]}</Badge>
                <p>{info.verdict.text}</p>
                {info.ranking && (
                  <p className="muted small">Next week: ranked in the {info.ranking.decile >= 6 ? `top ${(11 - info.ranking.decile) * 10}%` : `bottom ${info.ranking.decile * 10}%`} ({fmtPct(info.ranking.p_outperform * 100, 0, false)} chance to beat the typical stock).
                    <Hint>From the daily machine-learning ranking on the Predict page.</Hint></p>
                )}
                {info.idea && <p className="notice">Live idea right now: {info.idea.direction === "long" ? "rising" : "falling"} {fmtPct(info.idea.change_pct, 1)} on news. <Link to="/now" className="link">Open</Link></p>}
                <AIDesk symbol={symbol} />
              </div>
            )}
          </Card>
          {hasEarnings(symbol) && <EarningsCard key={symbol} symbol={symbol} />}
          {target && (
            <Card title={<>Analysts<Hint>Average 12-month price target from the analysts covering the stock, and their consensus. Analysts are often too optimistic; treat it as one opinion.</Hint></>}>
              <dl className="kv">
                <dt>Average target</dt><dd>{fmtPrice(target)} <span className={(upside ?? 0) >= 0 ? "up" : "down"}>({fmtPct(upside, 0)})</span></dd>
                <dt>Consensus</dt><dd style={{ textTransform: "capitalize" }}>{String(f.recommendationKey ?? "–").replace("_", " ")}</dd>
                <dt>Analysts</dt><dd>{f.numberOfAnalystOpinions ?? "–"}</dd>
              </dl>
            </Card>
          )}
        </div>
      </div>

      {info && FIELDS.some((x) => typeof f[x.key] === "number") && (
        <Card title={<>Key figures<Hint>From the company's latest reports, via Yahoo Finance. Hover or tap "?" on each for what it means.</Hint></>}>
          <div className="figs">
            {FIELDS.filter((x) => typeof f[x.key] === "number").map((x) => (
              <div key={x.key} className="fig"><span className="kpi-label">{x.label}<Hint term={x.term}>{x.hint}</Hint></span><strong>{x.fmt(f[x.key] as number)}</strong></div>))}
          </div>
        </Card>
      )}

      <Card title={<>Forecast · next 5 trading days<Hint>5,000 simulated futures from this stock's real daily moves and today's volatility, plus where most shares traded recently.</Hint></>}>
        <ForecastPanel symbol={symbol} horizon={5} />
      </Card>

      {info && info.similar.length > 0 && (
        <Card title={<>Similar companies<Hint>Companies in the same industry, with today's price and change and a line of the last 30 days. Useful to check whether a move is about this company or the whole industry.</Hint></>}>
          <div className="srows">
            {info.similar.map((s) => {
              const sq = quotes[s.symbol];
              return (
                <Link key={s.symbol} to={stockPath(s.symbol)} className="srow">
                  <span className="avatar">{s.symbol.replace(/[-.^/].*/, "").slice(0, 4)}</span>
                  <span className="srow-name"><strong>{s.name}</strong><span className="muted small">{s.symbol} · {s.industry}</span></span>
                  <Sparkline data={sq?.spark} width={84} height={26} className="hide-sm" />
                  <span className="srow-num"><span className="num">{fmtPrice(sq?.price)}</span>{sq?.change_pct !== undefined && <span className={`small ${sq.change_pct >= 0 ? "up" : "down"}`}>{fmtPct(sq.change_pct, 2)}</span>}</span>
                </Link>);
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
