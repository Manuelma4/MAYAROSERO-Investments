import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { asCcy, ccySign, fmtDay, fmtMoney, fmtNum, fmtPct, stockPath, type Ccy } from "../lib/format";
import { FxHint, Money, Price, useCurrency } from "../lib/currency";
import type { PortfolioDrift, PortfolioPlan, PortfolioRiskView } from "../lib/types";
import { STATIC } from "../lib/snapshot";
import { Hint } from "../components/Hint";
import { Badge, Card, Empty, ErrorBox, Spinner } from "../components/ui";
import { RiskCard } from "../components/RiskCard";

const KEY = "mri.portfolio";
const RISKS = [
  { id: "cautious", label: "Cautious", hint: "Risk limit: swings at most about 0.8 times as much as the S&P 500. About 20% momentum picks and 80% the S&P 500 index (up to 5% in live ideas), and some cash when the market is jumpy. Smaller losses in bad months, but in the past it grew more slowly than the S&P 500." },
  { id: "balanced", label: "Balanced", hint: "Risk limit: swings at most about as much as the S&P 500 (1.0 times). Up to 40% momentum picks and 60% the S&P 500 index (up to 10% in live ideas). The same mix as the Beat-the-S&P strategy; the risk limit moves money to the index when the picks get jumpy, so in the past it did about as well as the S&P 500." },
  { id: "bold", label: "Bold", hint: "Risk limit: swings at most about 1.3 times as much as the S&P 500. Up to 60% momentum picks and 40% the S&P 500 index (up to 15% in live ideas). In the past the biggest edge over the S&P 500, with deeper drops." },
  { id: "funds", label: "Simple funds", hint: "No stock picking: two funds, 60% the S&P 500 and 40% an S&P 500 momentum fund (SPMO). Rebalance back to 60/40 once a month or once a quarter. In the past a small edge over the S&P 500 with about the same swings, using real fund prices." },
];
// Consistency of the backtest (sent by the server with the track record).
type Robust = { windows?: number; "windows_beating_%"?: number; "worst_window_gap_%"?: number; years_beating?: number;
  years_total?: number; both_halves_beating?: boolean; "p_beat_5y_%"?: number; "p_beat_10y_%"?: number };
const ROLE = { core: "Picks", satellite: "Live idea", anchor: "S&P 500", fund: "Momentum fund", cash: "Cash" } as const;
// Monochrome on purpose: green and red are reserved for price direction (BRAND.md).
const ROLE_COLOR = { core: "var(--text)", satellite: "var(--text-2)", anchor: "var(--text-3)", fund: "var(--text)", cash: "var(--surface-3)" } as const;

