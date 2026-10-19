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
0. [ ] **UX overhaul: everything already computed, nothing to "run"** (Manuel's top priority, Oct 20):
       - A background job precomputes picks (all 4 strategies), ML predictions for every S&P 500 /
         popular stock, and market analysis on a schedule; pages just show results instantly.
         Remove Run / Train & predict buttons (keep advanced settings tucked away).
       - New home "Today" board answering at a glance: what to buy / hold / sell now, what is
         surging right now, market mood (S&P trend, breadth), and the engine's top 3 with reasons.
       - Fewer clicks, clearer labels, plain-language explanations, stock rows open a detail view,
         consistent empty / loading states, mobile-first layout check.
0b. [ ] **Live opportunities ("invest now")**: intraday scanner over S&P 500 + popular stocks + crypto
       flags stocks surging within the hour (move + volume + trend confirmation), ranks them, shows
       entry / stop / target and a one-tap "Invest" action (paper broker now, real broker in item 8),
       pushes a notification, auto-expires stale signals.
1. [ ] **Stock detail page** `/stock/:symbol`: price header, chart, key stats (market cap, P/E,
       dividend yield, 52-week range, sector), engine score and factor breakdown, "why / why not
       a pick", similar stocks. Link every symbol in the app to it.
2. [ ] **Full S&P 500 universe**: load all ~500 constituents (bundled list with sector, refreshable),
       picker and Discover use it; keep curated themes.
3. [ ] **Watchlists and custom price alerts**: create / edit lists, price-above / below and
       % move alerts stored in SQLite, checked by the live engine, delivered via notifiers + bell.
4. [ ] **Monthly picks alert**: when the picker's holdings change (buy / sell list), notify;
       "Picks history" view.
5. [ ] **S&P 500 real-time movers**: scan all constituents intraday in batches; surge / crash feed
       on Overview and Alerts.
6. [ ] **Quality pass**: code-split bundle, loading / empty / error states everywhere, keyboard and
       screen-reader basics, Playwright end-to-end tests of the main flows.
7. [ ] **Paid real-time stock data, ready to switch on**: provider adapters for Polygon, Alpaca and
       Finnhub (REST + websocket streaming), selected by `MARKET_DATA_PROVIDER` in `.env`, Yahoo as
       fallback; tests with mocked responses; documented in LATER.md.
8. [ ] **Broker connection (invest from the app)**: broker interface + Alpaca adapter (paper by default),
       IBKR and ccxt adapters; order ticket UI with confirmation, positions and P&L page, max order size,
       daily loss limit and kill switch; real money only when `TRADING_MODE=live`.
9. [ ] **Handover**: email + WhatsApp setup walkthrough (with Manuel), hosting guide, final README.

## Rules for every session
- English only. Commits authored by Manuelma4 only, no co-author trailers.
- Tests offline (synthetic data); verify on real data before pushing.
- Never place real orders. Keep honesty notes (survivorship bias, no guaranteed returns).
