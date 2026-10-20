import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { fmtNum, fmtPct, fmtPrice, fmtTime } from "../lib/format";
import { STATIC } from "../lib/snapshot";
import type { Opportunity, OpportunitiesResult, OrderPlan, PaperAccount } from "../lib/types";
import { Hint } from "../components/Hint";
import { Badge, Card, Empty, ErrorBox, Spinner } from "../components/ui";

const CATALYST: Record<string, string> = {
  earnings: "Earnings", guidance: "Guidance", analyst: "Analyst rating", deal: "Deal / M&A", contract: "Contract",
  product: "Product / approval", capital: "Buyback / dividend", legal: "Legal",
};

function InvestPanel({ o, onDone }: { o: Opportunity; onDone: (msg: string) => void }) {
  const [plan, setPlan] = useState<OrderPlan | null>(null);
  const [mode, setMode] = useState<string>("paper");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const body = { symbol: o.symbol, side: o.direction }; // prices and stop come from the server
  useEffect(() => {
    api.paperOrder({ ...body, preview: true }).then((r) => { setPlan(r.plan); setMode(r.mode); }).catch((e) => setErr((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [o.symbol]);
  const confirm = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api.paperOrder(body);
      onDone(`Paper ${o.direction === "long" ? "buy" : "short"} placed: ${fmtNum(r.plan.qty, 4)} ${o.symbol} at ${fmtPrice(r.plan.entry)}.`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="invest-panel">
      <p className="invest-mode">{mode === "paper" ? <><Badge>Paper mode</Badge> Practice money only. No real order is sent.</> : <><Badge tone="down">Live mode</Badge> Real money.</>}</p>
      {err && <div className="error">{err}</div>}
      {!plan && !err && <Spinner />}
      {plan && (
        <>
          <dl className="kv">
            <dt>{o.direction === "long" ? "Buy" : "Sell short"}</dt><dd>{fmtNum(plan.qty, 4)} × {fmtPrice(plan.entry)} = {fmtPrice(plan.value)}</dd>
            <dt>Stop-loss<Hint>If the price reaches this level, the position is closed automatically to limit the loss.</Hint></dt><dd>{fmtPrice(plan.stop)}</dd>
            <dt>Target</dt><dd>{fmtPrice(plan.target)}</dd>
            <dt>Max loss if stopped<Hint>Sized so that hitting the stop-loss costs about 1% of your practice account. That keeps any single idea from hurting you much.</Hint></dt><dd className="down">{fmtPrice(plan.max_loss)} ({fmtNum(plan.risk_pct_of_equity, 1)}% of account)</dd>
          </dl>
          <div className="row gap"><button className="btn primary" onClick={confirm} disabled={busy || STATIC}>{busy ? <Spinner /> : "Confirm paper order"}</button></div>
        </>
      )}
    </div>
  );
}

function OppCard({ o, onDone }: { o: Opportunity; onDone: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  const long = o.direction === "long";
  const rr = Math.abs(o.target - o.entry) / Math.abs(o.entry - o.stop);
  return (
    <article className={`opp ${long ? "opp-long" : "opp-short"}`}>
      <header className="opp-head">
        <div className="opp-id">
          <Link to={`/charts?symbol=${encodeURIComponent(o.symbol)}`} className="opp-sym">{o.symbol}</Link>
          <span className="muted small">{o.name}</span>
        </div>
        <div className="opp-move">
          <span className={`opp-pct ${long ? "up" : "down"}`}>{fmtPct(o.change_pct, 1)}</span>
          <span className="muted small">{fmtPrice(o.price)}</span>
        </div>
      </header>
      <div className="opp-tags">
        <Badge tone={long ? "up" : "down"}>{long ? "Rising · long idea" : "Falling · short idea"}</Badge>
        {o.catalyst && <Badge>{CATALYST[o.catalyst] ?? o.catalyst}</Badge>}
        <Badge>{fmtNum(o.rel_volume, 1)}x volume</Badge>
      </div>
      {o.headline && (
        <p className="opp-news">
          {o.headline_url ? <a href={o.headline_url} target="_blank" rel="noreferrer">{o.headline}</a> : o.headline}
          {o.headline_publisher && <span className="muted small"> · {o.headline_publisher}</span>}
        </p>
      )}
      <ul className="opp-reasons muted small">{o.reasons.slice(0, 3).map((r) => <li key={r}>{r}</li>)}</ul>
      <div className="opp-plan">
        <div><span className="kpi-label">Entry</span><span>{fmtPrice(o.entry)}</span></div>
        <div><span className="kpi-label">Stop<Hint>Where you exit if wrong. Placed beyond today's {long ? "low" : "high"} or 1.5x the normal daily range.</Hint></span><span className="down">{fmtPrice(o.stop)}</span></div>
        <div><span className="kpi-label">Target<Hint>Twice the risk: if the stop is 3% away, the target is 6% away. You can be right less than half the time and still come out ahead.</Hint></span><span className="up">{fmtPrice(o.target)}</span></div>
        <div><span className="kpi-label">Hold max</span><span>{o.hold_days} days</span></div>
      </div>
      <footer className="opp-foot">
        <span className="muted small">Reward/risk {fmtNum(rr, 1)} · score {fmtNum(o.score, 0)}/100 · valid until {fmtTime(o.expires_at)}</span>
        {o.qualified && <button className="btn primary small" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Close" : "Invest"}</button>}
      </footer>
      {open && <InvestPanel o={o} onDone={(m) => { setOpen(false); onDone(m); }} />}
    </article>
  );
}

export default function Opportunities() {
  const [data, setData] = useState<OpportunitiesResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showShort, setShowShort] = useState(true);

  const load = useCallback(() => {
    api.opportunities().then((d) => { setData(d); setErr(null); }).catch((e) => setErr((e as Error).message));
    api.paperAccount().then(setAccount).catch(() => undefined);
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 60_000); return () => clearInterval(id); }, [load]);

  const scan = async () => {
    setScanning(true);
    try { setData(await api.scanOpportunities()); } catch (e) { setErr((e as Error).message); } finally { setScanning(false); }
  };
  const items = data?.items ?? [];
  const qualified = items.filter((o) => o.qualified && (showShort || o.direction === "long"));
  const watch = items.filter((o) => !o.qualified);
  const oppPositions = (account?.positions ?? []).filter((p) => p.strategy === "opportunity");

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Live opportunities · {data ? `scanned ${fmtTime(data.as_of)}` : "scanning"} · {data?.us_market_open ? "US market open" : "US market closed: last session"}</p>
        <h1 className="display">Invest now</h1>
        <p className="muted lead">Stocks and coins making a big move right now for a real reason: news, heavy volume and a trend that agrees. Each idea comes with an entry, a stop-loss and a target.
          <Hint>Rules: move of 3%+ (5% for crypto) that is unusual for the stock, at least 1.8x normal volume, in the direction of its long-term trend and near its 52-week extreme, liquid, and backed by a relevant headline. Research shows news-driven moves tend to continue while moves without news often fade. Stock prices are about 15 minutes delayed.</Hint>
        </p>
        <div className="row gap wrap-row">
          <button className="btn" onClick={scan} disabled={scanning || STATIC}>{scanning ? <><Spinner /> Scanning</> : "Scan now"}</button>
          <label className="check"><input id="opp-short" type="checkbox" checked={showShort} onChange={(e) => setShowShort(e.target.checked)} /> Show falling (short) ideas</label>
        </div>
      </section>
      {toast && <div className="notice" role="status">{toast}</div>}
      <ErrorBox error={err} />
      {!data && !err && <div className="empty"><Spinner /> Scanning ~150 stocks and coins…</div>}

      {data && (
        <section>
          <h2 className="section-title">Ideas with a news catalyst · {qualified.length}</h2>
          {qualified.length ? <div className="opps">{qualified.map((o) => <OppCard key={`${o.symbol}${o.direction}`} o={o} onDone={(m) => { setToast(m); load(); }} />)}</div>
            : <Empty>Nothing qualifies right now. That is normal: the rules are strict on purpose. The scan repeats every 5 minutes and you get a notification when something appears.</Empty>}
        </section>
      )}

      {watch.length > 0 && (
        <details className="customize">
          <summary>Moving without news · {watch.length}<span className="muted small"> · watch only</span></summary>
          <p className="muted small">Big moves with no headline found. They often fade, so there is no Invest button.</p>
          <div className="opps">{watch.map((o) => <OppCard key={`w${o.symbol}`} o={o} onDone={() => undefined} />)}</div>
        </details>
      )}

      <Card title={<>Your practice positions<Hint>Positions opened with the Invest button, using practice (paper) money. They close automatically at the stop-loss, the target, or after about 5 trading days.</Hint></>}
        actions={account && <span className="row gap"><span className="muted small">Practice account {fmtPrice(account.equity)}</span>
          {oppPositions.length > 0 && !STATIC && <button className="btn small" onClick={async () => { await api.paperCloseAll(); load(); setToast("All practice positions closed."); }}>Close all</button>}</span>}>
        {oppPositions.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Stock</th><th>Side</th><th className="r">Qty</th><th className="r">Entry</th><th className="r">Now</th><th className="r">Stop</th><th className="r">Target</th><th className="r">P&amp;L</th></tr></thead>
            <tbody>{oppPositions.map((p) => (
              <tr key={p.symbol}><td><strong>{p.symbol}</strong></td><td className={p.side === "long" ? "up" : "down"}>{p.side}</td><td className="r num">{fmtNum(p.qty, 4)}</td>
                <td className="r num">{fmtPrice(p.entry)}</td><td className="r num">{fmtPrice(p.price ?? null)}</td><td className="r num">{fmtPrice(p.stop)}</td><td className="r num">{fmtPrice(p.target)}</td>
                <td className={`r num ${(p.pnl ?? 0) >= 0 ? "up" : "down"}`}>{fmtPrice(p.pnl ?? null)}</td></tr>))}
            </tbody></table></div>
        ) : <Empty>No practice positions yet. Press Invest on an idea to try it with practice money.</Empty>}
      </Card>
      <p className="caveat">Ideas are generated by rules, not advice. Even strong news-driven moves fail often; the stop-loss and small position size are what keep losses small. Real-money trading will need a broker connection (see the plan) and stays off until you switch it on.</p>
    </div>
  );
}