// The plan's currency follows Settings > Display currency ("as listed" builds it in dollars, like its US stocks).
interface Inputs { amount: string; risk: string; fractional: boolean }
function load(): Inputs {
  const base: Inputs = { amount: "10000", risk: "balanced", fractional: true };
  try {
    const { amount, risk, fractional } = { ...base, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
    return { amount: String(amount), risk, fractional: !!fractional };
  } catch { return base; }
}

export default function Portfolio() {
  const [inp, setInp] = useState(load);
  const [plan, setPlan] = useState<PortfolioPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cur = useCurrency();
  const planCcy: "EUR" | "USD" = cur.pref === "EUR" ? "EUR" : "USD";
  const pc: Ccy = plan?.currency ?? planCcy;   // the currency the plan's amounts come back in
  const money = (v: number | null | undefined) => <Money v={v} from={pc} />;

  const seq = useRef(0);   // only the latest build may update the screen (a slower earlier answer is dropped)
  const build = async (next = inp) => {
    const n = ++seq.current;
    setBusy(true); setErr(null);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage unavailable */ }
    try {
      const p = await api.portfolio({ ...next, currency: planCcy, amount: Number(next.amount) });
      if (n === seq.current) setPlan(p);
    } catch (e) { if (n === seq.current) setErr(`Your plan could not be built. ${(e as Error).message}`); } finally { if (n === seq.current) setBusy(false); }
  };
  // Built on arrival, and again if the display currency changes (the server converts at its live rate).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { build(); }, [planCcy]);

  const [drift, setDrift] = useState<PortfolioDrift | null>(null);
  const [tBusy, setTBusy] = useState(false);
  const [tErr, setTErr] = useState<string | null>(null);
  useEffect(() => { api.portfolioDrift().then(setDrift).catch((e) => setTErr((e as Error).message)); }, []);
  const saveTarget = async () => {
    setTBusy(true); setTErr(null);
    // The plan on screen, not unsaved edits in the form.
    const body = plan ? { amount: plan.amount, currency: plan.currency, risk: plan.risk, fractional: inp.fractional } : { ...inp, currency: planCcy, amount: Number(inp.amount) };
    try { setDrift(await api.saveTarget(body)); } catch (e) { setTErr(`The target could not be saved. ${(e as Error).message}`); } finally { setTBusy(false); }
  };
  const removeTarget = async () => {
    setTBusy(true); setTErr(null);
    try { await api.deleteTarget(); setDrift(await api.portfolioDrift()); } catch (e) { setTErr((e as Error).message); } finally { setTBusy(false); }
  };

  const lines = (plan?.lines ?? []).filter((l) => l.invested > 0);
  const m = plan?.risk_metrics ?? {};
  const t = plan?.track_record;
  const rb = (t as { robustness?: Robust } | undefined)?.robustness;
  const funds = plan?.risk === "funds";
  const roles = plan ? (["core", "fund", "satellite", "anchor", "cash"] as const).filter((r) => (plan.by_role[r] ?? 0) > 0.0005) : [];

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Portfolio builder</p>
        <h1 className="display">My portfolio</h1>
        <p className="muted lead">Tell it how much you want to invest. It builds a diversified plan designed to beat the S&amp;P&nbsp;500: the engine's picks as the core, today's live ideas on the side, and the index for stability, with exact shares to buy.</p>
      </section>

      <Card>
        <form className="form" onSubmit={(e) => { e.preventDefault(); build(); }}>
          <label className="field" style={{ minWidth: 200 }}><span>Amount to invest, {ccySign(planCcy)}<Hint term="exchange-rate">The money you want to put in, in {planCcy === "EUR" ? "euros" : "US dollars"}{cur.pref === "listed" ? " (the currency of the plan's US stocks)" : ""}. Change it in Settings, Display currency.{planCcy === "EUR" ? " The US stocks are bought in dollars, so the plan converts at today's EUR/USD rate." : ""}</Hint></span>
            <input id="pf-amount" type="number" min="100" step="100" value={inp.amount} onChange={(e) => setInp({ ...inp, amount: e.target.value })} /></label>
          <div className="field" style={{ minWidth: "fit-content" }}><span>Risk level<Hint>{RISKS.map((r) => <span key={r.id} style={{ display: "block" }}><strong>{r.label}:</strong> {r.hint}</span>)}</Hint></span>
            <div className="segmented risk-seg" role="radiogroup" aria-label="Risk level">
              {RISKS.map((r) => <button type="button" key={r.id} role="radio" aria-checked={inp.risk === r.id} className={inp.risk === r.id ? "active" : ""} onClick={() => setInp({ ...inp, risk: r.id })}>{r.label}</button>)}
            </div>
          </div>
          <label className="check"><input id="pf-frac" type="checkbox" checked={inp.risk === "funds" ? false : inp.fractional} disabled={inp.risk === "funds"} onChange={(e) => setInp({ ...inp, fractional: e.target.checked })} /> Fractional shares
            <Hint>{inp.risk === "funds" ? "Simple funds is always built in whole shares of each fund; what is left over is only the rounding." : "Many brokers (Trade Republic, Revolut, IBKR) let you buy part of a share, so every euro gets invested. Untick if yours only sells whole shares."}</Hint></label>
          <button className="btn primary" disabled={busy}>{busy ? <><Spinner /> Building</> : "Build my plan"}</button>
        </form>
      </Card>
      <ErrorBox error={err} />
      {!plan && busy && <div className="empty"><Spinner /> Building your plan…</div>}

      {plan && (
        <>
          {plan.eu_note && <div className="notice"><strong>Buying from Europe.</strong> {plan.eu_note}</div>}
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

          <Card title={<>What to buy · {lines.length} positions<Hint term="exchange-rate">Your shopping list. Each share price is in the currency the stock trades in (dollars for US stocks), with the converted value next to it; the amounts are in {cur.target(pc) === "EUR" ? "euros" : "dollars"}{plan.currency === "EUR" ? `, converted at 1 € = ${fmtMoney(plan.fx_usd_per_unit, "USD", 4)}` : ""}. Your broker's rate and fees may differ a little. Place these orders at your broker, then come back monthly for the changes.</Hint></>}
            actions={plan.currency === "EUR" ? <span className="muted small fx-rate">1 € = {fmtMoney(plan.fx_usd_per_unit, "USD", 4)}</span> : <FxHint from={pc} />}>
            {!lines.length && plan.cash <= 0.5 ? <Empty>Nothing to buy with this amount. Try a larger amount or tick "Fractional shares".</Empty> : <ul className="pick-cards always">
              {lines.map((l) => (
                <li key={l.symbol}>
                  <div className="pc-top">
                    <Badge>{ROLE[l.role]}</Badge>
                    <Link to={stockPath(l.symbol)} className="pc-name"><strong>{l.name}</strong><span className="muted small">{l.symbol}{l.sector ? ` · ${l.sector}` : ""}</span></Link>
                    <span className="pc-num"><span className="num">{money(l.invested)}</span><span className="muted small">{fmtNum(l.shares, 4)} shares × <Price v={l.price} symbol={l.symbol} alt="hover" /></span></span>
                  </div>
                  <p className="muted small">{fmtNum(l.invested / plan.amount * 100, 1)}% of the portfolio{l.stop ? <> · stop-loss <Price v={l.stop} symbol={l.symbol} /></> : ""}{l.note ? ` · ${l.note}` : ""}</p>
                </li>))}
              {plan.cash > 0.5 && <li><div className="pc-top"><Badge>Cash</Badge><span className="pc-name"><strong>Keep in cash</strong><span className="muted small">{funds ? "Rounding to whole shares" : [
                (plan.weighting?.to_cash ?? 0) > 0.005 ? "Kept out of the market by the risk limit" : "",
                "rounding"].filter(Boolean).join(", ").replace(/^./, (c) => c.toUpperCase())}</span></span><span className="pc-num">{money(plan.cash)}</span></div></li>}
            </ul>}
          </Card>

          {plan.weighting?.summary?.length ? (
            <Card title={<>Why these weights<Hint>{funds ? "A fixed mix: no forecasts, no stock picking, nothing to time. The momentum fund does the stock choosing by its own published rules; you only bring the two funds back to 60/40 from time to time." : <>Money is not the same as risk: 1,000 in a jumpy stock can move your plan as much as 3,000 in a calm one. So each pick gets the amount that makes its ups and downs count about equally, and each risk level has a limit on how much the whole plan may swing compared with the S&amp;P&nbsp;500. When the picks are too jumpy for that limit, money goes to the S&amp;P&nbsp;500 index first and only then to cash. Only past prices are used, never anything that happened after the plan date.</>}</Hint></>}>
              <div className="weights-why">
                {plan.weighting.summary.map((s) => <p key={s}>{s}</p>)}
              </div>
              {plan.standard_mix && plan.weighting.budget_applied && (
                <p className="muted small">Risk limit for {RISK_LABEL[plan.risk] ?? plan.risk}: {fmtNum(plan.weighting.target_x, 1)} times the S&amp;P&nbsp;500's swings.
                  {" "}Picks {fmtNum(plan.mix.core * 100, 0)}% (standard {fmtNum(plan.standard_mix.core * 100, 0)}%), S&amp;P&nbsp;500 index {fmtNum(plan.mix.anchor * 100, 0)}% (standard {fmtNum(plan.standard_mix.anchor * 100, 0)}%).
                  <Hint>"Swings" means volatility: how much the plan's value typically moves up and down in a year. 1.0 times means about as much as simply owning the S&amp;P&nbsp;500. The limit is a ceiling, judged on the past year and on the last 3 months, whichever is jumpier; a calmer plan is left as it is.</Hint></p>
              )}
            </Card>
          ) : null}

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
            {!funds && <Card title={<>Diversification by sector<Hint term="diversification">No sector gets more than 25% of the portfolio and no single stock more than 10%. When the top picks crowd into one sector, the next-best picks from other sectors are added instead.</Hint></>}>
              <ul className="sector-bars">
                {Object.entries(plan.by_sector).map(([sec, w]) => (
                  <li key={sec}><span>{sec}</span><span className="bar"><span style={{ width: `${(w / 0.25) * 100}%` }} /></span><span className="num">{fmtNum(w * 100, 1)}%</span></li>))}
              </ul>
            </Card>}
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
                <dt>Yearly return<Hint>Average growth per year, dividends included, after trading costs.{funds ? "" : " Measured on months without live ideas: their share is invested in the picks and the index, as the plan does today when there are no ideas."}</Hint></dt><dd>{fmtPct(t["cagr_%"], 1)} <span className="muted">vs {fmtPct(t["spy_cagr_%"], 1)}</span></dd>
                {t["volatility_%"] !== undefined && <><dt>Yearly swings<Hint>Volatility: how much the value typically moved up and down in a year. This is what the risk limit controls.</Hint></dt><dd>{fmtPct(t["volatility_%"], 1, false)} <span className="muted">vs {fmtPct(t["spy_volatility_%"], 1, false)}</span></dd></>}
                {t["month_1in20_%"] !== undefined && <><dt>Bad month (1 in 20)<Hint>The loss that was exceeded in only 1 month out of 20.</Hint></dt><dd>{fmtPct(t["month_1in20_%"], 1)} <span className="muted">vs {fmtPct(t["spy_month_1in20_%"], 1)}</span></dd></>}
                <dt>Worst drop<Hint>The biggest fall from a high point to a later low point.</Hint></dt><dd>{fmtPct(t["max_drawdown_%"], 1)} <span className="muted">vs {fmtPct(t["spy_max_drawdown_%"], 1)}</span></dd>
                {t.sharpe !== undefined && t.spy_sharpe !== undefined && <><dt>Return per unit of risk<Hint>The Sharpe ratio: yearly return divided by yearly swings (cash counted as earning 0%). Higher means more growth for the same ups and downs.</Hint></dt><dd>{fmtNum(t.sharpe, 2)} <span className="muted">vs {fmtNum(t.spy_sharpe, 2)}</span></dd></>}
                {rb?.["windows_beating_%"] !== undefined && <><dt>3-year periods ahead<Hint>Every 3-year stretch of the backtest, starting each month: in how many of them this mix grew faster than the S&amp;P&nbsp;500. Above 50% means it won more often than it lost; the periods overlap, so this is weaker evidence than it looks.</Hint></dt><dd>{fmtNum(rb["windows_beating_%"], 0)}% <span className="muted">of {rb.windows}</span></dd></>}
                {rb?.["p_beat_10y_%"] !== undefined && <><dt>Odds over 10 years<Hint>We re-shuffled the backtest's months in yearly blocks thousands of times and counted how often this mix ended ahead of the S&amp;P&nbsp;500 after 5 and 10 years. It assumes the future looks like 2015-2026, so treat it as optimistic, not a promise.</Hint></dt><dd>{fmtNum(rb["p_beat_10y_%"], 0)}% <span className="muted">5 years: {fmtNum(rb["p_beat_5y_%"] ?? 0, 0)}%</span></dd></>}
              </dl>
              {t.method === "funds"
                ? <p className="muted small">Backtest with the real prices of the two funds (dividends included) from SPMO's first trading day, {fmtDay(t.start)}: back to 60/40 at each month end, trading at the next day's open with 0.10% costs. Real funds, so no survivorship bias, but it is one decade with a strong momentum run (big US tech), and about +1 to +2% a year over the S&amp;P&nbsp;500 is a small edge that can vanish for years. The UCITS funds a European broker offers follow different indexes, so their past differs. Not a promise of future returns.</p>
                : t.method === "plan"
                ? <p className="muted small">Backtest of this risk level's picks and index parts, rebuilt every month with the same rules as today (weights by risk, risk limit), using only prices known at the time, trading at the next day's open with 0.10% costs. Stocks only count from the day they joined the S&amp;P&nbsp;500, but companies that later left it are missing, which still flatters the past. Live ideas cannot be replayed, so their share is invested in the picks and the index, as the plan does on a day without ideas. Not a promise of future returns.</p>
                : <p className="muted small">Rough estimate while the full backtest is being computed: the equal-weight picks and the index with today's mix, rebalanced daily; live ideas and cash earn nothing. Not a promise of future returns.</p>}
            </details>
          )}
          <p className="caveat">This plan is generated by rules from market data. It is information, not personal advice. Review it monthly, keep the stop-losses on live ideas, and only invest money you can leave invested for years.</p>
        </>
      )}
    </div>
  );
}

