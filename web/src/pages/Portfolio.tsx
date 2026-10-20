import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtDay, fmtNum, fmtPct, fmtPrice, stockPath } from "../lib/format";
import type { PortfolioDrift, PortfolioPlan, PortfolioRiskView } from "../lib/types";
import { STATIC } from "../lib/snapshot";
import { Hint } from "../components/Hint";
import { Badge, Card, Empty, ErrorBox, Spinner } from "../components/ui";
import { RiskCard } from "../components/RiskCard";

const KEY = "mri.portfolio";
const RISKS = [
  { id: "cautious", label: "Cautious", hint: "Risk limit: swings at most about 0.8 times as much as the S&P 500. Up to 50% picks, the rest mostly the S&P 500 index, 5% live ideas, and some cash when the picks are jumpy. Smaller losses in bad months, smaller gains in good ones." },
  { id: "balanced", label: "Balanced", hint: "Risk limit: swings at most about as much as the S&P 500 (1.0 times). Up to 70% picks, 20% live ideas, the rest the S&P 500 index. The recommended mix." },
  { id: "bold", label: "Bold", hint: "Risk limit: swings at most about 1.3 times as much as the S&P 500. Up to 75% picks and 25% live ideas. Biggest potential edge, biggest swings." },
];
const ROLE = { core: "Picks", satellite: "Live idea", anchor: "S&P 500", cash: "Cash" } as const;
// Monochrome on purpose: green and red are reserved for price direction (BRAND.md).
const ROLE_COLOR = { core: "var(--text)", satellite: "var(--text-2)", anchor: "var(--text-3)", cash: "var(--surface-3)" } as const;

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
    try { setPlan(await api.portfolio({ ...next, amount: Number(next.amount) })); } catch (e) { setErr(`Your plan could not be built. ${(e as Error).message}`); } finally { setBusy(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { build(); }, []);

  const [drift, setDrift] = useState<PortfolioDrift | null>(null);
  const [tBusy, setTBusy] = useState(false);
  const [tErr, setTErr] = useState<string | null>(null);
  useEffect(() => { api.portfolioDrift().then(setDrift).catch((e) => setTErr((e as Error).message)); }, []);
  const saveTarget = async () => {
    setTBusy(true); setTErr(null);
    // The plan on screen, not unsaved edits in the form.
    const body = plan ? { amount: plan.amount, currency: plan.currency, risk: plan.risk, fractional: inp.fractional } : { ...inp, amount: Number(inp.amount) };
    try { setDrift(await api.saveTarget(body)); } catch (e) { setTErr(`The target could not be saved. ${(e as Error).message}`); } finally { setTBusy(false); }
  };
  const removeTarget = async () => {
    setTBusy(true); setTErr(null);
    try { await api.deleteTarget(); setDrift(await api.portfolioDrift()); } catch (e) { setTErr((e as Error).message); } finally { setTBusy(false); }
  };

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
            <div className="alloc-bar" role="img" aria-label={`Allocation: ${roles.map((r) => `${ROLE[r]} ${fmtNum(plan.by_role[r] * 100, 0)}%`).join(", ")}`}>
              {roles.map((r) => <span key={r} style={{ flexBasis: `${plan.by_role[r] * 100}%`, background: ROLE_COLOR[r] }} />)}
            </div>
            <div className="alloc-legend">
              {roles.map((r) => (
                <span key={r}><i style={{ background: ROLE_COLOR[r] }} />{ROLE[r]} <strong>{fmtNum(plan.by_role[r] * 100, 0)}%</strong> <span className="muted">{money(r === "cash" ? plan.cash : lines.filter((l) => l.role === r).reduce((a, l) => a + l.invested, 0))}</span></span>))}
            </div>
          </section>

          <Card title={<>What to buy · {lines.length} positions<Hint>Your shopping list. Prices are in US dollars on US exchanges; amounts are converted to {plan.currency}. Place these orders at your broker, then come back monthly for the changes.</Hint></>}
            actions={<span className="muted small">{plan.currency === "EUR" ? `1 EUR = ${fmtNum(plan.fx_usd_per_unit, 4)} USD` : ""}</span>}>
            {!lines.length && plan.cash <= 0.5 ? <Empty>Nothing to buy with this amount. Try a larger amount or tick "Fractional shares".</Empty> : <ul className="pick-cards always">
              {lines.map((l) => (
                <li key={l.symbol}>
                  <div className="pc-top">
                    <Badge>{ROLE[l.role]}</Badge>
                    <Link to={stockPath(l.symbol)} className="pc-name"><strong>{l.name}</strong><span className="muted small">{l.symbol}{l.sector ? ` · ${l.sector}` : ""}</span></Link>
                    <span className="pc-num"><span className="num">{money(l.invested)}</span><span className="muted small">{fmtNum(l.shares, 4)} shares × ${fmtPrice(l.price)}</span></span>
                  </div>
                  <p className="muted small">{fmtNum(l.invested / plan.amount * 100, 1)}% of the portfolio{l.stop ? ` · stop-loss $${fmtNum(l.stop, 2)}` : ""}{l.note ? ` · ${l.note}` : ""}</p>
                </li>))}
              {plan.cash > 0.5 && <li><div className="pc-top"><Badge>Cash</Badge><span className="pc-name"><strong>Keep in cash</strong><span className="muted small">{[
                (plan.weighting?.to_cash ?? 0) > 0.005 ? "Kept out of the market by the risk limit" : "",
                plan.by_role.satellite === undefined || plan.by_role.satellite < plan.mix.satellite - 0.005 ? "waiting for live ideas" : "",
                "rounding"].filter(Boolean).join(", ").replace(/^./, (c) => c.toUpperCase())}</span></span><span className="pc-num">{money(plan.cash)}</span></div></li>}
            </ul>}
          </Card>

          {plan.weighting && plan.weighting.summary.length > 0 && (
            <Card title={<>Why these weights<Hint>Money is not the same as risk: 1,000 in a jumpy stock can move your plan as much as 3,000 in a calm one. So each pick gets the amount that makes its ups and downs count about equally, and each risk level has a limit on how much the whole plan may swing compared with the S&amp;P&nbsp;500. When the picks are too jumpy for that limit, money goes to the S&amp;P&nbsp;500 index first and only then to cash. Only past prices are used, never anything that happened after the plan date.</Hint></>}>
              <div className="weights-why">
                {plan.weighting.summary.map((s) => <p key={s}>{s}</p>)}
              </div>
              {plan.standard_mix && plan.weighting.budget_applied && (
                <p className="muted small">Risk limit for {RISK_LABEL[plan.risk] ?? plan.risk}: {fmtNum(plan.weighting.target_x, 1)} times the S&amp;P&nbsp;500's swings.
                  {" "}Picks {fmtNum(plan.mix.core * 100, 0)}% (standard {fmtNum(plan.standard_mix.core * 100, 0)}%), S&amp;P&nbsp;500 index {fmtNum(plan.mix.anchor * 100, 0)}% (standard {fmtNum(plan.standard_mix.anchor * 100, 0)}%).
                  <Hint>"Swings" means volatility: how much the plan's value typically moves up and down in a year. 1.0 times means about as much as simply owning the S&amp;P&nbsp;500. The limit is a ceiling, judged on the past year and on the last 3 months, whichever is jumpier; a calmer plan is left as it is.</Hint></p>
              )}
            </Card>
          )}

          <RiskCard risk={plan.risk_view} />

          <DriftCard drift={drift} busy={tBusy} err={tErr} onSave={saveTarget} onRemove={removeTarget} />

          <div className="grid-2">
            <Card title={<>Last 12 months of this mix<Hint>What exactly these holdings, with these weights, did over the past year, next to the S&amp;P 500. The worst drop is the biggest fall from a high to a low point. Past results, not a forecast.</Hint></>}>
              <dl className="kv">
                <dt>Return<Hint>Gain or loss over the last 12 months, dividends included.</Hint></dt><dd className={(m["return_1y_%"] ?? 0) >= (m["spy_return_1y_%"] ?? 0) ? "up" : "down"}>{fmtPct(m["return_1y_%"], 1)} <span className="muted">vs {fmtPct(m["spy_return_1y_%"], 1)}</span></dd>
                <dt>Worst drop<Hint>The biggest fall from a high point to a later low point within those 12 months.</Hint></dt><dd>{fmtPct(m["max_drawdown_1y_%"], 1)} <span className="muted">vs {fmtPct(m["spy_max_drawdown_1y_%"], 1)}</span></dd>
              </dl>
              <p className="muted small">Today's holdings over the past 12 months. Today's picks were chosen partly because they rose, so this flatters them.</p>
            </Card>
            <Card title={<>Diversification by sector<Hint term="diversification">No sector gets more than 25% of the portfolio and no single stock more than 10%. When the top picks crowd into one sector, the next-best picks from other sectors are added instead.</Hint></>}>
              <ul className="sector-bars">
                {Object.entries(plan.by_sector).map(([sec, w]) => (
                  <li key={sec}><span>{sec}</span><span className="bar"><span style={{ width: `${(w / 0.25) * 100}%` }} /></span><span className="num">{fmtNum(w * 100, 1)}%</span></li>))}
              </ul>
            </Card>
          </div>

          {plan.changes?.date && (
            <Card title={<>Changes at the last review · {fmtDay(plan.changes.date)}<Hint>When you already hold the plan, this is what to adjust after the monthly review.</Hint></>}>
              <div className="changes inline">
                {([["Buy", plan.changes.buy, "up"], ["Sell", plan.changes.sell, "down"], ["Keep", plan.changes.keep, ""]] as const).map(([label, list, tone]) => (
                  <div key={label} className="change-row"><span className={`badge ${tone}`}>{label}</span><span className="change-syms">{list.length ? list.join(" · ") : <span className="muted">None</span>}</span></div>))}
              </div>
            </Card>
          )}

          {t && (
            <details className="customize">
              <summary>Track record of this mix<span className="muted small"> · since {fmtDay(t.start)}: {fmtPct(t["cagr_%"], 1)}/yr vs S&amp;P 500 {fmtPct(t["spy_cagr_%"], 1)}/yr</span></summary>
              <dl className="kv">
                <dt>Yearly return<Hint>Average growth per year, dividends included, after trading costs. The live-ideas part counts as cash earning nothing.</Hint></dt><dd>{fmtPct(t["cagr_%"], 1)} <span className="muted">vs {fmtPct(t["spy_cagr_%"], 1)}</span></dd>
                {t["volatility_%"] !== undefined && <><dt>Yearly swings<Hint>Volatility: how much the value typically moved up and down in a year. This is what the risk limit controls.</Hint></dt><dd>{fmtPct(t["volatility_%"], 1, false)} <span className="muted">vs {fmtPct(t["spy_volatility_%"], 1, false)}</span></dd></>}
                {t["month_1in20_%"] !== undefined && <><dt>Bad month (1 in 20)<Hint>The loss that was exceeded in only 1 month out of 20.</Hint></dt><dd>{fmtPct(t["month_1in20_%"], 1)} <span className="muted">vs {fmtPct(t["spy_month_1in20_%"], 1)}</span></dd></>}
                <dt>Worst drop<Hint>The biggest fall from a high point to a later low point.</Hint></dt><dd>{fmtPct(t["max_drawdown_%"], 1)} <span className="muted">vs {fmtPct(t["spy_max_drawdown_%"], 1)}</span></dd>
              </dl>
              {t.method === "plan"
                ? <p className="muted small">Backtest of this risk level's picks and index parts, rebuilt every month with the same rules as today (weights by risk, risk limit), using only prices known at the time, trading at the next day's open with 0.10% costs. Stocks only count from the day they joined the S&amp;P&nbsp;500, but companies that later left it are missing, which still flatters the past. Live ideas cannot be replayed, so their share counts as cash. Not a promise of future returns.</p>
                : <p className="muted small">Rough estimate while the full backtest is being computed: the equal-weight picks and the index with today's mix, rebalanced daily; live ideas and cash earn nothing. Not a promise of future returns.</p>}
            </details>
          )}
          <p className="caveat">This plan is generated by rules from market data. It is information, not personal advice. Review it monthly, keep the stop-losses on live ideas, and only invest money you can leave invested for years.</p>
        </>
      )}
    </div>
  );
}

