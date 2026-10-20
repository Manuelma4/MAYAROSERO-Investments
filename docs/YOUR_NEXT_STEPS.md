# Your next steps, Manuel

Everything that can be built without paying is built, tested and on GitHub
(`Manuelma4/MAYAROSERO-Investments`, branch `main`). What is left needs **you**: an account, a password, a
payment or a decision. Do them in this order; each step works on its own, and the app keeps working if you
stop at any step.

| # | Step | Cost | Time | Needed for |
|---|---|---|---|---|
| 1 | Run the app all the time | Free at home, or ~€5/month server | 15 min | Everything live: alerts, scans, track record |
| 2 | Email + WhatsApp alerts | Free | 15 min | Getting alerts on your phone when the app is closed |
| 3 | Install it on your phone | Free | 1 min | Opening it like an app |
| 4 | Practice with a broker (Alpaca paper) | Free | 20 min | Testing the Invest button end to end, fake money |
| 5 | Decide after 1–3 months of live track record | Free | – | Whether the picks deserve real money |
| 6 | Optional paid upgrades | see below | – | Faster prices, AI analyst, real-money orders |

---

## 1. Run it all the time

Follow [docs/HOSTING.md](HOSTING.md). Short version on any computer with Docker:

```
git clone https://github.com/Manuelma4/MAYAROSERO-Investments.git
cd MAYAROSERO-Investments
cp .env.example .env
cp config/config.example.yaml config/config.yaml
docker compose up -d --build
```

Open http://localhost:8000. If you put it on the internet (a server), first set a long password in `.env`:
`TRADEBOT_API_TOKEN=` followed by the output of `openssl rand -hex 32`, then paste it once in Settings → Access.

**Why it matters:** the live track record, weekly digest, earnings and price alerts only work while the app
is running. The track record starts counting from the first day it runs.

## 2. Alerts on your phone (email + WhatsApp)

Follow [docs/ALERTS_SETUP.md](ALERTS_SETUP.md): a Gmail "app password" and a free Twilio WhatsApp sandbox.
Then switch them on in `config/config.yaml` (`notifiers: [console, email, whatsapp]`) and check with:

```
docker compose exec app python scripts/test_alerts.py
```

You will then receive: price alerts you set, picks changes at each monthly review, Invest-now ideas,
earnings the day before (for your picks, watchlists and holdings), portfolio drift, and a short weekly digest
every Sunday at 18:00.

## 3. Install it on your phone

Open the app's address in Safari or Chrome → Share / menu → **Add to Home Screen**.

## 4. Practice with a broker, with fake money

1. Open a free **Alpaca paper** account (alpaca.markets), create paper API keys (they start with `PK`).
2. In `.env`: `BROKER=alpaca`, `ALPACA_API_KEY_ID=...`, `ALPACA_API_SECRET_KEY=...`. Leave `TRADING_MODE=paper`.
3. Restart (`docker compose up -d --force-recreate`). Settings shows **PAPER · Alpaca · Connected**.
4. Use the Invest button for a few weeks. Check that stops and targets appear at Alpaca, that the Close
   everything button works, and that the app only closes what it opened.

Details: [LATER.md section 2](../LATER.md). Interactive Brokers (popular in France) is ready in paper mode
only; tell Claude to finish it if you choose IBKR for real money.

## 5. Decide with real evidence, not the backtest

What the tests honestly say today (details on the Learn page):

- The monthly picks alone grew about **17% a year since 2015** vs **14% for the S&P 500**, with bigger swings
  (worst drop −39%). They lost to the index in 2015–2020 and beat it strongly in 2021–2026. Not proven.
- The ready-made plans with their risk matched to Cautious / Balanced / Bold earned about **11% a year**, below
  the S&P 500. Simply holding an S&P 500 fund is a strong, cheap default.
- Only the 1-day prediction ranking showed a statistically real edge; the 5-day and 21-day rankings did not.

So: let the **live track record** (Today and Beat the S&P pages) run for at least 1–3 months, ideally a year,
before trusting the picks with real money. If you invest anyway, keep most of it in a plain S&P 500 fund and
use small amounts for the picks.

## 6. Optional paid upgrades (only if you want them)

| Upgrade | What you get | Cost (approx.) | How |
|---|---|---|---|
| Real-time US prices | Live prices instead of ~15 min delayed | Polygon "Stocks Advanced" ~$199/month, or Alpaca "Algo Trader Plus" ~$99/month | `MARKET_DATA_PROVIDER` + key in `.env` ([LATER.md §1](../LATER.md)) |
| AI analyst desk | "Ask the AI desk" on ideas and charts: news, fundamentals, bull vs bear, risk verdict | Pay as you go, a few cents per analysis | `ANTHROPIC_API_KEY` in `.env`, `pip install -e '.[ai]'` ([LATER.md §3](../LATER.md)) |
| Real-money orders | The Invest button places real orders | Broker fees only | Steps 1–4 above, then `TRADING_MODE=live` with a strong token ([LATER.md §2](../LATER.md)) |
| Exact index history | Removes the last bias from the picks backtest | Norgate Data or similar | Replace `src/tradebot/data/sp500_joins.csv` ([LATER.md §5](../LATER.md)) |
| Own web address | e.g. `invest.mayarosero.com` with HTTPS | ~€10/year | [docs/HOSTING.md](HOSTING.md) |
| WhatsApp without the sandbox | No re-joining every 72 h | Twilio WhatsApp sender, small monthly fee | Twilio console |

## Your weekly routine (10 minutes)

1. **Today**: market mood, what to hold, what changed, earnings this week.
2. **Sunday digest**: read it; nothing to do most weeks.
3. **Month end**: Beat the S&P shows buy / sell / keep. Update your holdings if you follow the picks.
4. **My portfolio**: if you get a drift alert, rebalance with the suggested amounts.
5. **Learn**: look up any word you don't know.

Never risk money you need in the next few years, keep each idea small (the app sizes them at 1% risk), and
remember: this app gives information, not financial advice.

## If you continue with Claude later

The plan and status are in [ROADMAP.md](../ROADMAP.md); the project rules are in [CLAUDE.md](../CLAUDE.md).
Ask Claude to "work the first unchecked item in ROADMAP.md". Ideas not built yet: Interactive Brokers for
real money, replaying Invest-now ideas in the plan backtest, Qlib factor research.
