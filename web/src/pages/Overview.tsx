import { Link } from "react-router-dom";
import { fmtPct, fmtPrice, fmtTime } from "../lib/format";
import { useLive } from "../lib/live";
import { MARKETS, STOCKS, marketName } from "../lib/markets";
import { useQuotes } from "../lib/quotes";
import type { Quote } from "../lib/types";
import { Sparkline } from "../components/Sparkline";
import { Card, Empty } from "../components/ui";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

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

export default function Overview() {
  const { events, status } = useLive();
  const watch = Array.from(new Set([...(status?.watchlist.map((w) => w.symbol) ?? []), ...STOCKS.map((s) => s.symbol)])).slice(0, 14);
  const { quotes } = useQuotes([...MARKETS.map((m) => m.symbol), ...watch]);

  const ranked = watch.map((s) => quotes[s]).filter((q): q is Quote => q?.change_pct !== undefined)
    .sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));
  const gainers = ranked.filter((q) => (q.change_pct ?? 0) > 0).slice(0, 4);
  const losers = [...ranked].reverse().filter((q) => (q.change_pct ?? 0) < 0).slice(0, 4);
  const anyError = MARKETS.every((m) => quotes[m.symbol]?.error);

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">{new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })} · {greeting()}, Manuel</p>
        <h1 className="display">Markets, live.</h1>
        <p className="muted lead">Real-time prices, alerts and a stock-selection engine built to beat the S&amp;P&nbsp;500.</p>
        <div className="hero-actions">
          <Link to="/picks" className="btn primary">This month's picks</Link>
          <Link to="/discover" className="btn">Discover stocks</Link>
        </div>
      </section>

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
                      <td><Link to={`/charts?symbol=${encodeURIComponent(s)}`} className="asset"><span className="avatar">{s.replace("^", "").slice(0, 2)}</span><span><strong>{s}</strong><span className="muted small">{marketName(s)}</span></span></Link></td>
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
        <div className="stack">
          <Card title="Top movers today">
            {ranked.length ? (
              <ul className="movers">
                {[...gainers, ...losers].map((q) => (
                  <li key={q.symbol}><Link to={`/charts?symbol=${encodeURIComponent(q.symbol)}`}>{q.symbol}</Link>
                    <span className={(q.change_pct ?? 0) >= 0 ? "up" : "down"}>{fmtPct(q.change_pct, 2)}</span></li>))}
              </ul>
            ) : <Empty>Waiting for prices…</Empty>}
          </Card>
          <Card title="Latest alerts" actions={<Link to="/alerts" className="link">All</Link>}>
            {events.length ? (
              <ul className="movers">
                {events.slice(0, 6).map((e) => (
                  <li key={e.id}>
                    <span><strong>{e.symbol}</strong> <span className="muted small">{e.type === "move" ? e.direction?.toLowerCase() : `${e.side} setup`} · {fmtTime(e.time)}</span></span>
                    {e.type === "move" ? <span className={(e.move_pct ?? 0) >= 0 ? "up" : "down"}>{fmtPct(e.move_pct, 2)}</span> : <span className={e.side === "long" ? "up" : "down"}>{e.side === "long" ? "LONG" : "SHORT"}</span>}
                  </li>))}
              </ul>
            ) : <Empty>No alerts yet. Start the engine on the Alerts page.</Empty>}
          </Card>
        </div>
      </div>
    </div>
  );
}