const RISK_LABEL: Record<string, string> = { cautious: "Cautious", balanced: "Balanced", bold: "Bold" };

function DriftCard({ drift, busy, err, onSave, onRemove }: { drift: PortfolioDrift | null; busy: boolean; err: string | null; onSave: () => void; onRemove: () => void }) {
  const t = drift?.target;
  const cur = (v: number, c = drift?.currency ?? t?.currency ?? "EUR") => v.toLocaleString("en-GB", { style: "currency", currency: c, maximumFractionDigits: 0 });
  const rows = (drift?.rows ?? []).filter((r) => r["target_%"] > 0.05 || r["current_%"] > 0.05);
  const limit = drift?.position_limit ?? 5;
  const live = drift && (drift.status === "on_target" || drift.status === "drifted");
  const [tRisk, setTRisk] = useState<PortfolioRiskView | null>(null);
  const savedAt = t?.saved_at;
  useEffect(() => {
    setTRisk(null);
    if (savedAt) api.portfolioRisk().then(setTRisk).catch(() => setTRisk(null));
  }, [savedAt]);
  const rm = tRisk?.status === "ok" ? tRisk.month : undefined;
  return (
    <Card title={<>My target and drift<Hint term="drift">Save the plan you actually bought as your target. Prices move, so over time some positions grow bigger than planned and others smaller: that gap is the drift. The app compares what you hold with your target every 30 minutes and sends you one alert (at most once a week) when it drifts too far, with what to sell and buy to get back on plan. It never buys or sells for you.</Hint></>}
      actions={t ? <button className="btn small ghost" onClick={onRemove} disabled={busy || STATIC}>Remove target</button> : undefined}>
      {t ? (
        <p className="muted small">Target saved {fmtDay(t.saved_at)}: {cur(t.amount, t.currency)}, {RISK_LABEL[t.risk] ?? t.risk}, {Object.keys(t.weights).length} positions kept for the long term.
          {" "}Live ideas ({fmtNum(t.ideas_share * 100, 0)}%) come and go within days, so they count with cash.</p>
      ) : (
        <p className="muted small">No target yet. When you have bought this plan, save it here so the app can tell you when it needs a rebalance.</p>
      )}
      {t && rm && (
        <p className="small target-risk">Risk of your target: in a bad month (1 in 20) it could lose about <strong>{cur(rm.plan.loss_95, t.currency)}</strong> ({fmtNum(rm.plan["loss_95_%"], 0)}%), against {cur(rm.spy.loss_95, t.currency)} ({fmtNum(rm.spy["loss_95_%"], 0)}%) for the S&amp;P&nbsp;500 with the same money.
          <Hint>The same simulation as "How risky is this plan?", run on the positions you saved as your target (the cash and live-ideas part counts as cash), for the amount you saved.</Hint></p>
      )}
      {drift && drift.status !== "no_target" && (
        <div className={drift.status === "drifted" ? "notice" : ""} style={{ margin: "12px 0" }}>
          <p style={{ margin: 0 }}>{drift.message}</p>
          {drift.status === "drifted" && drift.suggestion && <p style={{ margin: "8px 0 0" }}><strong>Suggestion:</strong> {drift.suggestion} <Hint>Amounts are rounded and based on what your account is worth now. Place these orders yourself if you agree; nothing is traded automatically.</Hint></p>}
        </div>
      )}
      {live && (
        <>
          <dl className="kv">
            <dt>Compared with<Hint>The practice account inside this app, or your real broker when one is connected (BROKER=... in .env).</Hint></dt><dd>{drift.source}</dd>
            <dt>Account value</dt><dd>{drift.account_value ? cur(drift.account_value) : "–"}</dd>
            <dt>Largest gap<Hint>The position furthest from its target, in percentage points: 18% held instead of 10% is a gap of 8 points. An alert is sent above {fmtNum(limit, 0)} points.</Hint></dt><dd>{fmtNum(drift.max_drift, 1)} pts</dd>
            <dt>Money off plan<Hint>The share of your money that would have to move to be exactly on plan. An alert is sent above {fmtNum(drift.total_limit ?? 10, 0)}%.</Hint></dt><dd>{fmtNum(drift.total_drift, 1)}%</dd>
          </dl>
          <ul className="drift-list" aria-label="Holdings compared with the target">
            {rows.map((r) => (
              <li key={r.symbol ?? "bucket"}>
                <span>{r.symbol ? <Link to={stockPath(r.symbol)}><strong>{r.symbol}</strong></Link> : <strong>{r.name}</strong>}{r.symbol && <span className="muted small"> · {r.in_plan ? r.name : "not in your plan"}</span>}</span>
                <span className="num muted small">{fmtNum(r["current_%"], 1)}% <span className="muted">vs {fmtNum(r["target_%"], 1)}%</span></span>
                <span className={`num ${Math.abs(r.drift) > limit && r.symbol ? "gap-big" : "muted"}`}>{r.drift >= 0 ? "+" : "−"}{fmtNum(Math.abs(r.drift), 1)} pts</span>
              </li>))}
          </ul>
        </>
      )}
      <ErrorBox error={err} />
      <div className="row gap" style={{ marginTop: 12 }}>
        <button className="btn" onClick={onSave} disabled={busy || STATIC}>{busy ? <><Spinner /> Saving</> : t ? "Replace target with this plan" : "Save this plan as my target"}</button>
      </div>
    </Card>
  );
}
