import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { asCcy, fmtNum, fmtPct, fmtTime } from "../lib/format";
import { FxHint, Money, Price } from "../lib/currency";
import { STATIC } from "../lib/snapshot";
import type { BrokerPositions, BrokerStatus, Opportunity, OpportunitiesResult, PaperAccount } from "../lib/types";
import { AIDesk } from "../components/AIDesk";
import { ModeBadge, OrderTicket, brokerLabel } from "../components/Trading";
import { Hint } from "../components/Hint";
import { SP500Movers } from "../components/Movers";
import { Badge, Card, Empty, ErrorBox, Spinner } from "../components/ui";

const CATALYST: Record<string, string> = {
  earnings: "Earnings", guidance: "Guidance", analyst: "Analyst rating", deal: "Deal / M&A", contract: "Contract",
  product: "Product / approval", capital: "Buyback / dividend", legal: "Legal",
};

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
          <Price className="muted small" v={o.price} symbol={o.symbol} />
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
        <div><span className="kpi-label">Entry<Hint>The price to buy at (or sell short at), close to the current price.</Hint></span><Price v={o.entry} symbol={o.symbol} alt="hover" /></div>
        <div><span className="kpi-label">Stop<Hint term="stop-loss">Where you exit if wrong. Placed beyond today's {long ? "low" : "high"} or 1.5x the normal daily range.</Hint></span><Price className="down" v={o.stop} symbol={o.symbol} alt="hover" /></div>
        <div><span className="kpi-label">Target<Hint term="target">Twice the risk: if the stop is 3% away, the target is 6% away. You can be right less than half the time and still come out ahead.</Hint></span><Price className="up" v={o.target} symbol={o.symbol} alt="hover" /></div>
        <div><span className="kpi-label">Hold max<Hint>A short-term idea: if neither the stop nor the target is reached, close it after this many trading days.</Hint></span><span>{o.hold_days} days</span></div>
      </div>
      <p className="muted small opp-meta">Reward/risk {fmtNum(rr, 1)} · score {fmtNum(o.score, 0)}/100 · valid until {fmtTime(o.expires_at)}
        <Hint term="reward-risk">Reward/risk: the possible gain is {fmtNum(rr, 1)} times the possible loss. Score: how strongly the idea meets the rules (higher is better). After the time shown the idea expires and is no longer offered.</Hint></p>
      {o.qualified && (
        <footer className="opp-foot">
          <button className="btn primary" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Close" : "Invest"}</button>
          <AIDesk symbol={o.symbol} />
        </footer>
      )}
      {open && <OrderTicket o={o} onDone={(m) => { setOpen(false); onDone(m); }} />}
    </article>
  );
}

