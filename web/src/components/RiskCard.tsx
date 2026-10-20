import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { fmtDay, fmtNum } from "../lib/format";
import type { PortfolioRiskView, WorstDrop } from "../lib/types";
import { Hint } from "./Hint";
import { Card } from "./ui";

/** "How risky is this plan?": plain-English sentences first, then the numbers side by side with the S&P 500. */
export function RiskCard({ risk }: { risk: PortfolioRiskView | undefined }) {
  if (!risk) return null;
  const title = <>How risky is this plan?<Hint>What this exact mix could lose in a bad month, how it fell in the past, and how well its holdings spread the risk, always next to simply putting the same money in the S&amp;P&nbsp;500.</Hint></>;
  if (risk.status !== "ok" || !risk.month || !risk.worst_drop || !risk.diversification) {
    return <Card title={title}><p className="muted small">{risk.message ?? "The risk view is not available right now."}</p></Card>;
  }
  const ccy = risk.currency ?? "EUR";
  const money = (v: number) => v.toLocaleString("en-GB", { style: "currency", currency: ccy, maximumFractionDigits: 0 });
  const { plan, spy } = risk.month;
  const dp = risk.worst_drop.plan, ds = risk.worst_drop.spy;
  const d = risk.diversification;
  const years = Math.round((risk.days ?? 756) / 252);
  const loss = (m: number, p: number) => <><span className="num">−{money(m)}</span> <span className="muted small">({p.toFixed(1)}%)</span></>;
  const rec = (w: WorstDrop) => w.recovered ? duration(w.recovery_days ?? 0) : "not yet";

  const rows: [ReactNode, ReactNode, ReactNode][] = [
    [<>Bad month (1 in 20)<Hint>In about one month out of twenty, the loss would be at least this big. Simulated from {fmtNum(risk.paths ?? 10000, 0)} possible next months built from real past days, scaled to how calm or stormy the market is now.</Hint></>,
      loss(plan.loss_95, plan["loss_95_%"]), loss(spy.loss_95, spy["loss_95_%"])],
    [<>Very bad month (1 in 100)<Hint>A rarer, harsher month: roughly once every eight years. Real crashes (2008, March 2020) can be worse than any simulation.</Hint></>,
      loss(plan.loss_99, plan["loss_99_%"]), loss(spy.loss_99, spy["loss_99_%"])],
    [<>Chance of losing over 10% in a month<Hint>Share of the simulated months in which the whole portfolio drops by more than 10%.</Hint></>,
      <span className="num">{fmtNum(plan.p_loss_10 * 100, 1)}%</span>, <span className="num">{fmtNum(spy.p_loss_10 * 100, 1)}%</span>],
    [<>Worst drop, last {years} years<Hint>The biggest fall from a high point to a low point if you had held today's holdings, with today's weights, for the last {years} years. Indicative only: the plan changes every month, and today's picks were partly chosen because they did well.</Hint></>,
      <span className="num">{pct1(dp["drop_%"])}</span>, <span className="num">{pct1(ds["drop_%"])}</span>],
    [<>Time to get back to the high<Hint>How long it took, after the lowest point of that worst drop, to climb back to the previous high. "Not yet" means it had not recovered by {fmtDay(risk.as_of ?? "")}.</Hint></>,
      <span className="num">{rec(dp)}</span>, <span className="num">{rec(ds)}</span>],
    [<>Yearly swing (volatility)<Hint>How much the value typically moves up or down in a year, measured over the last {years} years. About two years in three end within this range of their average.</Hint></>,
      <span className="num">{fmtNum(risk["volatility_%"], 0)}%</span>, <span className="num">{fmtNum(risk["spy_volatility_%"], 0)}%</span>],
    [<>Swing right now<Hint>The same measure using mostly the last few weeks, which is what the bad-month numbers are scaled to. Higher than the yearly swing means the market is nervous at the moment.</Hint></>,
      <span className="num">{fmtNum(risk["volatility_now_%"], 0)}%</span>, <span className="num">{fmtNum(risk["spy_volatility_now_%"], 0)}%</span>],
    [<>Beta to the S&amp;P&nbsp;500<Hint>How much the plan tends to move when the S&amp;P 500 moves 1%. 0.9 means about 0.9%; the S&amp;P 500 itself is 1.00 by definition.</Hint></>,
      <span className="num">{fmtNum(risk.beta, 2)}</span>, <span className="num">1.00</span>],
  ];

  return (
    <Card title={title}>
      <div className="risk-summary">
        {(risk.summary ?? []).map((s, i) => <p key={i}>{s}</p>)}
      </div>

      <div className="table-wrap">
        <table className="risk-table">
          <thead><tr><th scope="col"><span className="sr-only">Measure</span></th><th scope="col">This plan</th><th scope="col">S&amp;P 500</th></tr></thead>
          <tbody>{rows.map(([label, a, b], i) => <tr key={i}><td>{label}</td><td>{a}</td><td>{b}</td></tr>)}</tbody>
        </table>
      </div>

      {risk.histogram && <MonthChart h={risk.histogram} loss95={plan["loss_95_%"]} />}

      <h3 className="small-title muted">How the risk is spread</h3>
      <dl className="kv">
        <dt>Independent bets<Hint>Holdings that move together count as one bet. This number says how many truly separate bets the {d.holdings} holdings add up to, once their ups and downs are compared. More is calmer; 1 means everything moves in lockstep.</Hint></dt>
        <dd>{d.independent_bets != null ? <>{fmtNum(d.independent_bets, 1)} <span className="muted">from {d.holdings} holdings</span></> : "–"}</dd>
        <dt>Average correlation<Hint>How much two holdings tend to move in the same direction on the same day, from 0 (unrelated) to 1 (always together). US stocks are usually around 0.3 to 0.5.</Hint></dt>
        <dd>{d.avg_correlation != null ? fmtNum(d.avg_correlation, 2) : "–"}</dd>
        {d.top_contributor && <><dt>Biggest single risk<Hint>The holding that adds the most to the plan's ups and downs, counting both its size and how much it moves with the rest. A share of risk far above its share of money means a volatile holding.</Hint></dt>
          <dd><strong>{d.top_contributor.symbol}</strong> <span className="muted">{fmtNum(d.top_contributor["risk_share_%"], 0)}% of the risk for {fmtNum(d.top_contributor["weight_%"], 0)}% of the money</span></dd></>}
        {d.top_sector && <><dt>Largest sector<Hint>The sector with the most money in it (the S&amp;P 500 index part is spread over all sectors and is not counted here). Rules cap any one sector at 25%.</Hint></dt>
          <dd>{d.top_sector.sector} <span className="muted">{fmtNum(d.top_sector["weight_%"], 0)}% of the money, {fmtNum(d.top_sector["risk_share_%"], 0)}% of the risk</span></dd></>}
        {(risk.ideas_share ?? 0) > 0.0005 && <><dt>Live ideas<Hint>Short trades held for days with a stop-loss, so the simulation counts them as cash. If all of them hit their stop at once this is roughly the extra loss; a price gap through a stop can make it worse.</Hint></dt>
          <dd>{fmtNum((risk.ideas_share ?? 0) * 100, 0)}% <span className="muted">{risk.ideas_stop_loss ? `at most about −${money(risk.ideas_stop_loss)} at their stops` : "about 1% of the portfolio each at its stop"}</span></dd></>}
      </dl>

      <p className="muted small" style={{ marginTop: 16 }}>
        Based on {years} years of daily prices up to {fmtDay(risk.as_of ?? "")} of today's holdings with today's weights{risk.currency_risk ? ", converted to euros (the euro-dollar rate moves too)" : ""}.
        {" "}The month simulation assumes no average gain or loss, so it shows risk, not a forecast. Past swings do not guarantee future ones.
        {risk.notes?.length ? <> {risk.notes.join(" ")}</> : null}
      </p>
    </Card>
  );
}