const RISK_LABEL: Record<string, string> = { cautious: "Cautious", balanced: "Balanced", bold: "Bold", funds: "Simple funds" };

function DriftCard({ drift, busy, err, onSave, onRemove }: { drift: PortfolioDrift | null; busy: boolean; err: string | null; onSave: () => void; onRemove: () => void }) {
  const t = drift?.target;
  const dc: Ccy = asCcy(drift?.currency ?? t?.currency) ?? "EUR";   // drift amounts come in the target's currency
  const fx = useCurrency();
  const cur = (v: number, c: string = dc) => <Money v={v} from={asCcy(c) ?? dc} />;
  // Rebuilt here rather than the server's sentence, so the amounts follow the display currency (largest trades first).
  const pick = (xs: { symbol: string; amount: number }[] | undefined, verb: string) =>
    (xs ?? []).slice().sort((a, b) => b.amount - a.amount).map((x) => ({ ...x, verb }));
  const sells = pick(drift?.sell, "sell"), buys = pick(drift?.buy, "buy");
  const top = [...sells.slice(0, 3), ...buys.slice(0, 3)];
  const more = sells.length + buys.length - top.length;
  const suggestion = top.length
    ? (top.map((x) => `${x.verb} about ${fx.money(x.amount, dc)} of ${x.symbol}`).join(", ")
      + (more > 0 ? ` (and ${more} smaller trade${more > 1 ? "s" : ""})` : "") + ".").replace(/^./, (c) => c.toUpperCase())
    : drift?.suggestion;
  const rows = (drift?.rows ?? []).filter((r) => r["target_%"] > 0.05 || r["current_%"] > 0.05);
  const limit = drift?.position_limit ?? 5;
  const live = drift && (drift.status === "on_target" || drift.status === "drifted");
  const [tRisk, setTRisk] = useState<PortfolioRiskView | null>(null);
  const savedAt = t?.saved_at;
  useEffect(() => {
    let alive = true;
    setTRisk(null);
    if (savedAt) api.portfolioRisk().then((r) => alive && setTRisk(r)).catch(() => alive && setTRisk(null));
    return () => { alive = false; };
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
          {drift.status === "drifted" && suggestion && <p style={{ margin: "8px 0 0" }}><strong>Suggestion:</strong> {suggestion} <Hint term={fx.converts(dc) ? "exchange-rate" : undefined}>Amounts are rounded and based on what your account is worth now.{fx.converts(dc) ? ` ${fx.fxNote(dc)}` : ""} Place these orders yourself if you agree; nothing is traded automatically.</Hint></p>}
        </div>
      )}
      {live && (
        <>
          <dl className="kv">
            <dt>Compared with<Hint>The practice account inside this app, or your real broker when one is connected (BROKER=... in .env).</Hint></dt><dd>{drift.source}</dd>
            <dt>Account value<FxHint from={dc} /></dt><dd>{drift.account_value ? cur(drift.account_value) : "–"}</dd>
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
