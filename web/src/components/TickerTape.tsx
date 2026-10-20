import { Link } from "react-router-dom";
import { fmtListed, fmtPct } from "../lib/format";
import { MARKETS } from "../lib/markets";
import { useQuotes } from "../lib/quotes";

export function TickerTape() {
  const { quotes } = useQuotes(MARKETS.map((m) => m.symbol), 60_000);
  const items = MARKETS.filter((m) => quotes[m.symbol]?.price !== undefined);
  if (!items.length) return null;
  // The scrolling copy is decoration: hidden from screen readers and skipped by the Tab key.
  const row = (copy: boolean) => items.map((m) => {
    const q = quotes[m.symbol];
    return (
      <Link key={m.symbol} to={`/charts?symbol=${encodeURIComponent(m.symbol)}`} className="tick" tabIndex={copy ? -1 : undefined}>
        <span className="tick-name">{m.name}</span>
        <span className="tick-price">{fmtListed(q.price, m.symbol)}</span>
        <span className={(q.change_pct ?? 0) >= 0 ? "up" : "down"}>{fmtPct(q.change_pct, 2)}</span>
      </Link>
    );
  });
  return (
    <section className="tape" aria-label="Market prices">
      <div className="tape-track">{row(false)}<span aria-hidden className="tape-dup">{row(true)}</span></div>
    </section>
  );
}
