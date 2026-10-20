# Things for Manuel to do later

The code for each of these is (or will be) ready. You only sign up, pay if needed, and
put the credentials in `.env` on the server. Nothing here is required to use the app today.

## 1. Real-time stock prices (paid)
Today: stocks come from Yahoo Finance (free, often ~15 min delayed); crypto is already real time.
The code for three paid feeds is ready (`src/tradebot/data/paid.py`). Pick ONE:

| Provider | Plan to buy (approx.) | Notes |
|---|---|---|
| **Polygon.io** (now also branded Massive) | "Stocks Advanced" ~$199/month (real time). Starter ~$29 / Developer ~$79 are 15-min delayed like Yahoo (more reliable, not faster) | Best coverage: all US exchanges, minute bars, live snapshot. Recommended. |
| **Alpaca** | "Algo Trader Plus" ~$99/month (full SIP feed). The free plan works too but only with IEX prices (~2-3% of US volume) | The same account will be used for trading (item 2). |
| **Finnhub** | A paid stock plan that includes "Stock candles" (~$50+/month) | Free keys only give quotes, not candles: the app would keep using Yahoo. |

Steps:
1. Sign up, buy the plan, copy the API key from the provider's dashboard.
2. Add to `.env` on the server (only the lines for your provider):
```
MARKET_DATA_PROVIDER=polygon          # yahoo (default) | polygon | alpaca | finnhub
POLYGON_API_KEY=...
# ALPACA_API_KEY_ID=...  ALPACA_API_SECRET_KEY=...  ALPACA_DATA_FEED=sip   (sip = paid full feed, iex = free)
# FINNHUB_API_KEY=...
```
3. Restart: `docker compose up -d` (it reads `.env`).
4. Check it works (calls the paid feed directly, no fallback, prints the last bars and last trade):
```
docker compose exec app python -m tradebot.data.paid AAPL
```
   Without Docker: `set -a; . ./.env; set +a; python -m tradebot.data.paid AAPL`.
   "OK: polygon works" means you are live. "FAILED ... HTTP 403" means the key or plan is wrong.

What happens automatically: US stocks (AAPL, BRK-B, ...) come from the paid feed; indices (^GSPC),
European listings (MC.PA) and crypto stay on Yahoo / Binance. If the paid feed fails (bad key, rate
limit, outage) the app quietly uses Yahoo for that request and logs one warning; nothing breaks.
After a rejected key it stops asking the provider for 15 minutes.

Optional settings: `MARKET_DATA_MAX_RPM=60` (cap requests per minute, for low-tier plans),
`MARKET_DATA_EXTENDED_HOURS=1` (include pre/after-market bars; default is the regular 9:30-16:00
session, like Yahoo), `POLYGON_BASE_URL=https://api.massive.com` (if Polygon retires the old domain).
Live streaming clients (trades + 1-minute bars over WebSocket) are in `src/tradebot/data/streaming.py`,
ready for a later push-to-browser feature; they stay off until a key is set.

## 2. Investing from the platform (broker connection)
The connection is built (roadmap item 8). You only add keys to `.env` and restart the app.
Until then, the Invest button uses the practice account inside the app.

**How the safety works** (you cannot switch it off by accident):
- Real money needs BOTH a real broker (`BROKER=alpaca|ccxt|ibkr`) AND `TRADING_MODE=live`. Any other value,
  a typo or nothing means paper / test accounts. There is no button in the app for this, on purpose.
- Every order: a preview first (quantity, cost, stop-loss, target, risk in € and %, PAPER/LIVE badge), then a
  confirmation that expires after 90 seconds. Live orders also need a tick box "I understand this is real money".
- Live orders are refused unless `TRADEBOT_API_TOKEN` is set, so only you can place them.
- Server-side limits for every broker: 1% risk per idea, max 10% of the account per position, max 5 open ideas,
  max 20% short, daily loss stop 3% (open losses count). Optional stricter caps below.
- The stop-loss (and target, on Alpaca) is held at the broker, so it works even if the app is off.
  Positions are closed after about 5 trading days (time limit) by the app.
- Kill switch: Settings → Trading → "Close everything" cancels every order and closes every position in the
  broker account (including ones bought outside the app), then pauses new orders until you resume or tomorrow.

### Step 1: Alpaca paper account (free, fake money, real prices)
1. Sign up at https://alpaca.markets (email only for paper trading).
2. In the dashboard, switch to **Paper Trading** (top left), then **API Keys → Generate New Key**.
   Copy the Key ID and the Secret (shown once).
