import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtDay, fmtPct, fmtPrice, fmtTime, stockPath } from "../lib/format";
import { useLive } from "../lib/live";
import { MARKETS, STOCKS, marketName } from "../lib/markets";
import { useQuotes } from "../lib/quotes";
import type { LiveEvent, OpportunitiesResult, Quote, TodayBoard } from "../lib/types";
import { Hint } from "../components/Hint";
import { Sparkline } from "../components/Sparkline";
import { TrackRecordCard } from "../components/TrackRecord";
import { Card, Empty, Spinner } from "../components/ui";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** One line per notification, whatever its type: what happened, when, and the number that matters. */
function eventLine(e: LiveEvent): { title: string; what: string; value: string; tone: string } {
  const when = fmtTime(e.created_at || e.time);
  if (e.type === "picks") return { title: "Picks updated", what: `Buy ${e.buy?.join(", ") || "nothing new"} · ${when}`, value: "Review", tone: "" };
  if (e.type === "alert") return { title: e.symbol, what: `Your price alert fired · ${when}`, value: fmtPrice(e.price), tone: "" };
  if (e.type === "move") return { title: e.symbol, what: `${e.direction === "SURGE" ? "Sudden rise" : "Sudden drop"} · ${when}`, value: fmtPct(e.move_pct, 2), tone: (e.move_pct ?? 0) >= 0 ? "up" : "down" };
  // Live ideas carry "long" / "short" in direction; setup signals carry it in side.
  const long = (e.side ?? (e.direction as string | undefined)) === "long";
  if (e.type === "opportunity") return { title: e.symbol, what: `Live idea: ${long ? "rising" : "falling"} on news · ${when}`, value: fmtPct(e.change_pct, 1), tone: long ? "up" : "down" };
  return { title: e.symbol, what: `${long ? "Long" : "Short"} setup triggered · ${when}`, value: long ? "Long" : "Short", tone: long ? "up" : "down" };
}

const MOOD_TONE = { "Risk-on": "up", Neutral: "", "Risk-off": "down" } as const;

function MarketCard({ symbol, name, q }: { symbol: string; name: string; q?: Quote }) {
  const pct = q?.change_pct ?? 0;
  return (
    <Link to={`/charts?symbol=${encodeURIComponent(symbol)}`} className="mcard">
      <div className="mcard-top">
        <div><div className="mcard-name">{name}</div><div className="muted small">{symbol}</div></div>
        {q?.price !== undefined && <span className={`pill ${pct >= 0 ? "up" : "down"}`}>{fmtPct(pct, 2)}</span>}
      </div>
      {q?.error ? <div className="muted small mcard-err">Data unavailable</div> : q?.price === undefined ? <div className="skeleton" /> : (
        <div className="mcard-bottom">
          <span className="mcard-price">{fmtPrice(q.price)}</span>
          <Sparkline data={q.spark} width={110} height={38} />
        </div>
      )}
    </Link>
  );
}

