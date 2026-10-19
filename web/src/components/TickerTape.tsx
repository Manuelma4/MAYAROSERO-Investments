import { Link } from "react-router-dom";
import { fmtPct, fmtPrice } from "../lib/format";
import { MARKETS } from "../lib/markets";
import { useQuotes } from "../lib/quotes";

export function TickerTape() {
  const { quotes } = useQuotes(MARKETS.map((m) => m.symbol), 60_000);
  const items = MARKETS.filter((m) => quotes[m.symbol]?.price !== undefined);
  if (!items.length) return null;
  const row = items.map((m) => {
    const q = quotes[m.symbol];
    return (
      <Link key={m.symbol} to={`/charts?symbol=${encodeURIComponent(m.symbol)}`} className="tick">
        <span className="tick-name">{m.name}</span>
        <span className="tick-price">{fmtPrice(q.price)}</span>
        <span className={(q.change_pct ?? 0) >= 0 ? "up" : "down"}>{fmtPct(q.change_pct, 2)}</span>
      </Link>
    );
  });
  return (
    <div className="tape" aria-label="Market prices">
      <div className="tape-track">{row}<span aria-hidden className="tape-dup">{row}</span></div>
    </div>
  );
}