3. In `.env` on the server:
   ```
   BROKER=alpaca
   ALPACA_API_KEY_ID=PK...            # paper keys start with PK
   ALPACA_API_SECRET_KEY=...
   # TRADING_MODE stays unset (or TRADING_MODE=paper)
   ```
4. Restart (`docker compose up -d` or `tradebot serve`). Settings → Trading should show
   **PAPER · Alpaca · Connected** with the paper balance ($100,000 by default; you can reset it to e.g. $10,000
   in the Alpaca dashboard to match real life).
5. Use it for a few weeks. Alpaca trades US stocks only here; crypto goes through an exchange (below).

### Step 2: real money (only when you are confident)
1. Open and fund a live account (Alpaca live: check that French residents are accepted; otherwise IBKR below).
2. Generate **live** API keys (they start with `AK`), and replace the paper keys in `.env`.
3. Set a long random `TRADEBOT_API_TOKEN` (required for live), and optionally stricter caps:
   ```
   TRADING_MODE=live
   TRADEBOT_API_TOKEN=a-long-random-string
   MAX_ORDER_VALUE=1000               # max cost of one order, in the account currency (USD at Alpaca)
   MAX_DAILY_LOSS_VALUE=300           # stop new orders after losing this much today
   RISK_PER_TRADE_PCT=0.5             # optional: risk less than the 1% default per idea
   ```
   These caps can only make the limits stricter, never looser than the defaults.
4. Restart. The ticket now shows a red **LIVE** badge and "Confirm LIVE order". To go back to practice,
   delete the `TRADING_MODE=live` line and restart.

### Crypto (Binance, Kraken, ... through ccxt)
Paper mode uses the exchange's **test network**. Binance spot testnet: log in at https://testnet.binance.vision
with GitHub, generate an HMAC key. Exchanges without a test network are refused in paper mode.
```
BROKER=ccxt
CCXT_EXCHANGE=binance
CCXT_API_KEY=...  CCXT_SECRET=...     # live: trading permission only, NEVER withdrawal
CCXT_QUOTE=USDT
```
Spot only: rising (long) ideas; short ideas are refused. The stop-loss is placed on the exchange right after the
buy; if the exchange refuses it, the coins are sold again immediately.

### Interactive Brokers (recommended for real money in France; experimental here)
1. Open an IBKR account (paper account included), install TWS or IB Gateway, enable the API
   (Configure → API → Settings), and `pip install ib_insync`.
2. `.env`: `BROKER=ibkr`, `IBKR_HOST=127.0.0.1`, `IBKR_PORT=7497` (TWS paper; 4002 Gateway paper), `IBKR_CLIENT_ID=17`.
   Live ports (7496 / 4001) are refused unless `TRADING_MODE=live`, and a paper session that lands on a
   real account (ids not starting with "D") disconnects at once.

Note: investing your own money through your own account is fine. Managing other people's
money or selling signals as a service needs a license in France (AMF); talk to a professional first.

## 3. AI analyst (Claude API key)
The live "invest now" opportunities can be checked by a team of AI agents (TradingAgents:
news, fundamentals, sentiment, bull vs bear debate, risk check) before you invest.
Create a key at console.anthropic.com (pay as you go, roughly a few cents per analysis) and add:
```
ANTHROPIC_API_KEY=sk-ant-...
AI_ANALYST=on                      # set to off to disable
AI_ANALYST_MODEL=claude-opus-5-5   # optional
```
Then install the extra once: `pip install -e '.[ai]'`. The "Ask the AI desk" button appears on every
Invest-now idea and on Charts. Each stock is reviewed at most once every 6 hours (cached) to keep costs low.
Without a key, the app works the same, just without the AI verdicts.

## 4. Hosting (so it runs 24/7 and you can open it anywhere)
Any of: a small VPS (Hetzner / OVH ~€5/month), Railway, Render or Fly.io. Run
`docker compose up -d` (files are ready), set `TRADEBOT_API_TOKEN`, and add HTTPS
(Caddy does it automatically). Optional: buy a domain such as `mayarosero.com` (~€10/year).

## 5. Optional extras
- **Verified commits**: add a GPG or SSH signing key to your GitHub account so commits show "Verified".
- **Install on your phone**: once hosted, open the site in Safari/Chrome → "Add to Home Screen".
- **Better S&P 500 history**: a paid point-in-time constituents dataset (e.g. Norgate Data)
  removes survivorship bias from the picker's backtest.