function TodayBoardView({ t, ideas }: { t: TodayBoard; ideas: ReactNode }) {
  const core = t.core;
  const ch = core?.changes;
  return (
    <>
      {t.mood && <section className="mood">
        <div className="mood-head">
          <span className="kpi-label">Market mood<Hint>Combines the S&amp;P 500's trend (above or below its 200-day average), how many S&amp;P 500 stocks are in an uptrend, and the fear index (VIX). It tells you whether the market wind is at your back.</Hint></span>
          <span className={`mood-label ${MOOD_TONE[t.mood.label]}`}>{t.mood.label}</span>
        </div>
        <p className="mood-text">{t.mood.explanation}</p>
        <p className="mood-advice">{t.mood.advice}</p>
      </section>}

      {ideas}

      <div className="grid-3">
        <Card className="span-2" title={<>What to hold now<Hint>The engine's current top picks among the S&amp;P 500 stocks: strong 12-month performance, beating the index, in an uptrend, with calmer price action. Split your money equally between them and review once a month.</Hint></>}
          actions={<Link to="/picks" className="link">All picks</Link>}>
          {!core ? <Empty>Picks are being computed. They appear here within a few minutes of the server starting.</Empty> : core.risk_off ? (
            <div className="notice">The S&amp;P 500 is in a downtrend, so the engine suggests holding cash until it recovers.</div>
          ) : !core.picks.length ? <Empty>No stock passes the engine's rules today (strong trend, beating the index). Holding cash until one does is part of the plan.</Empty> : (
            <ol className="hold-list">
              {core.picks.slice(0, 5).map((p) => (
                <li key={p.symbol}>
                  <Link to={stockPath(p.symbol)} className="hold-sym">{p.symbol}</Link>
                  <div className="hold-body"><strong>{p.name}</strong><span className="muted small">{p.reason}</span></div>
                </li>))}
              {core.picks.length > 5 && <li className="muted small hold-more"><Link to="/picks" className="link">+ {core.picks.length - 5} more picks</Link></li>}
            </ol>
          )}
          {core && !core.risk_off && (
            <p className="muted small edge-line">
              Tested since {core.edge.start} with {core.settings ?? "the default settings"}: {fmtPct(core.edge["cagr_%"], 1)} a year vs {fmtPct(core.edge["benchmark_cagr_%"], 1)} for the S&amp;P 500.
              <Hint>How this strategy would have done in the past (not a guarantee). Each stock only counts from the day it joined the S&amp;P 500, but companies that left the index are missing, so this is still a bit flattering; the "selection skill" over the same stocks held equally is {fmtPct(core.edge["skill_vs_universe_%"], 1)} a year. Details in Picks › Track record.</Hint>
            </p>
          )}
        </Card>

        <Card title={<>Changes at the last review<Hint>What changed at the last completed monthly review: stocks to buy (new in the picks), to sell (dropped out) and to keep. Reviews happen at month end, so mid-month rankings are not acted on yet.</Hint></>}>
          {!ch?.date ? <Empty>No changes yet.</Empty> : (
            <div className="changes">
              <p className="muted small">Review of {fmtDay(ch.date)}{ch.provisional_skipped ? " · next review at month end" : ""}</p>
              {([["Buy", ch.buy, "up"], ["Sell", ch.sell, "down"], ["Keep", ch.keep, ""]] as const).map(([label, list, tone]) => (
                <div key={label} className="change-row">
                  <span className={`badge ${tone}`}>{label}</span>
                  <span className="change-syms">{list.length ? list.join(" · ") : <span className="muted">None</span>}</span>
                </div>))}
            </div>
          )}
        </Card>
      </div>

      <TrackRecordCard compact />

      <div className="grid-2">
        <Card title={<>Rising most today<Hint>The S&amp;P 500 stocks up the most today. A big jump is information, not a buy signal on its own: moves backed by news tend to continue, moves without news often fade.</Hint></>}>
          {!t.gainers.length ? <Empty>Today's prices are not in yet. Movers appear once the market has traded.</Empty> : <ul className="movers">{t.gainers.map((q) => (
            <li key={q.symbol}><Link to={stockPath(q.symbol)}>{q.symbol} <span className="muted small">{q.name ?? marketName(q.symbol)}</span></Link><span className="up">{fmtPct(q.change_pct, 2)}</span></li>))}</ul>}
        </Card>
        <Card title={<>Falling most today<Hint>The S&amp;P 500 stocks down the most today. If one of your picks is here, check its stop-loss rather than reacting to one day.</Hint></>}>
          {!t.losers.length ? <Empty>Today's prices are not in yet. Movers appear once the market has traded.</Empty> : <ul className="movers">{t.losers.map((q) => (
            <li key={q.symbol}><Link to={stockPath(q.symbol)}>{q.symbol} <span className="muted small">{q.name ?? marketName(q.symbol)}</span></Link><span className="down">{fmtPct(q.change_pct, 2)}</span></li>))}</ul>}
        </Card>
      </div>
    </>
  );
}

