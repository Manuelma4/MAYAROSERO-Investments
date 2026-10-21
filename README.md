# MAYAROSERO Investments

A trading **notifications and investing platform** for **stocks, indices and crypto**, built to help
beat the S&P 500: already-computed recommendations, live "invest now" ideas, a diversified portfolio
plan, price alerts and forecasts, delivered in the app, the browser, by email and on WhatsApp.
Everything opens computed and live; a **Customize** panel changes the period, number of stocks and
options, and every number has a short "what this means" hint.

## Start here (Manuel)

Your checklist, in order, with costs: **[docs/YOUR_NEXT_STEPS.md](docs/YOUR_NEXT_STEPS.md)**.

1. **Run it** at home or on a small server: [docs/HOSTING.md](docs/HOSTING.md) (about 10 minutes).
2. **Get alerts on your phone** by email and WhatsApp: [docs/ALERTS_SETUP.md](docs/ALERTS_SETUP.md)
   (about 15 minutes), then check with `python scripts/test_alerts.py`.
3. **Install it on your phone**: open the app in the browser → Add to Home Screen.
4. **Later, when you decide to pay** (real-time prices, a broker for real money, the AI analyst):
   [LATER.md](LATER.md) has the exact `.env` lines for each. Nothing else changes in the code.

| Works now, free | Switch on later in `.env` (LATER.md) |
|---|---|
| Prices from Yahoo (~15 min delayed) and Binance (real time) | Real-time stock prices: Polygon, Alpaca or Finnhub (`MARKET_DATA_PROVIDER`) |
| Invest button on a practice account (10,000 practice money) | A real broker: Alpaca, a crypto exchange or IBKR (`BROKER`, then `TRADING_MODE=live`) |
| All picks, forecasts, alerts, portfolio plan | The AI analyst desk (`ANTHROPIC_API_KEY`) |

## Web platform

| Page | What it does |
|---|---|
| **Today** | Market mood, what to hold this month, buy / sell / keep changes, earnings this week, live track record, today's biggest movers |
| **My portfolio** | A ready-to-buy plan for your amount in €: Cautious / Balanced / Bold (risk matched to the label) or **Simple funds** (60% S&P 500 fund + 40% momentum fund); "How risky is this plan?", save as target with drift alerts |
| **Discover** | ~520 stocks (the full S&P 500 plus curated Europe / Asia names) + crypto by theme, sector and region, and a **Screener** (size, valuation, dividends, trend, momentum) |
| **Beat the S&P** | Default **Core + momentum** (60% S&P 500 + 40% the 10 strongest momentum stocks): this month's picks, why each one, picks history, live track record, and an honest collapsed backtest (realistic edge about +1–2%/yr, not proven) |
| **Invest now** | Stocks and coins moving hard right now on news and heavy volume, with entry / stop / target and an order ticket; the S&P 500 movers board |
| **Stock page** | Any symbol: price (with € value), key figures, next earnings, the engine's verdict, forecast, live idea, similar companies, Set price alert, Add to watchlist |
| **Alerts** | Your price alerts and watchlists, picks updates, earnings, drift, surges / crashes and setup signals, pushed live; weekly digest on Sundays |
| **Charts** | Candlesticks + volume, VWAP, EMAs, Bollinger, patterns, structure (Dow, Wyckoff, Elliott) and a Monte Carlo forecast fan |
| **Predict** | Ranking of which S&P 500 stocks should beat the others, with up / down probabilities and an honest validation (only the 1-day ranking shows a real edge) |
| **Backtest** | Test any setup on history before risking money |
| **Learn** | 5-minute guide, honest expectations, a 55-term glossary with examples, and the first-visit tour |
| **Settings** | Display currency (€ / $), broker and safety limits, Close everything (kill switch), notifications and weekly digest, theme, access token |

Run it:

```bash
pip install -e '.[dev]'
cd web && npm install && npm run build && cd ..
tradebot serve                     # http://127.0.0.1:8000
```

