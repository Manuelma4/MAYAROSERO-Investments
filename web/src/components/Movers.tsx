import { Link } from "react-router-dom";
import { fmtNum, fmtPct, fmtPrice, stockPath } from "../lib/format";
import type { MoversBoard, MoverRow } from "../lib/types";
import { Hint } from "./Hint";
import { Card } from "./ui";

function Row({ m }: { m: MoverRow }) {
  return (
    <li className="mover-row">
      <Link className="link" to={stockPath(m.symbol)}><strong>{m.symbol}</strong></Link>
      <span className="muted small mover-name">{m.name}</span>
      <span className="num">{fmtPrice(m.price)}</span>
      <span className={`num ${m.change_pct >= 0 ? "up" : "down"}`}>{fmtPct(m.change_pct, 1)}</span>
      <span className={`num small ${m.rel_volume && m.rel_volume >= 1.8 ? "" : "muted"}`}>{m.rel_volume ? `${fmtNum(m.rel_volume, 1)}x vol` : "–"}</span>
    </li>
  );
}

/** The whole S&P 500 ranked by today's move (refreshed with every 5-minute scan). */
export function SP500Movers({ board }: { board?: MoversBoard | null }) {
  if (!board || !board.count) return null;
  return (
    <Card title={<>S&amp;P 500 movers today<Hint>All {board.count} US stocks we follow, ranked by today's move versus yesterday's close. "Vol" compares today's volume with a normal day at this hour (2x = twice the usual): big moves on heavy volume matter more. {board["breadth_up_%"] !== null ? `${fmtNum(board["breadth_up_%"], 0)}% of them are up today.` : ""} Prices are about 15 minutes delayed.</Hint></>}
      actions={board["breadth_up_%"] !== null && <span className="muted small">{fmtNum(board["breadth_up_%"], 0)}% up</span>}>
      <div className="grid-2 movers-board">
        <div><h3 className="up small-title">Surging</h3><ol className="movers-list">{board.gainers.slice(0, 10).map((m) => <Row key={m.symbol} m={m} />)}</ol></div>
        <div><h3 className="down small-title">Falling</h3><ol className="movers-list">{board.losers.slice(0, 10).map((m) => <Row key={m.symbol} m={m} />)}</ol></div>
      </div>
    </Card>
  );
}
