# MAYAROSERO Investments

A trading **notifications and charting platform** for **stocks, indices and
crypto**: real-time alerts when markets surge or crash, interactive charts
with classic technical analysis (Japanese candlesticks, Dow theory, Wyckoff,
Elliott waves), ML predictions validated on unseen data, and a backtester to
prove your setups before risking money. Alerts reach you in the browser, by
email and on WhatsApp.

## Web platform

| Page | What it does |
|---|---|
| **Overview** | Live indices, crypto, commodities with sparklines, watchlist, top movers, latest alerts |
| **Discover** | ~520 stocks (the full S&P 500 plus curated Europe / Asia names) + crypto organized by theme (Magnificent 7, AI & chips, Luxury…), GICS sector and region, with live sector performance |
| **Beat the S&P** | Factor engine ranks the S&P 500 monthly, shows this month's picks and a backtest vs SPY (dividends included), net of costs |
| **Alerts** | Live feed of big movers (surges / crashes) and setup signals, pushed over WebSocket; engine control; paper-trading positions |
| **Charts** | Candlesticks + volume, EMA 20/50/200, Bollinger, swing pivots, candlestick patterns, RSI, and a structure panel (Dow trend, Wyckoff range, Elliott impulse) |
| **Predict** | Train the model on one or many symbols, see BUY / HOLD / SELL probabilities and the out-of-sample validation |
| **Backtest** | Run any setup on history: equity vs buy & hold, trades on chart, full stats |

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

For true real-time stock data later, add a provider (Alpaca, Polygon,
Interactive Brokers) in `src/tradebot/data/providers.py` implementing
`DataProvider.history()`.

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
  universe.py              curated stocks by sector / theme / region (Discover + picker)
  picker.py                factor ranking + monthly rebalanced portfolio vs benchmark
  api/                     FastAPI app: routes, live engine, WebSocket broadcast, SQLite store
  cli.py
web/                       React + TypeScript UI (Vite)
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

## Roadmap

- [ ] Walk-forward / out-of-sample parameter optimization
- [ ] Multi-timeframe confirmation (e.g. daily trend + 1h entry)
- [ ] Equity curve and trade charts (matplotlib / plotly)
- [ ] Portfolio-level backtests across many symbols
- [ ] Broker adapters (ccxt with API keys, Alpaca / IBKR) behind a kill switch
- [ ] Deploy the live scanner on a small server / container