Development (hot reload): `tradebot serve --reload` and, in another shell,
`cd web && npm run dev` (http://localhost:5173, proxies to the API).

Production: `cp .env.example .env` (set `TRADEBOT_API_TOKEN`!), then
`docker compose up -d --build`. Put it behind HTTPS (Caddy / a PaaS) and
enter the token in the UI ("Set access token").

Brand and design system: see [BRAND.md](BRAND.md). Plan: [ROADMAP.md](ROADMAP.md).
Things to switch on later (paid real-time data, broker, hosting): [LATER.md](LATER.md).

Static preview (no server, snapshot of real data):
`cd web && VITE_STATIC=1 npx vite build --base ./ --outDir dist-static && cd .. && python scripts/export_snapshot.py web/dist-static/data`. The app is installable on
phones (Add to Home Screen).

Architecture: FastAPI (REST + WebSocket) over the Python engine, SQLite for
the event history, React + TypeScript + TradingView lightweight-charts for the
UI, one Docker image serving both.

## Engine and CLI

The workflow is:

1. **Analyze**: get a snapshot of a market's structure (trend, swings, RSI,
   ranges, candles, Elliott impulses).
2. **Predict**: a machine-learning model trained on history suggests
   BUY / SELL / HOLD, validated walk-forward against naive baselines.
3. **Detect movers**: real-time surge / crash detection across stocks and
   crypto (abnormal % move + volatility z-score + volume confirmation).
4. **Code your setups**: entry, stop, target and exit rules as a `Strategy`.
5. **Backtest**: run them on historical charts with realistic fills, fees,
   slippage and risk-based position sizing.
6. **Paper trade live**: the scanner watches the market in real time, alerts
   you (console / email / WhatsApp) when a setup triggers, and simulates the trade.
