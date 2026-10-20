import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { fmtNum, fmtPct, fmtPrice } from "../lib/format";
import type { ForecastResult } from "../lib/types";
import { LinesChart, SERIES, type Overlay } from "./charts";
import { Hint } from "./Hint";
import { Spinner } from "./ui";
import { cssVar } from "../lib/theme";

/** Monte Carlo fan chart + volume profile for one symbol. */
export function ForecastPanel({ symbol, horizon }: { symbol: string; horizon: number }) {
  const [f, setF] = useState<ForecastResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setF(null); setErr(null);
    api.forecast(symbol, horizon).then(setF).catch((e) => setErr((e as Error).message));
  }, [symbol, horizon]);

  const fan = useMemo<Overlay[]>(() => {
    if (!f) return [];
    const t = f.monte_carlo.fan_times;
    const line = (k: "p5" | "p25" | "p50" | "p75" | "p95") => f.monte_carlo.fan[k].map((value, i) => ({ time: t[i], value }));
    return [
      { data: line("p95"), color: SERIES.band, dashed: true, title: "95%" },
      { data: line("p75"), color: SERIES.ema20, width: 1, title: "75%" },
      { data: line("p50"), color: cssVar("--text"), width: 2, title: "Median" },
      { data: line("p25"), color: SERIES.ema20, width: 1, title: "25%" },
      { data: line("p5"), color: SERIES.band, dashed: true, title: "5%" },
    ];
  }, [f]);

  if (err) return <p className="muted small">{err}</p>;
  if (!f) return <div className="muted small"><Spinner /> Simulating 5,000 price paths…</div>;
  const mc = f.monte_carlo;
  const vp = f.volume_profile;
  const maxShare = Math.max(...vp.bins.map((b) => b.share), 0.0001);
  const days = horizon === 1 ? "tomorrow" : `in ${horizon} trading days`;
  return (
    <div className="forecast">
      <div className="fc-stats">
        <div><span className="kpi-label">Chance higher {days}<Hint>Share of 5,000 simulated futures that end above today's price. The simulation uses the stock's real past daily moves and today's volatility, so it describes risk and range more than direction.</Hint></span><strong>{fmtPct(mc.p_up * 100, 0, false)}</strong></div>
        <div><span className="kpi-label">Likely range<Hint>90% of simulated outcomes land inside this range (between the 5th and 95th percentile).</Hint></span><strong>{fmtPrice(mc.range_5_95[0])} – {fmtPrice(mc.range_5_95[1])}</strong></div>
        <div><span className="kpi-label">Chance of ±5% move</span><strong><span className="up">{fmtPct(mc["p_move_up_5%"] * 100, 0, false)}</span> / <span className="down">{fmtPct(mc["p_move_down_5%"] * 100, 0, false)}</span></strong></div>
        <div><span className="kpi-label">Volatility (yearly)</span><strong>{fmtNum(mc["annual_vol_%"], 0)}%</strong></div>
      </div>
      <LinesChart series={fan} height={220} />
      {vp.poc !== null && (
        <div className="vprofile">
          <span className="kpi-label">Volume profile · last 120 days<Hint>Where most shares changed hands. The busiest price (point of control) and the zone holding 70% of volume (value area) often act as support or resistance.</Hint></span>
          <ul>
            {[...vp.bins].reverse().map((b) => {
              const inVA = vp.value_area[0] !== null && b.price >= (vp.value_area[0] ?? 0) && b.price <= (vp.value_area[1] ?? 0);
              const isPoc = Math.abs(b.price - (vp.poc ?? 0)) < 1e-9;
              const here = Math.abs(b.price - mc.last_price) <= (vp.bins[1]?.price - vp.bins[0]?.price) / 2;
              return (
                <li key={b.price} className={`${isPoc ? "poc" : ""} ${here ? "here" : ""}`}>
                  <span className="num">{fmtPrice(b.price)}</span>
                  <span className="vbar"><span style={{ width: `${(b.share / maxShare) * 100}%`, opacity: inVA ? 1 : 0.45 }} /></span>
                  <span className="muted small">{isPoc ? "most traded" : here ? "price now" : ""}</span>
                </li>);
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
