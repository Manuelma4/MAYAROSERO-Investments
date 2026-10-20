/**
 * Plain-English glossary of every term the app uses, for the Learn page and the "Learn more" links in hints.
 * Each entry: one-sentence definition, where it shows up in this app, and a tiny example with numbers.
 * Keep ids stable: hints link to /learn?term=<id>.
 */
export interface GlossaryEntry {
  /** Stable slug used in links (/learn?term=id). */
  id: string;
  /** The word as shown in the app. */
  term: string;
  /** Other names people search for (abbreviations, synonyms). */
  aka?: readonly string[];
  /** One sentence, no jargon. */
  definition: string;
  /** Where and how this app uses it. */
  inApp: string;
  /** A tiny worked example with numbers. */
  example: string;
  /** Ids of closely related entries. */
  related?: readonly string[];
}

export const GLOSSARY = [
  {
    id: "200-day-average", term: "200-day average", aka: ["200-day moving average", "EMA 200", "SMA 200", "long-term trend"],
    definition: "The average closing price over the last 200 trading days (about 10 months): a simple way to see the long-term trend.",
    inApp: "Today's market mood and the bear-market filter on Beat the S&P check whether the S&P 500 is above it. Charts draw it as EMA 200.",
    example: "SPY at 580 with a 200-day average of 540 is 7% above it: the long-term wind is at its back.",
    related: ["uptrend", "risk-on-off"],
  },
  {
    id: "52-week-high", term: "52-week high", aka: ["year high", "from high", "distance from high"],
    definition: "The highest price a stock reached over the last year (52 weeks).",
    inApp: "Discover › Screener shows how far each stock is below it.",
    example: "High 200, price now 150: 25% below its 52-week high. Close to 0% means it trades near the top of its year.",
    related: ["momentum", "drawdown"],
  },
  {
    id: "atr", term: "ATR (daily range)", aka: ["average true range", "daily range"],
    definition: "How much a price typically moves in one candle, shown as a percentage of the price.",
    inApp: "Charts › Structure shows it as Daily range; Invest-now stop-losses are placed about 1.5 times this range away.",
    example: "A 200 stock with a 2% daily range usually moves about 4 a day, so a stop 1 away would be hit by normal noise.",
    related: ["stop-loss", "volatility"],
  },
  {
    id: "backtest", term: "Backtest", aka: ["track record", "historical test"],
    definition: "Testing a set of rules on past prices to see how they would have done, before risking money on them.",
    inApp: "The Backtest page tests chart setups; Beat the S&P has a collapsed track record. Orders fill at the next day's open and costs are included.",
    example: "\"Hold the 10 strongest S&P 500 stocks, review monthly\" turned 100 into about 660 from 2015 in the test. A test, not a promise.",
    related: ["look-ahead", "survivorship-bias", "out-of-sample"],
  },
  {
    id: "benchmark", term: "Benchmark", aka: ["yardstick", "index comparison"],
    definition: "What you compare your results with, to know whether your choices actually helped.",
    inApp: "The benchmark everywhere is the S&P 500, measured with SPY with dividends included.",
    example: "Your portfolio made 9% in a year while SPY made 12%: you made money but lagged the benchmark by 3 points.",
    related: ["sp500", "spy"],
  },
  {
    id: "beta", term: "Beta",
    definition: "How much a stock or portfolio tends to move when the whole market moves 1%.",
    inApp: "My portfolio › Risk compared with the S&P 500.",
    example: "Beta 1.2: if the S&P 500 drops 10%, expect roughly a 12% drop.",
    related: ["volatility"],
  },
  {
    id: "bid-ask-spread", term: "Bid / ask spread", aka: ["spread", "bid", "ask"],
    definition: "The gap between the highest price a buyer offers (bid) and the lowest price a seller accepts (ask).",
    inApp: "Large, busy stocks like those in the S&P 500 have tiny spreads; small stocks and some crypto pairs have wider ones, which costs you on every trade.",
    example: "Bid 99.98, ask 100.02: the spread is 0.04, so buying and selling straight away loses 0.04 per share.",
    related: ["slippage", "limit-vs-market"],
  },
  {
    id: "cagr", term: "CAGR (per year)", aka: ["compound annual growth rate", "a year", "/ yr", "annual return"],
    definition: "The steady yearly growth rate that would turn the starting value into the ending value.",
    inApp: "Every \"a year\" or \"/ yr\" figure on Today, Beat the S&P and Backtest is a CAGR.",
    example: "10,000 growing to 20,000 in 6 years is about 12.2% a year, not 16.7% (100% ÷ 6), because gains compound.",
    related: ["compounding"],
  },
  {
    id: "candle", term: "Candle", aka: ["candlestick", "bar"],
    definition: "One bar on a chart showing the open, high, low and close price for a period (a day, an hour).",
    inApp: "Charts and stock pages draw candles; letters on Charts mark well-known candle patterns.",
    example: "Open 100, high 104, low 99, close 103: a green daily candle because it closed above where it opened.",
  },
  {
    id: "compounding", term: "Compounding",
    definition: "Earning returns on your past returns, so growth speeds up over time.",
    inApp: "Why small yearly differences in CAGR matter so much over 10 years on Beat the S&P.",
    example: "10,000 at 14% a year becomes about 37,000 in 10 years; at 17% it becomes about 48,000.",
    related: ["cagr"],
  },
  {
    id: "diversification", term: "Diversification", aka: ["spreading risk"],
    definition: "Spreading money across many different investments so one bad one cannot sink you.",
    inApp: "My portfolio caps any sector at 25% and any single stock at 10%; picks are held in equal parts.",
    example: "With 10 equal positions, one stock falling 50% costs the portfolio 5%, not 50%.",
    related: ["sector", "equal-weight", "position-size"],
  },
  {
    id: "dividend-yield", term: "Dividend yield", aka: ["dividend"],
    definition: "The yearly cash a company pays its shareholders, as a percentage of the share price.",
    inApp: "Key figures on every stock page. The S&P 500 comparison (SPY) includes dividends.",
    example: "A 100 stock paying 3 a year in dividends has a 3% yield.",
  },
  {
    id: "drawdown", term: "Drawdown", aka: ["worst drop", "max drawdown", "worst drawdown"],
    definition: "The fall from a peak to the lowest point before a new high: how painful the bad patch was.",
    inApp: "\"Worst drop\" on Backtest and \"Worst drawdown\" in the Beat the S&P track record.",
    example: "12,000 falling to 9,000 is a 25% drawdown, and it then takes a 33% gain just to get back to 12,000.",
    related: ["volatility", "risk-per-trade"],
  },
  {
    id: "drift", term: "Drift", aka: ["portfolio drift", "off plan"],
    definition: "How far your real holdings have moved away from your planned weights as prices change.",
    inApp: "My portfolio › My target and drift compares what you hold with the saved plan and sends an alert when the gap gets big.",
    example: "Planned 10% in a stock, it rallied and is now 18%: a drift of 8 points.",
    related: ["rebalance"],
  },
  {
    id: "earnings", term: "Earnings", aka: ["earnings report", "results", "quarterly results"],
    definition: "A company's quarterly report of sales and profit, one of the biggest scheduled price movers.",
    inApp: "Stock pages show profit growth and P/E from these reports; news-driven Invest-now ideas often follow them.",
    example: "Profit of 1.20 per share when analysts expected 1.00 can lift the stock 8% the next morning; a miss can drop it 10%.",
    related: ["pe-ratio"],
  },
  {
    id: "equal-weight", term: "Equal weight",
    definition: "Putting the same amount of money in each holding.",
    inApp: "The Beat the S&P picks are held equal weight: 10 stocks means 10% each.",
    example: "5,000 split across 10 picks is 500 in each.",
    related: ["diversification", "rebalance"],
  },
  {
    id: "etf", term: "ETF", aka: ["exchange-traded fund", "index fund"],
    definition: "A fund holding a basket of investments that you buy and sell like a single stock.",
    inApp: "SPY, the yardstick for every comparison, is an ETF that holds the whole S&P 500.",
    example: "One share of an S&P 500 ETF at 580 gives you a small slice of 500 companies at once.",
    related: ["spy", "diversification"],
  },
  {
    id: "exchange-rate", term: "Exchange rate / currency risk", aka: ["currency risk", "EUR/USD", "FX", "euro dollar rate", "conversion"],
    definition: "How many dollars one euro buys today. It moves every day, so a US stock can gain in dollars and still lose a little in euros, or the other way round.",
    inApp: "Settings › Display currency shows money in euros (or dollars) at the live EUR/USD rate. Stock prices stay in their own currency with the converted value next to them, and the risk view of a euro plan includes the rate's moves.",
    example: "At 1 € = $1.16, a $531 Apple share is about €458. If the dollar weakens to 1 € = $1.25 and Apple does not move, it is worth about €425: a 7% loss in euros from the currency alone. Your broker also adds a small conversion fee.",
    related: ["diversification", "volatility"],
  },
  {
    id: "expectancy", term: "Expectancy", aka: ["average R", "avg R"],
    definition: "The average result per trade, measured in units of risk (R).",
    inApp: "Backtest stats and the Invest-now part of the live track record.",
    example: "Win 40% of trades at +2R and lose 60% at −1R: 0.4 × 2 − 0.6 × 1 = +0.2R per trade on average.",
    related: ["reward-risk", "win-rate"],
  },
  {
    id: "fractional-shares", term: "Fractional shares",
    definition: "Buying part of one share, so every euro can be invested even in expensive stocks.",
    inApp: "My portfolio › Customize has a tick box for brokers that allow it (Trade Republic, Revolut, IBKR).",
    example: "With 300 for a 600 stock, you can buy 0.5 shares instead of none.",
  },
  {
    id: "index", term: "Index", aka: ["stock index", "market index"],
    definition: "A number that tracks a group of stocks, used to measure a whole market.",
    inApp: "Today shows indices like the S&P 500, Nasdaq 100, CAC 40 and DAX.",
    example: "If the S&P 500 goes from 5,000 to 5,500 points, the market rose 10%.",
    related: ["sp500"],
  },
  {
    id: "information-coefficient", term: "Information coefficient (IC)", aka: ["IC", "rank correlation"],
    definition: "How well a model's ranking matches what actually happened next, from −1 (always wrong) to +1 (perfect).",
    inApp: "Predict measures each model's IC on years of data it never saw, and says so when there is no real edge.",
    example: "An IC of 0.03 sounds tiny but is useful to quant funds; an IC of 0.30 would almost certainly be a mistake in the test.",
    related: ["out-of-sample"],
  },
  {
    id: "kill-switch", term: "Kill switch", aka: ["close everything", "emergency stop"],
    definition: "An emergency button that stops new orders and closes every open position.",
    inApp: "Settings › Trading › Close everything. It pauses orders, cancels open ones and closes all positions at the market price.",
    example: "Something looks wrong at 15:30: one press, and within seconds no orders are pending and every position is closed.",
    related: ["paper-account"],
  },
  {
    id: "limit-vs-market", term: "Limit vs market order", aka: ["limit order", "market order", "order type"],
    definition: "A market order buys now at whatever price is available; a limit order sets the worst price you accept.",
    inApp: "The Invest button sends limit orders, so a sudden jump cannot fill you at a surprising price. The kill switch uses market orders to get out fast.",
    example: "Ask 100.10: a market buy in a fast market might fill at 100.25; a limit at 100.15 never pays more, but may not fill at all.",
    related: ["bid-ask-spread", "slippage"],
  },
  {
    id: "look-ahead", term: "Look-ahead bias", aka: ["future data", "hindsight"],
    definition: "A test mistake: using information that was not known yet at the moment of the decision.",
    inApp: "Every strategy is checked automatically for it, and backtests buy at the next day's opening price.",
    example: "Deciding with Monday's closing price but buying at that same close is look-ahead: you only know it once the market is shut, so the test buys at Tuesday's open.",
    related: ["backtest", "survivorship-bias"],
  },
  {
    id: "market-cap", term: "Market cap", aka: ["market value", "market capitalisation", "company size"],
    definition: "What the whole company is worth on the stock market: share price times number of shares.",
    inApp: "\"Market value\" in Key figures on every stock page, and the Size filter of Discover › Screener.",
    example: "15 billion shares at 200 each is a 3 trillion market cap.",
  },
  {
    id: "momentum", term: "Momentum",
    definition: "The tendency of stocks that rose strongly over the past 6 to 12 months to keep doing better than others for a while.",
    inApp: "The core of the Beat the S&P picks: the \"12M ex-1M\" column is the past year's return without the most recent month.",
    example: "Stock A rose 45% over the year (leaving out last month), stock B rose 5%: momentum prefers A.",
    related: ["relative-strength", "uptrend"],
  },
  {
    id: "monte-carlo", term: "Monte Carlo simulation", aka: ["simulation", "forecast", "simulated futures"],
    definition: "Running thousands of random \"what if\" futures built from past price moves, to see the range of likely outcomes.",
    inApp: "The Forecast on Charts and stock pages runs 5,000 paths over the next 5 trading days.",
    example: "If 3,100 of 5,000 paths end above today's price, \"chance higher\" is 62%. A range of odds, not a promise.",
    related: ["volatility"],
  },
  {
    id: "out-of-sample", term: "Out-of-sample", aka: ["walk-forward", "unseen data"],
    definition: "Testing a model on data it was not trained on, the only honest way to judge it.",
    inApp: "Predict's accuracy figures come from years of data each model never saw.",
    example: "Train on 2015–2020, test on 2021–2025: if the edge vanishes in 2021–2025, it was never real.",
    related: ["information-coefficient", "backtest"],
  },
  {
    id: "paper-account", term: "Paper (practice) account", aka: ["paper trading", "practice money", "demo account", "paper"],
    definition: "An account with pretend money that behaves like a real one, so you can practise without risk.",
    inApp: "The default for the Invest button. Real money is only possible when you set TRADING_MODE=live on the server yourself.",
    example: "Buy 10 shares at 50 in practice: the account shows a 500 position and its profit or loss, and no real money moves.",
    related: ["kill-switch", "risk-per-trade"],
  },
  {
    id: "pe-ratio", term: "P/E ratio", aka: ["price/earnings", "PE", "price to earnings"],
    definition: "Share price divided by yearly profit per share: how many years of current profits you pay for.",
    inApp: "Key figures on every stock page, for the last and the next 12 months; the Valuation filter of Discover › Screener.",
    example: "Price 100, profit 5 per share: a P/E of 20. The S&P 500 is usually around 20 to 25.",
    related: ["earnings"],
  },
  {
    id: "position-size", term: "Position size", aka: ["quantity", "how many shares"],
    definition: "How many shares to buy, worked out from how much you are willing to lose if the stop-loss is hit.",
    inApp: "The Invest ticket calculates it for you from the risk per trade and the distance to the stop.",
    example: "Account 10,000, risk 1% = 100. Entry 50, stop 48: 2 at risk per share, so 50 shares (2,500 invested).",
    related: ["risk-per-trade", "stop-loss"],
  },
  {
    id: "rebalance", term: "Rebalance", aka: ["review", "monthly review"],
    definition: "Bringing the portfolio back to its plan: selling what grew too big and buying what fell behind or is new.",
    inApp: "The picks are reviewed at each month end (Changes at the last review); My portfolio suggests amounts when you drift.",
    example: "Target 10% each; one stock grew to 16%: sell 6 points of it and use the cash for the new picks.",
    related: ["drift", "equal-weight"],
  },
  {
    id: "relative-strength", term: "Relative strength", aka: ["vs S&P", "beating the index"],
    definition: "How a stock did compared with the market over the same period.",
    inApp: "The \"vs S&P 6M\" column on Beat the S&P; picks must be beating the index.",
    example: "Stock up 20% in 6 months while the S&P 500 rose 8%: relative strength of +12 points.",
    related: ["momentum"],
  },
  {
    id: "relative-volume", term: "Relative volume", aka: ["vol 2x", "unusual volume", "heavy volume"],
    definition: "Today's trading volume compared with a normal day at the same time of day.",
    inApp: "\"Vol\" on the movers boards; an Invest-now idea needs at least 1.8x normal volume.",
    example: "Usually 1 million shares traded by noon, today 2.5 million: relative volume 2.5x, so many people are acting on something.",
    related: ["volume"],
  },
  {
    id: "reward-risk", term: "Reward / risk (R)", aka: ["R", "R multiple", "risk reward", "R:R"],
    definition: "The possible gain divided by the possible loss; one R is the amount you risk on a trade.",
    inApp: "Invest-now ideas aim for about 2R; Backtest results are counted in R (+2.0R won twice the risk).",
    example: "Entry 100, stop 97 (risk 3), target 106 (reward 6): 2 to 1. A win is +2R, a loss −1R, so winning 40% of the time still pays.",
    related: ["stop-loss", "target", "expectancy"],
  },
  {
    id: "risk-on-off", term: "Risk-on / risk-off", aka: ["market mood", "bear market", "bull market"],
    definition: "Whether the overall market is calm and rising (risk-on) or falling and nervous (risk-off).",
    inApp: "Today's market mood combines the S&P 500 trend, how many stocks are in an uptrend, and the VIX.",
    example: "S&P 500 above its 200-day average, 65% of stocks in uptrends, VIX at 14: risk-on.",
    related: ["200-day-average", "vix"],
  },
  {
    id: "risk-per-trade", term: "Risk per trade", aka: ["risk per idea", "risk %"],
    definition: "The share of your account you accept to lose on one idea if its stop-loss is hit.",
    inApp: "Settings › Safety limits; the Invest ticket sizes every order to it.",
    example: "1% of 20,000 is 200 per idea. Even ten losses in a row leave about 18,000.",
    related: ["position-size", "stop-loss"],
  },
  {
    id: "rsi", term: "RSI", aka: ["relative strength index", "overbought", "oversold"],
    definition: "A 0 to 100 gauge of recent buying versus selling pressure.",
    inApp: "Charts › Structure shows RSI 14.",
    example: "RSI 78 after a 15% run in two weeks: stretched (overbought), a pause is common. RSI 25: oversold.",
    related: ["momentum"],
  },
  {
    id: "screener", term: "Screener", aka: ["stock screener", "filter stocks"],
    definition: "A tool that filters a long list of stocks down to the ones matching your conditions.",
    inApp: "Discover › Screener filters the 520 stocks by sector, size, P/E, dividend, trend and momentum. A starting list to study, not a list to buy.",
    example: "\"Pays 2%+ dividend\" and \"in an uptrend\" might leave 60 of 520 stocks to look at more closely.",
    related: ["pe-ratio", "dividend-yield", "momentum"],
  },
  {
    id: "sector", term: "Sector", aka: ["industry"],
    definition: "A group of companies in the same kind of business, like technology, health care or energy.",
    inApp: "Discover groups stocks by sector (and the Screener filters by it); My portfolio keeps any sector under 25%.",
    example: "Apple, Microsoft and Nvidia are all technology: 3 of 10 equal picks is 30% in one sector.",
    related: ["diversification"],
  },
  {
    id: "selection-skill", term: "Selection skill",
    definition: "How much better the picks did than simply holding all the same stocks in equal parts.",
    inApp: "Beat the S&P track record and the hint under Today's picks. The most honest measure of the engine.",
    example: "Picks 17.4% a year, same stocks held equally 13.1%: a selection skill of about 4.3 points a year.",
    related: ["survivorship-bias", "benchmark"],
  },
  {
    id: "sharpe", term: "Sharpe ratio", aka: ["sharpe"],
    definition: "Return earned per unit of ups and downs, after subtracting what cash would have paid.",
    inApp: "Beat the S&P track record and Backtest. Below 0.5 is weak, around 1 is good, above 2 is rare.",
    example: "12% a year with 20% volatility while cash pays 2%: (12 − 2) ÷ 20 = 0.5.",
    related: ["volatility", "cagr"],
  },
  {
    id: "short-selling", term: "Short selling", aka: ["short", "sell short", "betting on a fall"],
    definition: "Betting on a fall: you borrow shares, sell them now and buy them back later, hopefully cheaper.",
    inApp: "SHORT ideas and signals are marked in red; Settings caps how much of the account can be short.",
    example: "Short at 100, buy back at 90: +10 a share. If it rises to 130 instead: −30, and there is no ceiling on the loss.",
  },
  {
    id: "slippage", term: "Slippage",
    definition: "The difference between the price you expected and the price you actually got.",
    inApp: "Backtests subtract costs on every trade (0.10% on Beat the S&P) so results are not too rosy.",
    example: "Expected 50.00, filled at 50.05: 0.05 of slippage, 0.1% of the price, on every share.",
    related: ["bid-ask-spread", "limit-vs-market"],
  },
  {
    id: "sp500", term: "S&P 500", aka: ["S&P", "SP500", "the market"],
    definition: "An index of about 500 of the largest US companies, the standard measure of the US stock market.",
    inApp: "Picks are chosen among its members, and \"Beat the S&P\" means doing better than it.",
    example: "Since 2015 it grew about 13.7% a year including dividends: 10,000 became roughly 45,000.",
    related: ["spy", "benchmark", "index"],
  },
  {
    id: "spy", term: "SPY",
    definition: "The best-known ETF that tracks the S&P 500: one share holds a tiny slice of all 500 companies.",
    inApp: "The yardstick in every comparison, with dividends included.",
    example: "10,000 in SPY when the index rises 10% becomes about 11,000, minus a 0.09% yearly fee.",
    related: ["sp500", "etf"],
  },
  {
    id: "stop-loss", term: "Stop-loss", aka: ["stop", "SL"],
    definition: "A price at which you exit a position to cap the loss when you are wrong.",
    inApp: "Every Invest-now idea and setup signal has one; the order ticket places it with the order.",
    example: "Buy at 100, stop at 95: you plan to lose at most about 5%. A gap overnight can make the loss bigger.",
    related: ["target", "reward-risk", "position-size"],
  },
  {
    id: "survivorship-bias", term: "Survivorship bias", aka: ["join-date bias", "point-in-time"],
    definition: "A test mistake: only testing companies that are still around today, which hides the losers and flatters results.",
    inApp: "The picks test counts each stock only from the day it joined the S&P 500. Without that fix the same test showed 37% a year instead of 17%.",
    example: "Testing today's S&P 500 members back to 2015 quietly \"knows\" which small companies would grow into giants.",
    related: ["look-ahead", "backtest", "selection-skill"],
  },
  {
    id: "target", term: "Target", aka: ["take-profit", "TP", "price target"],
    definition: "The price at which you plan to take your gain.",
    inApp: "Invest-now targets sit about twice as far as the stop-loss. Reaching it is never guaranteed.",
    example: "Entry 100 with a stop at 97 (3 of risk): the target is 106 (6 of reward).",
    related: ["stop-loss", "reward-risk"],
  },
  {
    id: "turnover", term: "Turnover",
    definition: "How much of the portfolio is bought and sold at each review.",
    inApp: "Shown next to \"Months beating index\" in the Beat the S&P track record.",
    example: "Turnover of 75% on a 10,000 portfolio means about 7,500 of buying and selling, each with small costs.",
    related: ["rebalance", "slippage"],
  },
  {
    id: "uptrend", term: "Uptrend", aka: ["trend", "downtrend", "higher highs"],
    definition: "A price making higher highs and higher lows; in this app also a price above its 200-day average.",
    inApp: "Beat the S&P keeps only stocks in an uptrend by default; Charts › Structure names the current trend.",
    example: "Peaks at 100, 108, 115 and dips at 92, 99, 104: an uptrend.",
    related: ["200-day-average", "momentum"],
  },
  {
    id: "vix", term: "VIX", aka: ["fear index", "volatility index"],
    definition: "An index of how big a move traders expect in the S&P 500 over the next month: the market's fear gauge.",
    inApp: "Part of Today's market mood.",
    example: "VIX around 13 to 17 is calm; above 30 means fear, as in March 2020 when it passed 80.",
    related: ["risk-on-off", "volatility"],
  },
  {
    id: "volatility", term: "Volatility", aka: ["vol", "swings", "risk"],
    definition: "How much a price swings up and down, usually measured over a year.",
    inApp: "The Forecast, My portfolio's risk card and the picks' \"calmer price action\" filter.",
    example: "20% yearly volatility on a 100 stock: a typical year ends roughly between 80 and 120.",
    related: ["drawdown", "sharpe", "beta"],
  },
  {
    id: "volume", term: "Volume",
    definition: "The number of shares (or coins) traded in a period.",
    inApp: "Below the candles on Charts, and the basis of relative volume and the volume profile.",
    example: "5 million Apple shares traded in the first hour: that hour's volume is 5 million.",
    related: ["relative-volume", "volume-profile", "vwap"],
  },
  {
    id: "volume-profile", term: "Volume profile", aka: ["point of control", "value area"],
    definition: "A sideways bar chart of how many shares traded at each price level.",
    inApp: "The Forecast card shows the last 120 days: the busiest price (point of control) and where 70% of trading happened (value area).",
    example: "If most shares changed hands around 150, a drop back to 150 often meets buyers.",
    related: ["volume", "vwap"],
  },
  {
    id: "vwap", term: "VWAP", aka: ["volume-weighted average price"],
    definition: "The average price paid during the day, where bigger trades count more.",
    inApp: "The yellow line on intraday charts (Charts, hourly or shorter).",
    example: "100 shares at 10 and 300 at 11: VWAP = (1,000 + 3,300) ÷ 400 = 10.75. A price above VWAP means the average buyer today is in profit.",
    related: ["volume", "volume-profile"],
  },
  {
    id: "win-rate", term: "Win rate",
    definition: "The share of trades that made money.",
    inApp: "Backtest stats and the Invest-now part of the live track record.",
    example: "12 winners out of 30 trades is a 40% win rate, which still profits if winners are twice the size of losers.",
    related: ["expectancy", "reward-risk"],
  },
] as const satisfies readonly GlossaryEntry[];

/** Every valid glossary id (type-checked links from hints). */
export type TermId = (typeof GLOSSARY)[number]["id"];

const BY_ID = new Map<string, GlossaryEntry>(GLOSSARY.map((e) => [e.id, e]));

/** Look up an entry by id (undefined if unknown). */
export const glossaryEntry = (id: string) => BY_ID.get(id);

/** Path of the glossary entry on the Learn page. */
export const learnPath = (id: string) => `/learn?term=${encodeURIComponent(id)}`;

/** First letter used for the A–Z index (digits and symbols go under "#"). */
export const letterOf = (e: GlossaryEntry) => {
  const c = e.term[0].toUpperCase();
  return c >= "A" && c <= "Z" ? c : "#";
};

/** Case- and accent-insensitive match on the term, its other names and its definition. */
export function matchesQuery(e: GlossaryEntry, q: string): boolean {
  const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const needle = norm(q.trim());
  if (!needle) return true;
  return [e.term, ...(e.aka ?? []), e.definition].some((s) => norm(s).includes(needle));
}