7. **Only then** connect a real broker (Alpaca, a crypto exchange via ccxt, or IBKR): paper / test
   accounts first; real money only when the owner sets `TRADING_MODE=live` (see [LATER.md](LATER.md#2-investing-from-the-platform-broker-connection)).

> **Disclaimer:** this is a research tool, not financial advice. Past
> backtest performance does not guarantee future results. By default no real
> orders are placed: the Invest button uses a practice account (or a broker's
> paper account). Real money needs `TRADING_MODE=live` set by the owner in `.env`.

## Broker connection and order safety

`src/tradebot/trading/brokers/` holds one `Broker` interface and four adapters: `PaperAdapter` (default,
the in-app practice account), `AlpacaBroker` (REST v2, bracket orders), `CCXTBroker` (crypto spot, exchange
testnet in paper mode) and `IBKRBroker` (ib_insync, experimental). Choose with `BROKER=paper|alpaca|ccxt|ibkr`.

- `resolve_endpoint()` in `brokers/base.py` is the only place that decides paper vs real money; it returns a
  live endpoint only when `TRADING_MODE=live`. Adapters call it themselves and accept no URL.
- Every order, whatever the broker, goes through the same server-side path (`api/orders.py::checked_plan`):
  active idea only, fresh price, 1.5% drift check, kill-switch pause, `plan_order` limits (1% risk per trade,
  10% per position, 5 open ideas, 20% short, 3% daily loss incl. open losses, optional `MAX_ORDER_VALUE` /
  `MAX_DAILY_LOSS_VALUE`), one lock.
- `POST /api/orders/preview` returns the plan and a 90-second single-use confirm token; `POST /api/orders`
  needs it. Live orders also require `TRADEBOT_API_TOKEN` (32+ characters, not the example value). `GET /api/broker/status`, `GET /api/broker/positions`,
  `POST /api/orders/close-all` and `POST /api/orders/resume`, both with the JSON body `{"confirm": true}` (kill
  switch: pauses first, then closes; paused until resume, or the next day in paper mode).
  `/api/paper/*` always uses the practice account.
- `tradebot serve` reads `.env` from the repo root (or `--env-file PATH`, or `TRADEBOT_ENV_FILE`), never the working
  directory; variables already set in the shell win, and the startup log says where `TRADING_MODE` came from.
- Real-broker exits close only the journaled quantity and cancel only that order's own legs; a failed close
  re-places the stop. IBKR is paper-only for now.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Usage

```bash
tradebot strategies                                   # list setups and parameters

# Market structure snapshot
tradebot analyze --provider yahoo --symbol AAPL --timeframe 1d
tradebot analyze --provider ccxt  --symbol BTC/USDT --timeframe 4h --limit 1000

# Backtests
tradebot backtest --provider yahoo --symbol ^GSPC --timeframe 1d --strategy dow_pullback --start 2010-01-01
tradebot backtest --provider ccxt --symbol ETH/USDT --timeframe 1h --strategy ema_cross_rsi \
    --start 2023-01-01 --params '{"fast": 10, "slow": 30, "rr": 3}' --out reports/eth
tradebot backtest --csv my_data.csv --strategy wyckoff_spring --long-only

# Prediction (one or several symbols pooled into one model)
tradebot predict --provider yahoo --symbol AAPL,MSFT,NVDA,GOOGL --timeframe 1d --horizon 5
tradebot predict --provider ccxt --symbol BTC/USDT,ETH/USDT --timeframe 1h --limit 5000 --horizon 6

# Real time
cp config/config.example.yaml config/config.yaml      # edit your watchlist and movers universe
tradebot movers --config config/config.yaml           # single pass of the surge/crash detector
tradebot scan --config config/config.yaml             # single pass of setups + movers
tradebot live --config config/config.yaml             # loop forever
```

### Alerts: email and WhatsApp

Copy `.env.example` to `.env` (git-ignored), fill in the credentials, and set
`notifiers: [console, email, whatsapp]` in the config.

- **Email**: any SMTP server. For Gmail use `smtp.gmail.com` and an
  [App Password](https://myaccount.google.com/apppasswords).
- **WhatsApp**: via the [Twilio API](https://www.twilio.com/docs/whatsapp).
  The free sandbox works for personal alerts: send the join code from your
  phone to the sandbox number once, then use it as `TWILIO_WHATSAPP_FROM`.

## Prediction model: how to read it

`tradebot predict` trains a gradient-boosting classifier on ~30 features
(returns, volatility, EMA distances, RSI, MACD, Bollinger position, volume,
Dow trend, candlestick bias, distance to highs/lows) to predict whether the
next `horizon` bars move up, down or sideways (relative to ATR).

- Validation is **walk-forward**: always trained on the past, tested on the
  unseen future, with a purge gap so labels can't leak.
- The report compares the model with the naive baseline. If it doesn't beat
  it out of sample, the output says **"statistical edge: NO"**: don't trade it.
- The test suite checks that the model finds **no** edge on pure random
  walks (a leak detector) and **does** find a genuine hidden cycle.
- Realistic expectations: 52-56% directional accuracy with good risk
  management is considered valuable by professional quant funds. Results that
  look too good usually mean a bug or overfitting.

## Movers detector

Flags a symbol when, over the last few closed intraday bars, all three hold:
the move is at least `min_move_pct`, it is `min_zscore` standard deviations
beyond the symbol's own normal volatility, and the peak-bar volume is at least
`min_volume_ratio` times average. Universe: your list + Yahoo's
`day_gainers` / `day_losers` / `most_actives` screeners + top-N crypto pairs
by 24h volume. A sudden move is information, not a buy signal: combine it
with your setups and risk rules.

## Data sources

| Market | Provider | Notes |
|---|---|---|
| Crypto | `ccxt` (Binance by default, any ccxt exchange via `--exchange`) | Real time, no API key needed |
| Stocks, indices, ETFs, FX | `yahoo` (yfinance) | Free; intraday is often ~15 min delayed. Intraday history is limited (1m: 7 days, <1h: 60 days) |

Paid real-time stock feeds (Polygon, Alpaca, Finnhub) are built in (`src/tradebot/data/paid.py`) and switch on
with `MARKET_DATA_PROVIDER` + a key; Yahoo stays the automatic fallback. See [LATER.md](LATER.md).

## Project layout

```
src/tradebot/
  data/providers.py        Yahoo + ccxt providers, normalized OHLCV
  indicators.py            EMA, SMA, RSI, ATR, MACD, Bollinger, VWAP, volume ratio
  analysis/
    candlesticks.py        doji, hammer, shooting star, engulfing, morning/evening star
    swings.py              pivots (confirmed, no look-ahead) and zigzag
    dow.py                 Dow trend from HH/HL vs LH/LL
    wyckoff.py             trading range, springs, upthrusts
    elliott.py             5-wave impulse rule checker + Fibonacci guidelines
  strategies/              your setups (one file each) + registry
  backtest/                engine + metrics
  ml/                      features, labels, walk-forward validated predictor
  live/                    real-time scanner, movers detector, email/WhatsApp notifiers, paper broker
  report.py                market snapshot (data for the API, text for the CLI)
  data/paid.py             Polygon / Alpaca / Finnhub adapters with Yahoo fallback (+ data/streaming.py)
  data/sp500.csv           S&P 500 members with sector and industry
  universe.py              curated stocks + the S&P 500 by sector / theme / region (Discover + picker)
  picker.py                factor ranking + monthly rebalanced portfolio vs benchmark
  portfolio.py             diversified ready-to-buy plan (core / ideas / anchor, sector caps)
  forecast.py              Monte Carlo fan, volume profile, VWAP bands
  ml/ranker.py             weekly cross-sectional ranker with walk-forward IC
  ai/analyst.py            optional AI analyst desk (Anthropic API key)
  live/alerts.py           price alerts; live/opportunities.py "invest now" scanner + movers board
  trading/                 risk limits, broker adapters (paper / Alpaca / ccxt / IBKR), safety guard
  api/                     FastAPI app: routes, orders, precompute, WebSocket broadcast, SQLite store
  cli.py
web/                       React + TypeScript UI (Vite)
docs/                      hosting guide, alerts setup walkthrough
tests/                     offline tests on synthetic data, incl. tests/e2e (Playwright, desktop + phone)
```

## Writing your own setup

Create `src/tradebot/strategies/my_setup.py`:

```python
import numpy as np
from .. import indicators as ta
from ..analysis import candlesticks as cs, dow
from .base import Strategy

class MySetup(Strategy):
    name = "my_setup"
    description = "Uptrend + bullish engulfing above EMA50"
    defaults = {"ema": 50, "atr_stop": 1.5, "rr": 2.5}

    def signals(self, df):
        e = ta.ema(df["close"], self.p("ema"))
        a = ta.atr(df)
        long_ok = (dow.trend(df) == 1) & cs.bullish_engulfing(df) & (df["close"] > e)
        df["entry_long"] = long_ok
        stop = df["low"] - self.p("atr_stop") * a
        df["stop"] = np.where(long_ok, stop, np.nan)
        df["target"] = np.where(long_ok, df["close"] + self.p("rr") * (df["close"] - stop), np.nan)
        return df
```

Then register it in `strategies/__init__.py`. A strategy fills these columns:
`entry_long`, `entry_short`, `exit_long`, `exit_short` (bool), and `stop`,
`target` (prices on entry bars).

## Backtest realism rules

- Signals are computed on a bar's **close** and filled at the **next open**.
- If stop and target are both touched in one bar, the **stop** is assumed.
- Gaps through a stop fill at the open (worse price).
- Swing pivots are only used once **confirmed** (`right` bars later), so Dow
  and pullback logic never peeks into the future. Tests enforce this
  (`tests/test_backtest.py::test_signals_have_no_lookahead`).
- Watch for overfitting: tune parameters on one period, validate on another.

## Tests

```bash
OMP_NUM_THREADS=1 pytest            # everything, offline (~3 min)
pytest -m "not e2e"                 # skip the browser tests
```

Plan and status: [ROADMAP.md](ROADMAP.md).
