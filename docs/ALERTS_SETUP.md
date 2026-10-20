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
| Portfolio drift | Your holdings moved far from the plan you saved as your target (at most once a week) | `[PORTFOLIO DRIFT] ... Sell about €300 of NVDA, buy about €250 of JNJ.` |
| Weekly digest | Sunday ~18:00 Paris time: the week in one short message | see section 6 |

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

## 6. Weekly digest

One short message a week (under 1,200 characters, so it fits a WhatsApp message) through the same
channels: what changed in the picks, the price alerts that fired, the live track record (picks vs the
S&P 500 and the Invest-now ideas), your portfolio drift if you saved a target, and the market mood.

```
MAYAROSERO weekly digest · 18 Oct 2026
Market mood: Neutral. Mixed signals: stay invested but respect stop-losses.
Picks: no change this week. The list is reviewed at each month end.
Your price alerts: 1 fired (AAPL above 250).
Live track record since 1 Oct (12 trading days): picks +2.4% vs S&P 500 +1.1% (ahead of). Too early to judge: it takes months.
Portfolio: on plan (largest gap 1.8 points).
Details in the app. Information, not advice.
```

- **When**: Sunday at 18:00 Europe/Paris by default (summer and winter time handled). If the server was
  off at that moment, it still goes out within the next 12 hours; otherwise that week is skipped. It is
  sent once per week: the "sent" mark is kept in the database, so a restart never sends it twice.
- **Change it** in `config/config.yaml`, or with environment variables in `.env` (these win):

  ```yaml
  digest:
    enabled: true
    day: sunday             # monday ... sunday
    hour: 18                # or "18:30"
    timezone: Europe/Paris
  ```

  ```
  DIGEST_DAY=friday
  DIGEST_HOUR=19
  DIGEST_ENABLED=false      # switch it off
  ```

- **Preview / test**: Settings → Notifications → Weekly digest → Preview shows the exact text; "Send it
  now" sends it immediately (a test send does not replace the weekly one). From a terminal:
  `curl localhost:8000/api/digest/preview` and
  `curl -X POST -H 'Content-Type: application/json' -d '{"confirm": true}' localhost:8000/api/digest/send-test`
  (add `-H "Authorization: Bearer $TRADEBOT_API_TOKEN"` when a token is set).

### Portfolio drift alert

On My portfolio, build your plan and press **Save this plan as my target** once you have bought it.
The app then compares what you hold (the practice account, or your real broker when `BROKER` is set)
with that target every 30 minutes. When one position is more than 5 percentage points away from its
target, or more than 10% of your money is off plan, you get one alert (at most once a week) with a
plain-English rebalance in amounts. Invest-now positions are left out of the advice: they close by
themselves at their stop, target or time limit. Nothing is ever bought or sold automatically.
