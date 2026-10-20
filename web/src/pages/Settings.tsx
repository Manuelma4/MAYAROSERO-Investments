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
import { fmtNum, fmtPrice } from "../lib/format";
import type { BrokerStatus } from "../lib/types";

export default function Settings() {
  const { pref } = useTheme();
  const { status } = useLive();
  const [notify, setNotify] = useState(browserNotifyEnabled());
  const [token, setTok] = useState(getToken() ?? "");
  const [saved, setSaved] = useState(false);
  const channels = status?.notifiers ?? [];
  const [broker, setBroker] = useState<BrokerStatus | null>(null);
  const loadBroker = useCallback(() => { api.brokerStatus().then(setBroker).catch(() => undefined); }, []);
  useEffect(() => { loadBroker(); }, [loadBroker]);
  const lim = broker?.limits;

  return (
    <div className="page narrow">
      <div className="page-head"><div><h1>Settings</h1><p className="muted">Trading, appearance, notifications and access.</p></div></div>

      <Card title="Tools" className="mobile-only">
        <div className="tool-links wrap">
          <Link to="/picks" className="btn">Picks</Link>
          <Link to="/discover" className="btn">Discover</Link>
          <Link to="/alerts" className="btn">Alerts</Link>
          <Link to="/charts" className="btn">Charts</Link>
          <Link to="/predict" className="btn">Predict</Link>
          <Link to="/backtest" className="btn">Backtest</Link>
        </div>
      </Card>

      <Card title="Trading">
        <div className="setting">
          <div><strong>Broker</strong><Hint>Where Invest orders go. Practice account = fake money inside this app. Alpaca and exchanges start on their paper (test) account. Change it with BROKER=... in the server's .env file.</Hint>
            <p className="muted small">{broker ? (broker.connected ? `Connected · account ${fmtPrice(broker.equity ?? null)} ${broker.currency ?? ""} · buying power ${fmtPrice(broker.buying_power ?? null)}` : `Not connected: ${broker.error ?? "unknown"}`) : "Checking…"}</p>
          </div>
          {broker && <span className="row gap"><ModeBadge mode={broker.mode} /><Badge>{brokerLabel(broker.broker)}</Badge></span>}
        </div>
        <div className="setting">
          <div><strong>Money</strong><Hint>PAPER = practice, nothing real can be lost. LIVE = real money. Only you can switch it on, by adding TRADING_MODE=live to the server's .env file and restarting; there is no button for it on purpose.</Hint>
            <p className="muted small">{broker?.mode === "live" ? "Real money. Every order asks for an extra confirmation." : "Practice only. Real money is off."}</p>
            {broker?.live_block && <p className="down small">{broker.live_block}</p>}
          </div>
        </div>
        {lim && (
          <div className="setting">
            <div><strong>Safety limits</strong><Hint>Checked by the server before every order, for every broker. They can only be made stricter in .env, never looser.</Hint>
              <ul className="muted small limits">
                <li>Risk per idea: {fmtNum(lim.risk_per_trade_pct, 1)}% of the account<Hint>The loss if the stop-loss is hit. 1% means a 10,000 account loses about 100 on a bad idea.</Hint></li>
                <li>Max per position: {fmtNum(lim.max_position_pct, 0)}% of the account<Hint>No single idea can take more than this share of your money.</Hint></li>
                <li>Max open ideas: {lim.max_open_positions}<Hint>How many Invest positions can be open at the same time.</Hint></li>
                <li>Daily loss stop: {fmtNum(lim.max_daily_loss_pct, 0)}%{lim.max_daily_loss_value ? ` or ${fmtNum(lim.max_daily_loss_value, 0)}` : ""}<Hint>After losing this much in one day (open losses included), new orders are refused until tomorrow.</Hint></li>
                {lim.max_order_value ? <li>Max order size: {fmtNum(lim.max_order_value, 0)}<Hint>No single order can cost more than this, in the account's currency.</Hint></li> : null}
                <li>Short positions: at most {fmtNum(lim.max_short_exposure_pct, 0)}% of the account<Hint>Betting on a fall (short) is riskier, so it is capped.</Hint></li>
              </ul>
            </div>
          </div>
        )}
        <KillSwitch status={broker} onChange={loadBroker} />
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
            ? <button className={`switch ${notify ? "on" : ""}`} role="switch" aria-checked={notify} onClick={async () => setNotify(await setBrowserNotify(!notify))}><span /></button>
            : <Badge>Not supported</Badge>}
        </div>
        {[["email", "Email", "SMTP_* variables in .env"], ["whatsapp", "WhatsApp", "TWILIO_* variables in .env"]].map(([k, label, how]) => (
          <div className="setting" key={k}>
            <div><strong>{label}</strong><p className="muted small">Configured on the server ({how}) and enabled in config.yaml notifiers.</p></div>
            {channels.includes(k) ? <Badge tone="up">Active</Badge> : <Badge>Not configured</Badge>}
          </div>))}
      </Card>

      <Card title="Access">
        <form className="setting" onSubmit={(e) => { e.preventDefault(); setToken(token.trim() || null); setSaved(true); setTimeout(() => location.reload(), 400); }}>
          <div style={{ flex: 1 }}><strong>Access token</strong><p className="muted small">Required when the server sets TRADEBOT_API_TOKEN. Stored only in this browser.</p>
            <input type="password" value={token} onChange={(e) => setTok(e.target.value)} placeholder="Paste your token" style={{ width: "100%", marginTop: 8 }} />
          </div>
          <button className="btn primary">{saved ? "Saved" : "Save"}</button>
        </form>
      </Card>

      <p className="muted small">MAYAROSERO Investments provides market information and analysis tools only. It is not financial advice; past performance does not guarantee future results.</p>
    </div>
  );
}
