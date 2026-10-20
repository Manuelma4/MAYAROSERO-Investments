import { useState } from "react";
import { Link } from "react-router-dom";
import { getToken, setToken } from "../lib/api";
import { browserNotifyEnabled, browserNotifySupported, setBrowserNotify } from "../lib/browserNotify";
import { STATIC } from "../lib/snapshot";
import { useLive } from "../lib/live";
import { setThemePref, useTheme, type ThemePref } from "../lib/theme";
import { Badge, Card } from "../components/ui";

export default function Settings() {
  const { pref } = useTheme();
  const { status } = useLive();
  const [notify, setNotify] = useState(browserNotifyEnabled());
  const [token, setTok] = useState(getToken() ?? "");
  const [saved, setSaved] = useState(false);
  const channels = status?.notifiers ?? [];

  return (
    <div className="page narrow">
      <div className="page-head"><div><h1>Settings</h1><p className="muted">Appearance, notifications and access.</p></div></div>

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
