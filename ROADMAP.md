# Roadmap to November 5, 2026

Automated work sessions run daily at ~08:00 and ~19:00 Paris time. Each session takes
the first unchecked item, builds it end to end (backend + UI + tests + visual check
on real data), pushes to `main` as Manuelma4, ticks the item here and notifies Manuel.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

## Done
- [x] Engine: data providers, indicators, candlesticks, Dow, Wyckoff, Elliott, backtester
- [x] ML predictor with walk-forward validation
- [x] Real-time movers detector, scanner, paper trading, email/WhatsApp notifiers
- [x] Web platform: FastAPI + WebSocket + React; Alerts, Charts, Predict, Backtest
- [x] Brand: aerospace design system, twin-peak logo, PWA, social preview
- [x] Overview, Discover (themes / sectors / regions), Beat the S&P 500 engine
- [x] Real data: Yahoo (stocks) + Binance data mirror (crypto)

## Next
0. [x] **UX overhaul: everything already computed, nothing to "run"** (Manuel's top priority, Oct 20):
       - A background job precomputes picks (all 4 strategies), ML predictions for every S&P 500 /
         popular stock, and market analysis on a schedule; pages just show results instantly.
         Results show without pressing anything; buttons stay available to customize (time period,
         number of stocks, options) and recompute.
       - New home "Today" board answering at a glance: what to buy / hold / sell now, what is
         surging right now, market mood (S&P trend, breadth), and the engine's top 3 with reasons.
       - Fewer clicks, clearer labels, plain-language explanations ("what this means" hints on every
         number and option, beginner-friendly), stock rows open a detail view,
         consistent empty / loading states, mobile-first layout check.
0b. [x] **Live catalyst-momentum scanner ("invest now")** — the satellite strategy (20–30% of capital;
       the monthly picks stay the core). During market hours, every few minutes, over S&P 500 +
       popular stocks + crypto: flag only stocks that are (a) up strongly today on >= 2x normal volume,
       (b) have a real news catalyst (earnings, guidance, upgrade, contract — fetched from Yahoo news /
       SEC filings), (c) above the 200-day average and near the 52-week high, (d) liquid large caps.
       Moves without news are filtered out (research: they tend to reverse; news-driven moves drift).
       Each signal: entry, stop, target, time limit, one-tap "Invest" (paper broker now), push notification,
       auto-expiry. Validate the rules on history internally; never show backtests on the main screens.
0c. [x] **AI analyst on live candidates**: integrate TradingAgents (Apache-2.0, supports Claude) as an
       optional service — analysts (news, fundamentals, sentiment, technicals), bull/bear debate and a
       risk check produce a short verdict + reasons shown on each opportunity before "Invest". Enabled by
       `ANTHROPIC_API_KEY` in `.env` (documented in LATER.md); app works without it.
0d. [x] **Portfolio builder ("My portfolio")**: enter an amount (e.g. EUR 10,000) and risk level → a diversified,
       ready-to-execute plan built to beat the S&P 500: core (monthly picks, 70-80%) + satellite (live
       opportunities, 20-30%) + optional SPY anchor; sector cap 25%, single-stock cap ~10%, volatility-aware
       weights; shows shares to buy per stock, expected risk vs S&P 500, and what changed since last month
       (buy / sell / keep). Validated walk-forward by quant-researcher; limits reviewed by risk-guardian.
0e. [x] **Live intraday charts + two-sided probabilistic forecasts** (comment from Manuel, Oct 19):
       - Charts open on intraday data (5m / 15m, ~15 min delayed for stocks with free data, real time for
         crypto and later with the paid feed), auto-refresh every minute, live last-price line.
       - Predictions for BOTH directions: long (expected rise) and short (expected fall) signals in the
         scanner, picks and stock pages, with paper short trades; risk-guardian adds short-specific limits
         (stop always required, borrow/margin warning, max short exposure).
       - Quant-style stochastic modelling: Monte Carlo price simulation (bootstrapped returns with GARCH
         volatility) giving a fan chart, P(up) / P(down) at the horizon and the 5-95% expected range.
       - Volume analysis: volume profile (point of control, value area), VWAP and bands, relative volume,
         on-balance volume; volume features feed the ML direction model. Validated walk-forward by
         quant-researcher (calibration of probabilities, not just accuracy).
       - **Predict page rework** (comments from Manuel, Oct 19): opens instantly on precomputed results,
         AND keeps a simple "Customize" panel with a Predict button so Manuel can choose: time horizon in
         plain words (tomorrow / 1 week / 1 month / 3 months), how many stocks to show (5 / 10 / 20 / 50),
         market (S&P 500, popular, Europe, crypto, or his own symbols), direction (rises, falls, both) and
         options like "only uptrends" or "include volume signals". Every option has a one-line "what this
         means" explanation for a non-expert, plus a short "How to read this page" guide. Default view: a
         precomputed ranking of the strongest expected moves for the coming days: top expected
         risers (long) and top expected fallers (short) across the S&P 500 + popular stocks + crypto, each
         with probability, expected range, confidence badge and a one-line reason (momentum, volume,
         news). Tap a row: fan chart + volume profile + what drives the prediction. Model quality shown as
         one plain sentence ("right 56% of the time on unseen data, better than chance"), details collapsed.
1. [x] **Stock detail page** `/stock/:symbol`: price header, chart, key stats (market cap, P/E,
       dividend yield, 52-week range, sector), engine score and factor breakdown, "why / why not
       a pick", similar stocks. Link every symbol in the app to it.
2. [ ] **Full S&P 500 universe**: load all ~500 constituents (bundled list with sector, refreshable),
       picker and Discover use it; keep curated themes.
3. [x] **Watchlists and custom price alerts**: create / edit lists, price-above / below and
       % move alerts stored in SQLite, checked by the live engine, delivered via notifiers + bell.
4. [x] **Monthly picks alert**: when the picker's holdings change (buy / sell list), notify;
       "Picks history" view.
5. [ ] **S&P 500 real-time movers**: scan all constituents intraday in batches; surge / crash feed
       on Overview and Alerts.
6. [ ] **Quality pass**: code-split bundle, loading / empty / error states everywhere, keyboard and
       screen-reader basics, Playwright end-to-end tests of the main flows.
7. [x] **Paid real-time stock data, ready to switch on**: provider adapters for Polygon, Alpaca and
       Finnhub (REST + websocket streaming), selected by `MARKET_DATA_PROVIDER` in `.env`, Yahoo as
       fallback; tests with mocked responses; documented in LATER.md.
8. [ ] **Broker connection (invest from the app)**: broker interface + Alpaca adapter (paper by default),
       IBKR and ccxt adapters; order ticket UI with confirmation, positions and P&L page, max order size,
       daily loss limit and kill switch; real money only when `TRADING_MODE=live`.
9. [ ] **Handover**: email + WhatsApp setup walkthrough (with Manuel), hosting guide, final README.

## Later research track
- Microsoft Qlib + RD-Agent to discover better ranking factors for the monthly core picks
  (offline, validated walk-forward before adoption).

## Rules for every session
- Use the subagents in `.claude/agents/` (see CLAUDE.md): quant-researcher for strategy work, product-designer
  for UI, risk-guardian for anything with money, code-reviewer on the diff, qa-tester before pushing.
- English only. Commits authored by Manuelma4 only, no co-author trailers.
- Tests offline (synthetic data); verify on real data before pushing.
- Never place real orders. Keep honesty notes (survivorship bias, no guaranteed returns).