export default function Overview() {
  const { events, status } = useLive();
  const [today, setToday] = useState<TodayBoard | null>(null);
  const [todayErr, setTodayErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.today().then((t) => { if (alive) { setToday(t); setTodayErr(null); } })
      .catch((e) => alive && setTodayErr((e as Error).message));
    load();
    const id = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const [opps, setOpps] = useState<OpportunitiesResult | null>(null);
  useEffect(() => {
    const load = () => api.opportunities().then(setOpps).catch(() => undefined);
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);
  const hot = (opps?.items ?? []).filter((o) => o.qualified).slice(0, 3);

  const ideas = hot.length > 0 && (
    <Card title={<>Invest now · {hot.length} live idea{hot.length > 1 ? "s" : ""}<Hint>Stocks moving strongly right now with news, heavy volume and the trend on their side. Open Invest now for the full plan (entry, stop-loss, target).</Hint></>}
      actions={<Link to="/now" className="link">See the plans</Link>}>
      <ul className="movers">{hot.map((o) => (
        <li key={o.symbol}>
          <Link to="/now" className="idea-main"><span><strong>{o.symbol}</strong> <span className="muted small">{o.name} · {o.direction === "long" ? "rising" : "falling"} on news</span></span>
            {o.headline && <span className="muted small ellipsis">{o.headline}</span>}</Link>
          <span className={o.direction === "long" ? "up" : "down"}>{fmtPct(o.change_pct, 1)}</span></li>))}</ul>
    </Card>
  );

  const watch = Array.from(new Set([...(status?.watchlist.map((w) => w.symbol) ?? []), ...STOCKS.map((s) => s.symbol)])).slice(0, 14);
  const { quotes } = useQuotes([...MARKETS.map((m) => m.symbol), ...watch]);
  const anyError = MARKETS.every((m) => quotes[m.symbol]?.error);

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">{new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · {greeting()}, Manuel</p>
        <h1 className="display">Today</h1>
        <p className="muted lead">Everything is already calculated: the market mood, what to hold, what changed and what is moving right now.</p>
      </section>

      {today ? <TodayBoardView t={today} ideas={ideas} /> : <>{ideas}{todayErr ? <div className="error" role="alert">Today's board is not available yet. {todayErr}</div> : <div className="empty"><Spinner /> Preparing today's board…</div>}</>}

      {anyError && <div className="error" role="alert">Market data is unreachable from this server. Check its network access to Yahoo Finance and your crypto exchange.</div>}

      {(["Indices", "Crypto", "Commodities & FX"] as const).map((g, i) => (
        <section key={g}>
          <h2 className="section-title">{g}{i === 0 && <Hint>Each card shows the price now, today's change (the colored box) and a line of the last 30 days. The line can fall while today is up: they cover different periods.</Hint>}</h2>
          <div className="mcards">
            {MARKETS.filter((m) => m.group === g).map((m) => <MarketCard key={m.symbol} symbol={m.symbol} name={m.name} q={quotes[m.symbol]} />)}
          </div>
        </section>
      ))}

      <div className="grid-3">
        <Card title={<>Watchlist<Hint>Live prices for the main markets and your watchlists. "Day" is the change since yesterday's close; the line shows the last 30 days. Tap a row to open its page.</Hint></>} className="span-2">
          <div className="table-wrap">
            <table className="watch">
              <thead><tr><th>Asset</th><th className="r">Price</th><th className="r">Day</th><th className="r hide-sm">30 days</th></tr></thead>
              <tbody>
                {watch.map((s) => {
                  const q = quotes[s];
                  return (
                    <tr key={s}>
                      <td><Link to={stockPath(s)} className="asset"><span className="avatar">{s.replace("^", "").slice(0, 2)}</span><span><strong>{s}</strong><span className="muted small">{marketName(s)}</span></span></Link></td>
                      <td className="r num">{fmtPrice(q?.price)}</td>
                      <td className={`r num ${(q?.change_pct ?? 0) >= 0 ? "up" : "down"}`}>{fmtPct(q?.change_pct, 2)}</td>
                      <td className="r hide-sm"><Sparkline data={q?.spark} width={100} height={28} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title={<>Latest alerts<Hint>The newest notifications: your own price alerts, live ideas, sudden moves and changes to the picks. The same alerts reach your browser, email and WhatsApp when those are set up.</Hint></>} actions={<Link to="/alerts" className="link">All</Link>}>
          {events.length ? (
            <ul className="movers">
              {events.slice(0, 8).map((e) => {
                const l = eventLine(e);
                return (
                  <li key={e.id}>
                    <span className="idea-main"><strong>{l.title}</strong><span className="muted small">{l.what}</span></span>
                    <span className={l.tone}>{l.value}</span>
                  </li>);
              })}
            </ul>
          ) : <Empty>No alerts yet. They appear here as soon as a stock surges or crashes.</Empty>}
        </Card>
      </div>
    </div>
  );
}
