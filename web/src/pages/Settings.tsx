import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getToken, setToken } from "../lib/api";
import { browserNotifyEnabled, browserNotifySupported, setBrowserNotify } from "../lib/browserNotify";
import { STATIC } from "../lib/snapshot";
import { useLive } from "../lib/live";
import { setThemePref, useTheme, type ThemePref } from "../lib/theme";
import { Badge, Card } from "../components/ui";
import { Hint } from "../components/Hint";
import { KillSwitch, ModeBadge, brokerLabel } from "../components/Trading";
import { asCcy, fmtMoney, fmtNum, fmtTime } from "../lib/format";
import { DISPLAY_OPTIONS, FxHint, Money, useCurrency } from "../lib/currency";
import type { BrokerStatus, DigestPreview } from "../lib/types";

export default function Settings() {
  const { pref } = useTheme();
  const cur = useCurrency();
  const { status } = useLive();
  const [notify, setNotify] = useState(browserNotifyEnabled());
  const [token, setTok] = useState(getToken() ?? "");
  const [saved, setSaved] = useState(false);
  const channels = status?.notifiers ?? [];
  const [broker, setBroker] = useState<BrokerStatus | null>(null);
  const loadBroker = useCallback(() => { api.brokerStatus().then(setBroker).catch(() => undefined); }, []);
  useEffect(() => { loadBroker(); }, [loadBroker]);
  const lim = broker?.limits;
  const acct = asCcy(broker?.currency) ?? "USD";
  const [digest, setDigest] = useState<DigestPreview | null>(null);
  const [digestBusy, setDigestBusy] = useState(false);
  const [digestMsg, setDigestMsg] = useState<string | null>(null);
  const previewDigest = async () => {
    if (digest) { setDigest(null); setDigestMsg(null); return; }
    setDigestBusy(true); setDigestMsg(null);
    try { setDigest(await api.digestPreview()); } catch (e) { setDigestMsg(`The preview could not be built. ${(e as Error).message}`); } finally { setDigestBusy(false); }
  };
  const sendDigest = async () => {
    setDigestBusy(true); setDigestMsg(null);
    try { const r = await api.digestSendTest(); setDigestMsg(`Sent now to: ${r.channels.join(", ") || "console"}. The weekly one still goes out as scheduled.`); }
    catch (e) { setDigestMsg((e as Error).message); } finally { setDigestBusy(false); }
  };

  return (
    <div className="page narrow">
      <section className="hero-x">
        <p className="eyebrow">Settings · {broker ? (broker.mode === "live" ? "real money on" : "practice money only") : "checking the broker"}</p>
        <h1 className="display">Settings</h1>
        <p className="muted lead">Trading safety, currency, appearance, notifications and access.</p>
      </section>

      <Card title="Tools" className="mobile-only">
        <div className="tool-links wrap">
          <Link to="/picks" className="btn">Picks</Link>
          <Link to="/discover" className="btn">Discover</Link>
          <Link to="/alerts" className="btn">Alerts</Link>
          <Link to="/charts" className="btn">Charts</Link>
          <Link to="/predict" className="btn">Predict</Link>
          <Link to="/backtest" className="btn">Backtest</Link>
          <Link to="/learn" className="btn">Learn</Link>
        </div>
      </Card>

      <Card title="Trading">
        <div className="setting">
          <div><strong>Broker</strong><Hint>Where Invest orders go. Practice account = fake money inside this app. Alpaca and exchanges start on their paper (test) account. Change it with BROKER=... in the server's .env file.</Hint>
            <p className="muted small">{broker ? (broker.connected ? <>Connected · account <Money v={broker.equity} from={acct} /> · buying power <Money v={broker.buying_power} from={acct} /><FxHint from={acct} /></> : `Not connected: ${broker.error ?? "unknown"}`) : "Checking…"}</p>
          </div>
          {broker && <span className="row gap"><ModeBadge mode={broker.mode} /><Badge>{brokerLabel(broker.broker)}</Badge></span>}
        </div>
        <div className="setting">
          <div><strong>Money</strong><Hint term="paper-account">PAPER = practice, nothing real can be lost. LIVE = real money. Only you can switch it on, by adding TRADING_MODE=live to the server's .env file and restarting; there is no button for it on purpose.</Hint>
            <p className="muted small">{broker?.mode === "live" ? "Real money. Every order asks for an extra confirmation." : "Practice only. Real money is off."}</p>
            {broker?.live_block && <p className="down small">{broker.live_block}</p>}
          </div>
        </div>
        {lim && (
          <div className="setting">
            <div><strong>Safety limits</strong><Hint>Checked by the server before every order, for every broker. They can only be made stricter in .env, never looser.</Hint>
              <ul className="muted small limits">
                <li>Risk per idea: {fmtNum(lim.risk_per_trade_pct, 1)}% of the account<Hint term="risk-per-trade">The loss if the stop-loss is hit. 1% means a 10,000 account loses about 100 on a bad idea.</Hint></li>
                <li>Max per position: {fmtNum(lim.max_position_pct, 0)}% of the account<Hint term="position-size">No single idea can take more than this share of your money.</Hint></li>
                <li>Max open ideas: {lim.max_open_positions}<Hint>How many Invest positions can be open at the same time.</Hint></li>
                <li>Daily loss stop: {fmtNum(lim.max_daily_loss_pct, 0)}%{lim.max_daily_loss_value ? ` or ${fmtMoney(lim.max_daily_loss_value, acct, 0)}` : ""}<Hint>After losing this much in one day (open losses included), new orders are refused until tomorrow.</Hint></li>
                {lim.max_order_value ? <li>Max order size: {fmtMoney(lim.max_order_value, acct, 0)}<Hint>No single order can cost more than this, in the account's currency (it is checked by the broker account, so it is not converted).</Hint></li> : null}
                <li>Short positions: at most {fmtNum(lim.max_short_exposure_pct, 0)}% of the account<Hint term="short-selling">Betting on a fall (short) is riskier, so it is capped.</Hint></li>
              </ul>
            </div>
          </div>
        )}
        <KillSwitch status={broker} onChange={loadBroker} />
      </Card>

      <Card title={<>Display currency<Hint term="exchange-rate">The currency money is shown in across the app: your plan, order costs, profits and losses, account values. Stock prices always stay in the currency they trade in (dollars for Apple, euros for LVMH), with the converted value next to them. Changing it never changes what you own.</Hint></>}>
        <div className="segmented wide" role="radiogroup" aria-label="Display currency">
          {DISPLAY_OPTIONS.map((o) => (
            <button key={o.id} role="radio" aria-checked={cur.pref === o.id} className={cur.pref === o.id ? "active" : ""} onClick={() => cur.setPref(o.id)}>
              {o.label}
            </button>))}
        </div>
        <p className="muted small">{DISPLAY_OPTIONS.find((o) => o.id === cur.pref)?.hint}</p>
        <p className="muted small fx-rate">{cur.perEur.USD
          ? <>Live rate: <strong>1 € = {fmtMoney(cur.perEur.USD, "USD", 4)}</strong>{cur.updated ? ` · updated ${fmtTime(cur.updated / 1000)}` : ""}, refreshed every 5 minutes.
            <Hint>Converted amounts use this mid-market rate. Your broker converts at its own rate and usually adds a fee (often 0.1% to 1%), so what you really pay can differ a little.</Hint></>
          : "Live rate loading… Until it arrives, amounts are shown in their original currency."}</p>
      </Card>

      <Card title="Appearance">
        <div className="segmented" role="radiogroup" aria-label="Theme">
          {(["system", "dark", "light"] as ThemePref[]).map((t) => (
            <button key={t} role="radio" aria-checked={pref === t} className={pref === t ? "active" : ""} onClick={() => setThemePref(t)}>
              {t[0].toUpperCase() + t.slice(1)}
            </button>))}
        </div>
      </Card>

      <Card title="Notifications">
        <div className="setting">
          <div><strong>Browser notifications</strong><p className="muted small">Pop-up alerts on this device while the app is open.</p></div>
          {!STATIC && browserNotifySupported()
            ? <button className={`switch ${notify ? "on" : ""}`} role="switch" aria-checked={notify} aria-label="Browser notifications" onClick={async () => setNotify(await setBrowserNotify(!notify))}><span /></button>
            : <Badge>Not supported</Badge>}
        </div>
        {[["email", "Email", "every alert in your inbox", "SMTP_* variables in .env"], ["whatsapp", "WhatsApp", "every alert as a WhatsApp message", "TWILIO_* variables in .env"]].map(([k, label, what, how]) => (
          <div className="setting" key={k}>
            <div><strong>{label}</strong><Hint>Set up once on the server: {how}, then add it to the notifiers list in config.yaml.</Hint><p className="muted small">Receive {what}.</p></div>
            {channels.includes(k) ? <Badge>Active</Badge> : <Badge>Not set up</Badge>}
          </div>))}
        <div className="setting">
          <div><strong>Weekly digest</strong><Hint>One short message a week, Sunday around 18:00 Paris time, through the channels above (email, WhatsApp, or the server log if none is set up). It sums up the week: changes to the picks, the price alerts that fired, the live track record, how far your portfolio drifted from its target, and the market mood. Change the day or hour with DIGEST_DAY and DIGEST_HOUR in .env.</Hint>
            <p className="muted small">{digest ? `${digest.schedule.enabled ? `Sent ${digest.schedule.text}` : "Switched off (DIGEST_ENABLED)"}${digest.last_sent ? ` · last sent ${new Date(digest.last_sent).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}` : ""}` : "Sent every Sunday around 18:00 (Paris time)."}</p>
          </div>
          <span className="row gap">
            <button className="btn small" onClick={previewDigest} disabled={digestBusy} aria-expanded={!!digest}>{digest ? "Hide preview" : "Preview"}</button>
            {!STATIC && digest && <button className="btn small" onClick={sendDigest} disabled={digestBusy}>Send it now</button>}
          </span>
          {digest && <div className="digest-preview">
            <pre aria-label="This week's digest">{digest.text}</pre>
            <p className="muted small">{digest.chars} characters, exactly what would be sent right now. It updates by itself until Sunday.</p>
          </div>}
          {digestMsg && <p className="small muted" role="status" style={{ flexBasis: "100%", margin: 0 }}>{digestMsg}</p>}
        </div>
      </Card>

      <Card title="Access">
        <form className="setting" onSubmit={(e) => { e.preventDefault(); setToken(token.trim() || null); setSaved(true); setTimeout(() => location.reload(), 400); }}>
          <div style={{ flex: 1 }}><strong>Access token</strong><p className="muted small">Required when the server sets TRADEBOT_API_TOKEN. Stored only in this browser.</p>
            <input type="password" aria-label="Access token" autoComplete="off" value={token} onChange={(e) => setTok(e.target.value)} placeholder="Paste your token" style={{ width: "100%", marginTop: 8 }} />
          </div>
          <button className="btn primary">{saved ? "Saved" : "Save"}</button>
        </form>
      </Card>

      <p className="muted small">MAYAROSERO Investments provides market information and analysis tools only. It is not financial advice; past performance does not guarantee future results.</p>
    </div>
  );
}