export default function Opportunities() {
  const [data, setData] = useState<OpportunitiesResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [broker, setBroker] = useState<BrokerStatus | null>(null);
  const [held, setHeld] = useState<BrokerPositions | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showShort, setShowShort] = useState(true);

  const load = useCallback(() => {
    api.opportunities().then((d) => { setData(d); setErr(null); }).catch((e) => setErr((e as Error).message));
    api.paperAccount().then(setAccount).catch(() => undefined);
    api.brokerStatus().then((b) => {
      setBroker(b);
      if (b.broker !== "paper" && b.connected) api.brokerPositions().then(setHeld).catch(() => undefined);
    }).catch(() => undefined);
  }, []);
  useEffect(() => { load(); const id = setInterval(load, 60_000); return () => clearInterval(id); }, [load]);

  const scan = async () => {
    setScanning(true);
    try { setData(await api.scanOpportunities()); } catch (e) { setErr((e as Error).message); } finally { setScanning(false); }
  };
  const items = data?.items ?? [];
  const qualified = items.filter((o) => o.qualified && (showShort || o.direction === "long"));
  const watch = items.filter((o) => !o.qualified);
  const brokerCcy = asCcy(broker?.currency) ?? "USD";   // the broker account's currency (the practice account is in dollars)
  const oppPositions = (account?.positions ?? []).filter((p) => p.strategy === "opportunity");

  return (
    <div className="page">
      <section className="hero-x">
        <p className="eyebrow">Live opportunities · {data ? `scanned ${fmtTime(data.as_of)}` : "scanning"} · {data?.us_market_open ? "US market open" : "US market closed: last session"}</p>
        <h1 className="display">Invest now</h1>
        <p className="muted lead">Stocks and coins making a big move right now for a real reason: news, heavy volume and a trend that agrees. Each idea comes with an entry, a stop-loss and a target.
          <Hint term="relative-volume">Rules: move of 3%+ (5% for crypto) that is unusual for the stock, at least 1.8x normal volume, in the direction of its long-term trend and near its 52-week extreme, liquid, and backed by a relevant headline. Research shows news-driven moves tend to continue while moves without news often fade. Stock prices are about 15 minutes delayed.</Hint>
        </p>
        <div className="row gap wrap-row">
          <button className="btn" onClick={scan} disabled={scanning || STATIC}>{scanning ? <><Spinner /> Scanning</> : "Scan now"}</button>
          <label className="check"><input id="opp-short" type="checkbox" checked={showShort} onChange={(e) => setShowShort(e.target.checked)} /> Show falling (short) ideas</label>
        </div>
      </section>
      {toast && <div className="notice" role="status">{toast}</div>}
      <ErrorBox error={err} />
      {!data && !err && <div className="empty"><Spinner /> Scanning ~500 stocks and coins…</div>}

      {data && (
        <section>
          <h2 className="section-title">Ideas with a news catalyst · {qualified.length}</h2>
          {qualified.length ? <div className="opps">{qualified.map((o) => <OppCard key={`${o.symbol}${o.direction}`} o={o} onDone={(m) => { setToast(m); load(); }} />)}</div>
            : <Empty>Nothing qualifies right now. That is normal: the rules are strict on purpose. The scan repeats every 5 minutes and you get a notification when something appears.</Empty>}
        </section>
      )}

      <SP500Movers board={data?.movers} />

      {watch.length > 0 && (
        <details className="customize">
          <summary>Moving without news · {watch.length}<span className="muted small"> · watch only</span></summary>
          <p className="muted small">Big moves with no headline found. They often fade, so there is no Invest button.</p>
          <div className="opps">{watch.map((o) => <OppCard key={`w${o.symbol}`} o={o} onDone={() => undefined} />)}</div>
        </details>
      )}

      {broker && broker.broker !== "paper" && (
        <Card title={<><ModeBadge mode={broker.mode} /> Your positions at {brokerLabel(broker.broker)}<Hint>Everything held in your {broker.mode === "live" ? "real" : "paper (test)"} account at the broker, including positions bought outside this app. Ideas opened with Invest close at their stop-loss, target or after about 5 trading days. P&amp;L means profit or loss so far, not yet locked in, shown in your display currency; prices are in each stock's own currency.</Hint></>}
          actions={broker.connected && <span className="muted small">Account <Money v={broker.equity} from={brokerCcy} /><FxHint from={brokerCcy} /></span>}>
          {!broker.connected ? <div className="error">Not connected: {broker.error}</div>
            : held?.positions.length ? (
              <div className="table-wrap"><table>
                <thead><tr><th>Symbol</th><th>Side</th><th className="r">Qty</th><th className="r">Entry</th><th className="r">Now</th><th className="r">P&amp;L</th></tr></thead>
                <tbody>{held.positions.map((p) => (
                  <tr key={p.symbol}><td><strong>{p.symbol}</strong></td><td className={p.side === "long" ? "up" : "down"}>{p.side}</td><td className="r num">{fmtNum(p.qty, 4)}</td>
                    <td className="r num"><Price v={p.entry} symbol={p.symbol} alt="hover" /></td><td className="r num"><Price v={p.price} symbol={p.symbol} alt="hover" /></td><td className={`r num ${(p.pnl ?? 0) >= 0 ? "up" : "down"}`}><Money v={p.pnl} from={brokerCcy} digits={2} /></td></tr>))}
                </tbody></table></div>
            ) : <Empty>No positions at {brokerLabel(broker.broker)} yet.</Empty>}
        </Card>
      )}

      <Card title={<>Your practice positions<Hint>Positions opened with the Invest button, using practice (paper) money. They close automatically at the stop-loss, the target, or after about 5 trading days. Prices are in each stock's own currency; the account value and P&amp;L are in your display currency (the practice account itself is kept in dollars).</Hint></>}
        actions={account && <span className="row gap"><span className="muted small">Practice account <Money v={account.equity} from="USD" /><FxHint from="USD" /></span>
          {oppPositions.length > 0 && !STATIC && <button className="btn small" onClick={async () => { await api.paperCloseAll(); load(); setToast("All practice positions closed."); }}>Close all</button>}</span>}>
        {oppPositions.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Stock</th><th>Side</th><th className="r">Qty</th><th className="r">Entry</th><th className="r">Now</th><th className="r">Stop</th><th className="r">Target</th><th className="r">P&amp;L</th></tr></thead>
            <tbody>{oppPositions.map((p) => (
              <tr key={p.symbol}><td><strong>{p.symbol}</strong></td><td className={p.side === "long" ? "up" : "down"}>{p.side}</td><td className="r num">{fmtNum(p.qty, 4)}</td>
                <td className="r num"><Price v={p.entry} symbol={p.symbol} alt="hover" /></td><td className="r num"><Price v={p.price} symbol={p.symbol} alt="hover" /></td><td className="r num"><Price v={p.stop} symbol={p.symbol} alt="hover" /></td><td className="r num"><Price v={p.target} symbol={p.symbol} alt="hover" /></td>
                <td className={`r num ${(p.pnl ?? 0) >= 0 ? "up" : "down"}`}><Money v={p.pnl} from="USD" digits={2} /></td></tr>))}
            </tbody></table></div>
        ) : <Empty>No practice positions yet. Press Invest on an idea to try it with practice money.</Empty>}
      </Card>
      <p className="caveat">Ideas are generated by rules, not advice. Even strong news-driven moves fail often; the stop-loss and small position size are what keep losses small. Orders go to {broker ? brokerLabel(broker.broker) : "the practice account"}{broker?.mode === "live" ? " with real money" : " with practice money"}; real money stays off unless you set TRADING_MODE=live on the server. The emergency "Close everything" button is in Settings.</p>
    </div>
  );
}
