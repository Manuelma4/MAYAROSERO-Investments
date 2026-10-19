/** Curated market universe shown across the app. */
export interface MarketDef { symbol: string; name: string; group: "Indices" | "Crypto" | "Commodities & FX" | "Stocks" }

export const MARKETS: MarketDef[] = [
  { symbol: "^GSPC", name: "S&P 500", group: "Indices" },
  { symbol: "^NDX", name: "Nasdaq 100", group: "Indices" },
  { symbol: "^DJI", name: "Dow Jones", group: "Indices" },
  { symbol: "^FCHI", name: "CAC 40", group: "Indices" },
  { symbol: "^GDAXI", name: "DAX", group: "Indices" },
  { symbol: "^STOXX50E", name: "Euro Stoxx 50", group: "Indices" },
  { symbol: "BTC/USDT", name: "Bitcoin", group: "Crypto" },
  { symbol: "ETH/USDT", name: "Ethereum", group: "Crypto" },
  { symbol: "SOL/USDT", name: "Solana", group: "Crypto" },
  { symbol: "GC=F", name: "Gold", group: "Commodities & FX" },
  { symbol: "CL=F", name: "Crude oil", group: "Commodities & FX" },
  { symbol: "EURUSD=X", name: "EUR / USD", group: "Commodities & FX" },
];

export const STOCKS: MarketDef[] = [
  { symbol: "AAPL", name: "Apple", group: "Stocks" },
  { symbol: "MSFT", name: "Microsoft", group: "Stocks" },
  { symbol: "NVDA", name: "NVIDIA", group: "Stocks" },
  { symbol: "AMZN", name: "Amazon", group: "Stocks" },
  { symbol: "TSLA", name: "Tesla", group: "Stocks" },
  { symbol: "META", name: "Meta", group: "Stocks" },
  { symbol: "MC.PA", name: "LVMH", group: "Stocks" },
  { symbol: "AIR.PA", name: "Airbus", group: "Stocks" },
];

const NAMES = Object.fromEntries([...MARKETS, ...STOCKS].map((m) => [m.symbol, m.name]));
export const marketName = (symbol: string) => NAMES[symbol] ?? symbol;
export const isCrypto = (symbol: string) => symbol.includes("/");
