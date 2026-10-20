import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtNum, fmtPct } from "../lib/format";
import type { PortfolioPlan } from "../lib/types";
import { Hint } from "../components/Hint";
import { Badge, Card, ErrorBox, Spinner } from "../components/ui";

const KEY = "mri.portfolio";
const RISKS = [
  { id: "cautious", label: "Cautious", hint: "50% picks, 45% S&P 500 index, 5% live ideas. Smoother ride, smaller edge." },
  { id: "balanced", label: "Balanced", hint: "70% picks, 20% live ideas, 10% S&P 500 index. The recommended mix." },
  { id: "bold", label: "Bold", hint: "75% picks, 25% live ideas, no index. Biggest potential edge, biggest swings." },
];
const ROLE = { core: "Picks", satellite: "Live idea", anchor: "S&P 500", cash: "Cash" } as const;
const ROLE_COLOR = { core: "var(--text)", satellite: "var(--up)", anchor: "#6b7489", cash: "var(--surface-3)" } as const;

function load(): { amount: string; currency: "EUR" | "USD"; risk: string; fractional: boolean } {
  try { return { amount: "10000", currency: "EUR", risk: "balanced", fractional: true, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; }
  catch { return { amount: "10000", currency: "EUR", risk: "balanced", fractional: true }; }
}

export default function Portfolio() {
  const [inp, setInp] = useState(load);
  const [plan, setPlan] = useState<PortfolioPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const money = (v: number | null | undefined) => v === null || v === undefined ? "–"
    : v.toLocaleString("en-GB", { style: "currency", currency: plan?.currency ?? inp.currency, maximumFractionDigits: 0 });

  const build = async (next = inp) => {
    setBusy(true); setErr(null);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage unavailable */ }
    try { setPlan(await api.portfolio({ ...next, amount: Number(next.amount) })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { build(); }, []);

  const lines = (plan?.lines ?? []).filter((l) => l.invested > 0);
  const m = plan?.risk_metrics ?? {};
  const t = plan?.track_record;
  const roles = plan ? (["core", "satellite", "anchor", "cash"] as const).filter((r) => (plan.by_role[r] ?? 0) > 0.0005) : [];

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Portfolio builder</p>
        <h1 className="display">My portfolio</h1>
        <p className="muted lead">Tell it how much you want to invest. It builds a diversified plan designed to beat the S&amp;P&nbsp;500: the engine's picks as the core, today's live ideas on the side, and the index for stability, with exact shares to buy.</p>
      </section>

      <Card>
        <form className="form" onSubmit={(e) => { e.preventDefault(); build(); }}>
          <label className="field"><span>Amount to invest</span>
            <input id="pf-amount" type="number" min="100" step="100" value={inp.amount} onChange={(e) => setInp({ ...inp, amount: e.target.value })} /></label>
          <label className="field"><span>Currency</span>
            <select id="pf-cur" value={inp.currency} onChange={(e) => setInp({ ...inp, currency: e.target.value as "EUR" | "USD" })}><option>EUR</option><option>USD</option></select></label>
          <div className="field"><span>Risk level<Hint>{RISKS.map((r) => <span key={r.id} style={{ display: "block" }}><strong>{r.label}:</strong> {r.hint}</span>)}</Hint></span>
            <div className="segmented" role="radiogroup" aria-label="Risk level">
              {RISKS.map((r) => <button type="button" key={r.id} role="radio" aria-checked={inp.risk === r.id} className={inp.risk === r.id ? "active" : ""} onClick={() => setInp({ ...inp, risk: r.id })}>{r.label}</button>)}
            </div>
          </div>
          <label className="check"><input id="pf-frac" type="checkbox" checked={inp.fractional} onChange={(e) => setInp({ ...inp, fractional: e.target.checked })} /> Fractional shares
            <Hint>Many brokers (Trade Republic, Revolut, IBKR) let you buy part of a share, so every euro gets invested. Untick if yours only sells whole shares.</Hint></label>
          <button className="btn primary" disabled={busy}>{busy ? <><Spinner /> Building</> : "Build my plan"}</button>
        </form>
      </Card>
      <ErrorBox error={err} />
      {!plan && busy && <div className="empty"><Spinner /> Building your plan…</div>}

      {plan && (
        <>
          {plan.core_risk_off && <div className="notice">The S&amp;P 500 is in a downtrend, so the engine keeps the picks part in cash until the trend recovers.</div>}
          <section className="alloc">
            <div className="alloc-bar" role="img" aria-label="Allocation">
              {roles.map((r) => <span key={r} style={{ flexBasis: `${plan.by_role[r] * 100}%`, background: ROLE_COLOR[r] }} />)}
            </div>
            <div className="alloc-legend">
              {roles.map((r) => (
                <span key={r}><i style={{ background: ROLE_COLOR[r] }} />{ROLE[r]} <strong>{fmtNum(plan.by_role[r] * 100, 0)}%</strong> <span className="muted">{money(r === "cash" ? plan.cash : lines.filter((l) => l.role === r).reduce((a, l) => a + l.invested, 0))}</span></span>))}
            </div>
          </section>

          <Card title={<>What to buy · {lines.length} positions<Hint>Your shopping list. Prices are in US dollars on US exchanges; amounts are converted to {plan.currency}. Place these orders at your broker, then come back monthly for the changes.</Hint></>}
            actions={<span className="muted small">{plan.currency === "EUR" ? `1 EUR = ${fmtNum(plan.fx_usd_per_unit, 4)} USD` : ""}</span>}>
            <ul className="pick-cards always">
              {lines.map((l) => (
                <li key={l.symbol}>
                  <div className="pc-top">
                    <Badge tone={l.role === "satellite" ? "up" : ""}>{ROLE[l.role]}</Badge>
                    <Link to={`/charts?symbol=${encodeURIComponent(l.symbol)}`} className="pc-name"><strong>{l.name}</strong><span className="muted small">{l.symbol}{l.sector ? ` · ${l.sector}` : ""}</span></Link>
                    <span className="pc-num"><span className="num">{money(l.invested)}</span><span className="muted small">{fmtNum(l.shares, 4)} sh × ${fmtNum(l.price, 2)}</span></span>
                  </div>
                  <p className="muted small">{fmtNum(l.invested / plan.amount * 100, 1)}% of the portfolio{l.stop ? ` · stop-loss $${fmtNum(l.stop, 2)}` : ""}{l.note ? ` · ${l.note}` : ""}</p>
                </li>))}
              {plan.cash > 0.5 && <li><div className="pc-top"><Badge>Cash</Badge><span className="pc-name"><strong>Keep in cash</strong><span className="muted small">{plan.by_role.satellite === undefined || plan.by_role.satellite < plan.mix.satellite - 0.005 ? "Waiting for live ideas, plus rounding" : "Rounding"}</span></span><span className="pc-num">{money(plan.cash)}</span></div></li>}
            </ul>
          </Card>

          <div className="grid-2">
            <Card title={<>Risk compared with the S&amp;P 500<Hint>Measured on the last 12 months of prices of exactly this mix. Volatility = how much it swings; beta = how much it moves when the S&amp;P 500 moves 1% (1.2 means about 1.2%).</Hint></>}>
              <dl className="kv">
                <dt>Volatility (yearly swing)</dt><dd>{fmtPct(m["volatility_%"], 0, false)} <span className="muted">vs {fmtPct(m["spy_volatility_%"], 0, false)}</span></dd>
                <dt>Beta</dt><dd>{fmtNum(m.beta, 2)}</dd>
                <dt>Last 12 months</dt><dd className={(m["return_1y_%"] ?? 0) >= (m["spy_return_1y_%"] ?? 0) ? "up" : "down"}>{fmtPct(m["return_1y_%"], 1)} <span className="muted">vs {fmtPct(m["spy_return_1y_%"], 1)}</span></dd>
                <dt>Worst drop in 12 months</dt><dd>{fmtPct(m["max_drawdown_1y_%"], 1)} <span className="muted">vs {fmtPct(m["spy_max_drawdown_1y_%"], 1)}</span></dd>
              </dl>
              <p className="muted small">Past 12 months of these stocks, not a forecast.</p>
            </Card>
            <Card title={<>Diversification by sector<Hint>No sector gets more than 25% of the portfolio and no single stock more than 10%. When the top picks crowd into one sector, the next-best picks from other sectors are added instead.</Hint></>}>
              <ul className="sector-bars">
                {Object.entries(plan.by_sector).map(([sec, w]) => (
                  <li key={sec}><span>{sec}</span><span className="bar"><span style={{ width: `${(w / 0.25) * 100}%` }} /></span><span className="num">{fmtNum(w * 100, 1)}%</span></li>))}
              </ul>
            </Card>
          </div>

          {plan.changes?.date && (
            <Card title={<>Changes at the last review · {plan.changes.date}<Hint>When you already hold the plan, this is what to adjust after the monthly review.</Hint></>}>
              <div className="changes inline">
                {([["Buy", plan.changes.buy, "up"], ["Sell", plan.changes.sell, "down"], ["Keep", plan.changes.keep, ""]] as const).map(([label, list, tone]) => (
                  <div key={label} className="change-row"><span className={`badge ${tone}`}>{label}</span><span className="change-syms">{list.length ? list.join(" · ") : <span className="muted">None</span>}</span></div>))}
              </div>
            </Card>
          )}

          {t && (
            <details className="customize">
              <summary>Track record of this mix<span className="muted small"> · since {t.start}: {fmtPct(t["cagr_%"], 1)}/yr vs S&amp;P 500 {fmtPct(t["spy_cagr_%"], 1)}/yr</span></summary>
              <dl className="kv">
                <dt>Yearly return (picks + index part)</dt><dd>{fmtPct(t["cagr_%"], 1)} <span className="muted">vs {fmtPct(t["spy_cagr_%"], 1)}</span></dd>
                <dt>Worst drop</dt><dd>{fmtPct(t["max_drawdown_%"], 1)} <span className="muted">vs {fmtPct(t["spy_max_drawdown_%"], 1)}</span></dd>
              </dl>
              <p className="muted small">Backtest of the picks and index parts rebalanced daily; live ideas and cash are not included. It uses today's S&amp;P 500 leaders, which flatters the past (survivorship bias). Not a promise of future returns.</p>
            </details>
          )}
          <p className="caveat">This plan is generated by rules from market data. It is information, not personal advice. Review it monthly, keep the stop-losses on live ideas, and only invest money you can leave invested for years.</p>
        </>
      )}
    </div>
  );
}
