# Things for Manuel to do later

The code for each of these is (or will be) ready. You only sign up, pay if needed, and
put the credentials in `.env` on the server. Nothing here is required to use the app today.

## 1. Real-time stock prices (paid)
Today: stocks come from Yahoo Finance (free, often ~15 min delayed); crypto is already real time.
When you want true real-time stocks, pick ONE provider:

| Provider | Price (approx.) | Good for |
|---|---|---|
| Polygon.io "Stocks Starter/Developer" | ~$30–80 / month | All US stocks and indices, real-time websockets |
| Alpaca "Algo Trader Plus" | ~$99 / month | Real-time US data + the same account can trade |
| Finnhub (paid tier) | ~$50+ / month | US + some international markets |

Then in `.env`:
```
MARKET_DATA_PROVIDER=polygon          # or alpaca / finnhub
POLYGON_API_KEY=...                   # or ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY, FINNHUB_API_KEY
```
The app switches automatically; Yahoo stays as the free fallback. (Built in roadmap item 7.)

## 2. Investing from the platform (broker connection)
The app can send orders to a broker through its official API. Plan:
1. **Paper trading first** (fake money, real prices): Alpaca paper account, free.
2. **Real money** when you're confident, with a broker that accepts you as a French resident:
   - **Interactive Brokers (IBKR)**: available in France, US + European stocks, full API. Recommended.
   - **Alpaca**: simple API, mainly US stocks; check that your country is accepted.
   - **Crypto**: Binance or Kraken API keys (trading permission only, never withdrawal).

Safety built in: paper mode by default, real money only with `TRADING_MODE=live` in `.env`,
an order confirmation screen, maximum order size and daily loss limits, and a kill switch.
(Built in roadmap item 8.) In `.env`:
```
TRADING_MODE=paper                    # paper | live
BROKER=alpaca                         # alpaca | ibkr | ccxt
ALPACA_API_KEY_ID=...  ALPACA_API_SECRET_KEY=...
MAX_ORDER_EUR=1000  MAX_DAILY_LOSS_EUR=300
```
Note: investing your own money through your own account is fine. Managing other people's
money or selling signals as a service needs a license in France (AMF); talk to a professional first.

## 3. Hosting (so it runs 24/7 and you can open it anywhere)
Any of: a small VPS (Hetzner / OVH ~€5/month), Railway, Render or Fly.io. Run
`docker compose up -d` (files are ready), set `TRADEBOT_API_TOKEN`, and add HTTPS
(Caddy does it automatically). Optional: buy a domain such as `mayarosero.com` (~€10/year).

## 4. Optional extras
- **Verified commits**: add a GPG or SSH signing key to your GitHub account so commits show "Verified".
- **Install on your phone**: once hosted, open the site in Safari/Chrome → "Add to Home Screen".
- **Better S&P 500 history**: a paid point-in-time constituents dataset (e.g. Norgate Data)
  removes survivorship bias from the picker's backtest.
