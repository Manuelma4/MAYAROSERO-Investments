import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtDay, fmtNum, fmtPct, stockPath, tone } from "../lib/format";
import { cssVar, useTheme } from "../lib/theme";
import type { TrackIdea, TrackRecord } from "../lib/types";
import { LinesChart, SERIES, type Overlay } from "./charts";
import { Hint } from "./Hint";
import { Card, Empty, Spinner, Stat } from "./ui";

const fmtR = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(2)}R`;

const REASON: Record<string, string> = { stop: "Stop-loss", target: "Target reached", "time limit": "Time limit" };

function IdeaRow({ o }: { o: TrackIdea }) {
  const what = o.status === "pending" ? "waits for the next market open"
    : o.status === "open" ? `bought ${fmtDay(o.fill_date)}, still open`
    : `${REASON[o.reason ?? ""] ?? "Closed"} · ${fmtDay(o.exit_date)}`;
  return (
    <li>
      <span className="idea-main">
        <span><Link to={stockPath(o.symbol)}><strong>{o.symbol}</strong></Link> <span className="muted small">{o.direction === "long" ? "rising" : "falling"} · idea of {fmtDay(o.as_of)}</span></span>
        <span className="muted small">{what}</span>
      </span>
      <span className={tone(o.r)}>{fmtR(o.r)}</span>
    </li>
  );
}

/** The live, forward track record: what the engine said each day and what really happened next. */
export function TrackRecordCard({ compact = false }: { compact?: boolean }) {
  const [tr, setTr] = useState<TrackRecord | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { resolved } = useTheme();
  useEffect(() => {
    let alive = true;
    const load = () => api.trackRecord().then((d) => { if (alive) { setTr(d); setErr(null); } })
      .catch((e) => alive && setErr((e as Error).message));
    load();
    const id = setInterval(load, 5 * 60_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const curve = useMemo<Overlay[]>(() => tr && tr.picks.curve.length > 1 ? [
    { data: tr.picks.curve.map((c) => ({ time: c.time, value: c.picks })), color: cssVar("--text"), width: 2, title: "Picks" },
    { data: tr.picks.curve.map((c) => ({ time: c.time, value: c.spy })), color: SERIES.band, dashed: true, title: "S&P 500" },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ] : [], [tr, resolved]);

  const title = (
    <>Live track record{tr?.started ? ` · since ${fmtDay(tr.started)}` : ""}
      <Hint>Not a backtest. From the day this record started, the server saves the picks after every US market close and each Invest-now idea the moment it appears. Results use the next opening price after each save, real prices since, and 0.10% trading costs, so nothing is chosen with hindsight.</Hint></>
  );
  if (!tr) return (
    <Card title={title}>{err ? <Empty>The live record is not available right now. {err}</Empty> : <div className="empty"><Spinner /> Loading the live record…</div>}</Card>
  );

  const p = tr.picks;
  const i = tr.ideas;
  const hasPicks = p.days > 0;
  return (
    <Card title={title} actions={compact ? <Link to="/picks" className="link">Details</Link> : undefined}>
      <p className={tr.too_early ? "notice" : "muted small"}>
        {tr.too_early ? <><strong>Too early to judge.</strong> </> : null}{tr.message}
      </p>
      {hasPicks && (
        <div className="stats track">
          <Stat label="Picks" value={fmtPct(p["return_%"], 2)} tone={tone(p["return_%"])}
            hint={`What the engine's picks really returned since ${fmtDay(p.first_trade)}: bought at the next opening price after each daily save, equal amounts in each stock, costs included.`} />
          <Stat label="S&P 500" value={fmtPct(p["spy_%"], 2)} tone={tone(p["spy_%"])}
            hint="The S&P 500 (the SPY fund, dividends included) over exactly the same days: the yardstick to beat." />
          <Stat label="Difference" value={fmtPct(p["excess_%"], 2)} tone={tone(p["excess_%"])}
            hint="Picks minus the S&P 500. Positive = the picks are ahead so far. Over a few weeks this is mostly luck." />
          {!compact && <Stat label="Same stocks, equal weight" value={fmtPct(p["universe_%"], 2)} tone={tone(p["universe_%"])}
            hint="All S&P 500 stocks held in equal amounts, no selection, measured from the close of the first saved day. Beating this line is the engine's own skill." />}
          {!compact && <Stat label="Worst drop" value={fmtPct(p["max_drawdown_%"], 1)}
            hint={`The biggest fall from a high point along the way (S&P 500: ${fmtPct(p["spy_max_drawdown_%"], 1)}).`} />}
          {!compact && <Stat label="Trading" value={`${fmtNum(p.rebalances, 0)} × · ${fmtNum(p["turnover_%"], 0)}%`}
            hint="How many times the portfolio was rebalanced (only when the list of picks changed) and how much was bought and sold in total, as a % of the portfolio. Each trade costs 0.10%." />}
        </div>
      )}
      {!compact && curve.length > 0 && (
        <div className="track-chart"><LinesChart series={curve} height={180} /></div>
      )}
      <h3 className="track-sub">Invest-now ideas<Hint>Every live idea that qualified (news + heavy volume + trend) is saved, then followed: bought at the next opening price, sold at its stop-loss, its target or after 5 trading days. If one day touches both the stop and the target, the stop is counted (the cautious choice).</Hint></h3>
      {!i.count ? <p className="muted small">No idea recorded yet. They are saved the moment one qualifies.</p> : (
        <div className="stats track">
          <Stat label="Ideas" value={`${i.closed_count} done · ${i.open_count + i.pending_count} open`}
            hint="Done = sold at the stop, the target or the time limit. Open = still running or waiting for the next market open." />
          <Stat label="Win rate" value={i.win_rate === null ? "–" : `${fmtNum(i.win_rate, 0)}%`}
            hint="Share of finished ideas that made money after costs. With a target twice as far as the stop, about 40% is enough to come out ahead." />
          <Stat label="Average result" value={fmtR(i.avg_r)} tone={tone(i.avg_r)}
            hint="Average gain per finished idea in units of risk (R). +1R = won as much as the planned loss at the stop-loss; −1R = the stop was hit." />
          <Stat label="Total" value={i["total_r_%"] === null ? "–" : fmtPct(i["total_r_%"], 0)} tone={tone(i["total_r_%"])}
            hint="All finished ideas added up, in % of the amount risked per idea. Example: risking 100 € each, +150% means +150 € in total." />
        </div>
      )}
      {!compact && (i.open.length > 0 || i.closed.length > 0) && (
        <details className="fold track-fold">
          <summary>Idea by idea<span className="muted small"> · {i.open.length} open · {i.closed.length} finished</span></summary>
          <ul className="movers">{[...i.open, ...i.closed].slice(0, 30).map((o) => <IdeaRow key={`${o.symbol}${o.direction}${o.as_of}`} o={o} />)}</ul>
        </details>
      )}
    </Card>
  );
}
