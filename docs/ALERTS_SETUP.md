# Alerts by email and WhatsApp: setup walkthrough

Alerts already appear in the app (the bell, the Alerts page, browser pop-ups). This page adds the
two channels that reach your phone when the app is closed. Both are free to start. Follow it once,
with the app running, in about 15 minutes.

What you will receive:

| Alert | When | Example |
|---|---|---|
| Price alert | A level you set on a stock page or on Alerts is reached | `[PRICE ALERT] AAPL is above 250 (now 251.30, +2.1% today)` |
| Picks update | The Beat-the-S&P list changes at a monthly review | `[PICKS UPDATE] BUY: TMO  SELL: UNH  KEEP: ...` |
| Invest now | A stock or coin moves hard on news and heavy volume | `[INVEST NOW] HAS RISING +6.8% on 4.9x volume` |
| Big mover | A sudden surge or crash on the watched markets | `[SURGE] BTC/USDT +3.2% in 5m` |

All settings go in the `.env` file next to `docker-compose.yml` (copy `.env.example` to `.env` the
first time). Never commit `.env`: it holds passwords.

## 1. Email (Gmail, free)

1. Turn on 2-Step Verification on the Google account that will send the alerts
   (myaccount.google.com → Security).
2. Create an app password: myaccount.google.com → Security → 2-Step Verification → App passwords →
   name it "MAYAROSERO" → copy the 16-letter password (shown once).
3. In `.env`:

   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=the.sender@gmail.com
   SMTP_PASSWORD=abcdefghijklmnop        # the app password, no spaces
   ALERT_EMAIL_TO=manuel@example.com     # where alerts go; several: a@x.com,b@y.com
   ```

   Any other provider works too (Outlook: `smtp-mail.outlook.com`, OVH, Gandi, ...): use its SMTP
   host, port 587 and your mailbox login.

## 2. WhatsApp (Twilio, free sandbox to start)

1. Create a free account at twilio.com and verify your phone number.
2. Console → Messaging → Try it out → Send a WhatsApp message. Twilio shows a sandbox number
   (usually +1 415 523 8886) and a code like `join purple-tiger`.
3. From your phone, send that exact `join ...` message to the sandbox number on WhatsApp.
   (The sandbox needs this again if you don't message it for 72 hours; a paid Twilio WhatsApp sender
   removes that limit, see LATER.md.)
4. Console home → copy the Account SID and Auth Token. In `.env`:

   ```
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your-auth-token
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
   WHATSAPP_TO=whatsapp:+33612345678      # your number, international format
   ```

## 3. Switch the channels on

In `config/config.yaml`:

```yaml
notifiers: [console, email, whatsapp]
```

## 4. Test, then restart

```
docker compose exec app python scripts/test_alerts.py      # in Docker
python scripts/test_alerts.py                               # without Docker (after: set -a; . ./.env; set +a)
```

Each channel prints `sent` or the exact reason it failed, for example:

- `SMTP_HOST, SMTP_USER, SMTP_PASSWORD and ALERT_EMAIL_TO must be set`: a line is missing in `.env`.
- `(535, b'... Username and Password not accepted')`: use the app password, not your Gmail password.
- `Twilio answered 401`: Account SID or Auth Token is wrong.
- `Twilio answered 400 ... not a valid WhatsApp ... / 63015`: your phone has not sent the `join` code
  (or it expired after 72 hours).

When both say `sent` and the messages arrived, restart the app so it picks up the settings:

```
docker compose up -d --force-recreate
```

Settings → Notifications in the app then shows Email and WhatsApp as configured.

## 5. Tune what you get

- Price alerts: set or delete them on any stock page (Set price alert) or on Alerts. Each fires once,
  then switches off; press Re-arm to watch again.
- Invest now ideas are strict on purpose (a few a week). Big-mover alerts are tuned in
  `config/config.yaml` under `movers:` (raise `min_zscore` / `min_move_pct` for fewer messages).
- Browser pop-ups: Settings → Notifications → Browser notifications.