const pct1 = (v: number) => `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;

function duration(days: number): string {
  if (days < 30) return `${days} trading day${days === 1 ? "" : "s"}`;
  const m = Math.round(days / 21);
  return `about ${m} month${m === 1 ? "" : "s"}`;
}

/** Distribution of 1-month results: the plan as bars, the S&P 500 as a line, the 1-in-20 loss marked. */
function MonthChart({ h, loss95 }: { h: { "edges_%": number[]; plan: number[]; spy: number[] }; loss95: number }) {
  const [hover, setHover] = useState<number | null>(null);
  // Drawn at the container's real pixel width so text stays legible on phones (no viewBox scaling).
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(640);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setW(Math.max(240, Math.round(el.clientWidth)));
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, []);
  const e = h["edges_%"];
  const H = W < 480 ? 140 : 160, pad = { l: 4, r: 4, t: 12, b: 22 };
  const n = h.plan.length;
  const max = Math.max(...h.plan, ...h.spy, 1e-9);
  const bw = (W - pad.l - pad.r) / n;
  const x = (i: number) => pad.l + i * bw;
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const xOf = (pct: number) => pad.l + ((pct - e[0]) / (e[n] - e[0])) * (W - pad.l - pad.r);
  const spyPath = h.spy.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}H${x(i + 1)}`).join("");
  const label = (i: number) => `${i === 0 ? "below " + fmtNum(e[1], 0) : i === n - 1 ? "above " + fmtNum(e[n - 1], 0) : `${fmtNum(e[i], 0)} to ${fmtNum(e[i + 1], 0)}`}%`;
  const ticks = [-20, -10, 0, 10, 20].filter((t) => t > e[0] && t < e[n]);
  return (
    <figure className="risk-chart">
      <figcaption className="muted small">
        Possible results over the next month
        <Hint>Each bar is the share of simulated months ending in that range. Left of 0 is a loss. The line is the same picture for the S&amp;P 500, so you can compare how wide the two spreads are. The dashed mark is the bad-month (1 in 20) loss of this plan.</Hint>
        <span className="risk-legend"><i className="sw-bar" />This plan <i className="sw-line" />S&amp;P 500</span>
      </figcaption>
      <div ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`Distribution of one-month results. In a bad month (1 in 20) this plan loses about ${fmtNum(loss95, 1)}%.`} onMouseLeave={() => setHover(null)}>
        <line x1={pad.l} x2={W - pad.r} y1={H - pad.b} y2={H - pad.b} stroke="var(--line)" />
        {h.plan.map((v, i) => {
          const top = y(v);
          return <rect key={i} x={x(i) + 1} width={Math.max(bw - 2, 1)} y={top} height={Math.max(H - pad.b - top, 0)}
            fill={e[i + 1] <= 0 ? "var(--down)" : "var(--text-2)"} opacity={hover === null || hover === i ? 0.85 : 0.4} />;
        })}
        <path d={spyPath} fill="none" stroke="var(--text)" strokeWidth={1.5} />
        <line x1={xOf(-loss95)} x2={xOf(-loss95)} y1={pad.t} y2={H - pad.b} stroke="var(--text)" strokeDasharray="3 3" />
        <text x={xOf(-loss95) - 4} y={pad.t + 8} textAnchor="end" fontSize="10" fill="var(--text-2)">1 in 20</text>
        {ticks.map((t) => <text key={t} x={xOf(t)} y={H - 6} textAnchor="middle" fontSize="10" fill="var(--text-2)">{t > 0 ? "+" : ""}{t}%</text>)}
        {h.plan.map((_, i) => <rect key={`hit${i}`} x={x(i)} width={bw} y={pad.t} height={H - pad.t - pad.b} fill="transparent"
          onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} tabIndex={-1} />)}
      </svg>
      </div>
      <p className="muted small risk-readout" aria-live="polite">
        {hover !== null ? <>Result {label(hover)}: this plan in <strong>{fmtNum(h.plan[hover] * 100, 1)}%</strong> of months, the S&amp;P 500 in <strong>{fmtNum(h.spy[hover] * 100, 1)}%</strong>.</>
          : "Point at a bar to see how often each result happens."}
      </p>
    </figure>
  );
}
