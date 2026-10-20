import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { fmtNum, fmtPrice, fmtTime } from "../lib/format";
import { STATIC } from "../lib/snapshot";
import type { BrokerStatus, Opportunity, OrderPreviewResult } from "../lib/types";
import { Hint } from "./Hint";
import { Badge, Spinner } from "./ui";

const BROKER_NAME: Record<string, string> = { paper: "Practice account", alpaca: "Alpaca", ccxt: "Crypto exchange", ibkr: "Interactive Brokers" };
export const brokerLabel = (b: string) => BROKER_NAME[b] ?? b;

/** PAPER (neutral) or LIVE (solid red): the account the order goes to. Decided by the server only. */
export function ModeBadge({ mode }: { mode: string }) {
  return mode === "live" ? <span className="badge live" title="Real money">Live</span> : <Badge>Paper</Badge>;
}

const money = (v: number | null | undefined, ccy: string) => ccy === "USD" ? `$${fmtPrice(v)}` : `${fmtPrice(v)} ${ccy}`;
const eur = (v: number | null | undefined) => `€${fmtPrice(v)}`;

/** Order ticket for one live idea: server-side plan, short-lived confirmation, extra step for real money. */
export function OrderTicket({ o, onDone }: { o: Opportunity; onDone: (msg: string) => void }) {
  const [pv, setPv] = useState<OrderPreviewResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ack, setAck] = useState(false);
  const [left, setLeft] = useState(0);
  const body = { symbol: o.symbol, side: o.direction }; // prices, size and stop come from the server

  const review = useCallback(() => {
    setErr(null); setPv(null); setAck(false);
    api.orderPreview(body).then((r) => { setPv(r); setLeft(r.expires_in); }).catch((e) => setErr((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [o.symbol, o.direction]);
  useEffect(() => { review(); }, [review]);
  useEffect(() => {
    if (!pv || left <= 0) return;
    const id = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(id);
  }, [pv, left]);

  const live = pv?.mode === "live";
  const expired = !!pv && left <= 0;
  const confirm = async () => {
    if (!pv) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.orderPlace({ ...body, confirm_token: pv.confirm_token });
      const what = `${o.direction === "long" ? "buy" : "short"} ${fmtNum(r.plan.qty, 4)} ${o.symbol}`;
      onDone(r.placed ? `${live ? "LIVE" : "Paper"} order sent to ${brokerLabel(r.broker)}: ${what} near ${fmtPrice(r.plan.entry)}, stop-loss ${fmtPrice(r.plan.stop)}.`
        : `The order to ${what} was not filled (the price moved). Nothing was bought.`);
    } catch (e) { setErr((e as Error).message); setPv(null); } finally { setBusy(false); }
  };

  const ccy = pv?.currency ?? "USD";
  const plan = pv?.plan;
  return (
    <div className={`invest-panel ticket ${live ? "ticket-live" : ""}`}>
      {pv && (
        <p className="invest-mode">
          <ModeBadge mode={pv.mode} /> <strong>{brokerLabel(pv.broker)}</strong>
          <Hint>{live ? "LIVE means real money: this order goes to your real account at the broker and can lose real money."
            : pv.broker === "paper" ? "PAPER means practice money inside this app. No order is sent to any broker."
            : `PAPER means the broker's practice (test) account: real prices, fake money. Real money only starts when TRADING_MODE=live is set in the server's .env file.`}</Hint>
          <span className="muted"> · {live ? "Real money. A real order will be sent." : "Practice money only."}</span>
        </p>
      )}
      {err && <div className="error" role="alert">{err} <button className="btn small" onClick={review}>Review again</button></div>}
      {!pv && !err && <Spinner />}
      {pv && plan && (
        <>
          <dl className="kv">
            <dt>{o.direction === "long" ? "Buy" : "Sell short"}<Hint>The number of shares (or coins) is calculated for you: hitting the stop-loss would lose about {fmtNum(plan.risk_pct_of_equity, 1)}% of your account, and one idea never takes more than 10% of it.</Hint></dt>
            <dd>{fmtNum(plan.qty, 4)} {o.symbol}</dd>
            <dt>Estimated cost<Hint>Quantity times the current price. The real fill can differ a little because prices move.</Hint></dt>
            <dd>{money(plan.value, ccy)}{pv.eur && <span className="muted"> ≈ {eur(pv.eur.value)}</span>}</dd>
            <dt>Stop-loss<Hint term="stop-loss">If the price reaches this level, the position is closed to limit the loss. {pv.broker === "paper" ? "The app watches it." : "It is placed at the broker, so it works even if this app is off."}</Hint></dt>
            <dd className="down">{fmtPrice(plan.stop)}</dd>
            <dt>Target<Hint>The price where the gain is taken. It is about twice as far as the stop-loss. Reaching it is not guaranteed.</Hint></dt>
            <dd className="up">{fmtPrice(plan.target)}</dd>
            <dt>Risk if stopped<Hint>The most you should lose if the stop-loss is hit, in money and as a share of your account. A gap (price jumping past the stop overnight) can make it bigger.</Hint></dt>
            <dd className="down">{pv.eur ? eur(pv.eur.max_loss) : money(plan.max_loss, ccy)} · {fmtNum(plan.risk_pct_of_equity, 2)}%{pv.eur && <span className="muted"> ({money(plan.max_loss, ccy)})</span>}</dd>
            <dt>Time limit<Hint>Short-term idea: if neither the stop nor the target is hit, the position is closed after about {pv.hold_days ?? 5} trading days.</Hint></dt>
            <dd>{pv.hold_days ?? 5} days{pv.expires_at && <span className="muted"> · idea valid until {fmtTime(pv.expires_at)}</span>}</dd>
            <dt>Account<Hint>Your account value at {brokerLabel(pv.broker)}. Buying power is how much you can still invest.</Hint></dt>
            <dd>{money(pv.equity, ccy)}{pv.buying_power != null && <span className="muted"> · buying power {money(pv.buying_power, ccy)}</span>}</dd>
            <dt>Order type<Hint term="limit-vs-market">How the order is sent. A limit order will not fill at a worse price than shown, so a sudden jump cannot surprise you.</Hint></dt>
            <dd className="small">{pv.order_type}</dd>
          </dl>
          {!pv.can_place && <div className="error" role="alert">{pv.block_reason}</div>}
          {live && pv.can_place && !expired && (
            <label className="check ticket-ack"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I understand this is a real order with real money, and I can lose up to {pv.eur ? eur(pv.eur.max_loss) : money(plan.max_loss, ccy)} or more.</label>
          )}
          <div className="row gap wrap-row">
            {expired ? <button className="btn" onClick={review}>Prices may have moved · Review again</button> : (
              <button className={`btn ${live ? "danger" : "primary"}`} onClick={confirm}
                disabled={busy || STATIC || !pv.can_place || (live && !ack)}>
                {busy ? <Spinner /> : live ? "Confirm LIVE order" : "Confirm paper order"}
              </button>)}
            {!expired && <span className="muted small">Confirm within {left}s<Hint>For safety the confirmation expires quickly. If it does, review the order again with fresh prices.</Hint></span>}
          </div>
        </>
      )}
    </div>
  );
}

/** Kill switch: pauses new orders, then cancels every order and closes every position at the broker.
 *  Stays usable when the broker is disconnected: it still pauses trading, and says to close at the broker. */
export function KillSwitch({ status, onChange }: { status: BrokerStatus | null; onChange: () => void }) {
  const [arm, setArm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const where = status ? brokerLabel(status.broker) : "your broker";
  const offline = !!status && !status.connected;
  const until = status?.halted?.persistent || status?.mode === "live" ? "until you resume them" : "until you resume them, or until tomorrow";
  const run = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.ordersCloseAll();
      setMsg(`Done: ${r.closed.length} position(s) closed, ${Math.max(0, r.cancelled)} order(s) cancelled.${r.errors.length ? ` Problems: ${r.errors.join("; ")}` : ""} New orders are paused.`);
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); setArm(false); onChange(); }
  };
  return (
    <>
      <div className="setting">
        <div><strong>Close everything</strong><Hint term="kill-switch">The emergency button. It first pauses new orders, then cancels every open order and sells (or buys back) every position in the account at {where}, at the market price, including positions you opened outside this app. New orders stay paused {until}.</Hint>
          <p className="muted small">Cancels all orders and closes all positions at {where}{status ? ` (${status.mode === "live" ? "real money" : "paper"})` : ""}.</p>
          {offline && <p className="down small" role="status">Not connected to {where}: pressing it pauses trading here, but cannot close anything. Close your positions at the broker manually.</p>}
        </div>
        {!arm ? <button className="btn danger" onClick={() => setArm(true)} disabled={STATIC || busy || !status}>Close everything</button>
          : <span className="row gap"><button className="btn" onClick={() => setArm(false)}>Cancel</button><button className="btn danger" onClick={run} disabled={busy}>{busy ? <Spinner /> : "Yes, close all"}</button></span>}
      </div>
      {status?.halted && (
        <div className="setting">
          <div><strong>Trading paused</strong><p className="muted small">Since {fmtTime(status.halted.at)}. New orders are refused {status.halted.persistent ? "until you resume (real-money accounts stay paused overnight too)" : "until you resume (or tomorrow)"}.</p></div>
          <button className="btn" onClick={async () => { try { await api.ordersResume(); } catch (e) { setMsg((e as Error).message); } onChange(); }} disabled={STATIC}>Resume trading</button>
        </div>
      )}
      {msg && <div className="notice" role="status">{msg}</div>}
    </>
  );
}
