import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtPct, fmtPrice, fmtTime, stockPath } from "../lib/format";
import { useLive } from "../lib/live";
import { MARKETS, STOCKS, marketName } from "../lib/markets";
import { useQuotes } from "../lib/quotes";
import type { OpportunitiesResult, Quote, TodayBoard } from "../lib/types";
import { Hint } from "../components/Hint";
import { Sparkline } from "../components/Sparkline";
import { Card, Empty, Spinner } from "../components/ui";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
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

function TodayBoardView({ t }: { t: TodayBoard }) {
  const core = t.core;
  const ch = core?.changes;
  return (
    <>
      {t.mood && <section className="mood">
        <div className="mood-head">
          <span className="kpi-label">Market mood<Hint>Combines the S&amp;P 500's trend (above or below its 200-day average), how many leading stocks are rising, and the fear index (VIX). It tells you whether the market wind is at your back.</Hint></span>
          <span className={`mood-label ${MOOD_TONE[t.mood.label]}`}>{t.mood.label}</span>
        </div>
        <p className="mood-text">{t.mood.explanation}</p>
        <p className="mood-advice">{t.mood.advice}</p>
      </section>}

      <div className="grid-3">
        <Card className="span-2" title={<>What to hold now<Hint>The engine's current top picks among the S&amp;P 500 stocks: strong 12-month performance, beating the index, in an uptrend, with calmer price action. Split your money equally between them and review once a month.</Hint></>}
          actions={<Link to="/picks" className="link">All picks</Link>}>
          {!core ? <Empty>Picks are being computed.</Empty> : core.risk_off ? (
            <div className="notice">The S&amp;P 500 is in a downtrend, so the engine suggests holding cash until it recovers.</div>
          ) : (
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
              <Hint>How this strategy would have done in the past (not a guarantee). Part of that lead comes from using today's index members; the honest "selection skill" is {fmtPct(core.edge["skill_vs_universe_%"], 1)} a year. Details in Picks › Track record.</Hint>
            </p>
          )}
        </Card>

        <Card title={<>Changes at the last review<Hint>What changed at the last completed monthly review: stocks to buy (new in the picks), to sell (dropped out) and to keep. Reviews happen at month end, so mid-month rankings are not acted on yet.</Hint></>}>
          {!ch?.date ? <Empty>No changes yet.</Empty> : (
            <div className="changes">
              <p className="muted small">Review of {ch.date}{ch.provisional_skipped ? " · next review at month end" : ""}</p>
              {([["Buy", ch.buy, "up"], ["Sell", ch.sell, "down"], ["Keep", ch.keep, ""]] as const).map(([label, list, tone]) => (
                <div key={label} className="change-row">
                  <span className={`badge ${tone}`}>{label}</span>
                  <span className="change-syms">{list.length ? list.join(" · ") : <span className="muted">None</span>}</span>
                </div>))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid-2">
        <Card title={<>Rising most today<Hint>The S&amp;P 500 stocks up the most today. A big jump is information, not a buy signal on its own: moves backed by news tend to continue, moves without news often fade.</Hint></>}>
          <ul className="movers">{t.gainers.map((q) => (
            <li key={q.symbol}><Link to={stockPath(q.symbol)}>{q.symbol} <span className="muted small">{q.name ?? marketName(q.symbol)}</span></Link><span className="up">{fmtPct(q.change_pct, 2)}</span></li>))}</ul>
        </Card>
        <Card title={<>Falling most today<Hint>The S&amp;P 500 stocks down the most today. If one of your picks is here, check its stop-loss rather than reacting to one day.</Hint></>}>
          <ul className="movers">{t.losers.map((q) => (
            <li key={q.symbol}><Link to={stockPath(q.symbol)}>{q.symbol} <span className="muted small">{q.name ?? marketName(q.symbol)}</span></Link><span className="down">{fmtPct(q.change_pct, 2)}</span></li>))}</ul>
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

      {hot.length > 0 && (
        <Card title={<>Invest now · {hot.length} live idea{hot.length > 1 ? "s" : ""}<Hint>Stocks moving strongly right now with news, heavy volume and the trend on their side. Open Invest now for the full plan (entry, stop-loss, target).</Hint></>}
          actions={<Link to="/now" className="link">Open</Link>}>
          <ul className="movers">{hot.map((o) => (
            <li key={o.symbol}><Link to="/now">{o.symbol} <span className="muted small">{o.headline ?? o.name}</span></Link>
              <span className={o.direction === "long" ? "up" : "down"}>{fmtPct(o.change_pct, 1)}</span></li>))}</ul>
        </Card>
      )}

      {today ? <TodayBoardView t={today} /> : <div className="empty">{todayErr ? todayErr : <><Spinner /> Preparing today's board…</>}</div>}

      {anyError && <div className="error">Market data is unreachable from this server. Check its network access to Yahoo Finance and your crypto exchange.</div>}

      {(["Indices", "Crypto", "Commodities & FX"] as const).map((g) => (
        <section key={g}>
          <h2 className="section-title">{g}</h2>
          <div className="mcards">
            {MARKETS.filter((m) => m.group === g).map((m) => <MarketCard key={m.symbol} symbol={m.symbol} name={m.name} q={quotes[m.symbol]} />)}
          </div>
        </section>
      ))}

      <div className="grid-3">
        <Card title="Watchlist" className="span-2">
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
        <Card title="Latest alerts" actions={<Link to="/alerts" className="link">All</Link>}>
          {events.length ? (
            <ul className="movers">
              {events.slice(0, 8).map((e) => (
                <li key={e.id}>
                  <span><strong>{e.symbol}</strong> <span className="muted small">{e.type === "move" ? e.direction?.toLowerCase() : `${e.side} setup`} · {fmtTime(e.time)}</span></span>
                  {e.type === "move" ? <span className={(e.move_pct ?? 0) >= 0 ? "up" : "down"}>{fmtPct(e.move_pct, 2)}</span> : <span className={e.side === "long" ? "up" : "down"}>{e.side === "long" ? "LONG" : "SHORT"}</span>}
                </li>))}
            </ul>
          ) : <Empty>No alerts yet. They appear here as soon as a stock surges or crashes.</Empty>}
        </Card>
      </div>
    </div>
  );
}
