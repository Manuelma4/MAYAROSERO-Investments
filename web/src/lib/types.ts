export type Provider = "yahoo" | "ccxt";

export interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number }
export interface Point { time: number; value: number }

export interface Analysis {
  time: string;
  close: number;
  atr: number;
  atr_pct: number;
  trend: -1 | 0 | 1;
  swings: { swing_high: number | null; swing_low: number | null };
  ema: Record<"20" | "50" | "200", number>;
  rsi: number;
  macd_hist: number;
  wyckoff_range: { support: number | null; resistance: number | null; tight: boolean };
  recent_patterns: { time: string; pattern: string }[];
  elliott: null | { direction: string; start: string; end: string; points: number[]; wave3_extension: number | null };
}

export interface ChartData {
  symbol: string;
  timeframe: string;
  candles: Candle[];
  overlays: Record<string, Point[]>;
  rsi: Point[];
  patterns: { time: number; kind: "bull" | "bear"; label: string }[];
  pivots: { time: number; kind: "H" | "L"; price: number }[];
  analysis: Analysis;
}

export interface StrategyInfo { name: string; description: string; defaults: Record<string, number> }

export interface Trade {
  side: "long" | "short"; entry_time: number; entry: number; exit_time: number; exit: number;
  qty: number; stop: number; target: number | null; reason: string; pnl: number; R: number; bars: number;
}

export interface BacktestResult {
  stats: Record<string, number | string>;
  equity: Point[];
  buy_hold: Point[];
  candles: Candle[];
  trades: Trade[];
}

export interface Validation {
  samples: number; accuracy: number; baseline_accuracy: number; confident_calls: number;
  confident_precision: number; "strategy_return_%": number; "buy_hold_return_%": number; has_edge: boolean;
}

export interface PredictionItem {
  symbol: string; time: string; action: "BUY" | "SELL" | "HOLD";
  probabilities: Record<string, number>; confidence: number; has_edge: boolean; last_close: number;
}

export interface PredictResult { validation: Validation; predictions: PredictionItem[] }

export interface LiveStatus {
  running: boolean; poll_seconds: number; scans: number; last_scan: string | null; last_error: string | null;
  watchlist: { provider: string; symbol: string; timeframe: string; strategies: string[] }[];
  movers_enabled: boolean; paper_trading: boolean; notifiers: string[];
}

export interface LiveEvent {
  id: number; created_at: string; type: "signal" | "move"; symbol: string; time: string;
  // signal
  side?: "long" | "short"; strategy?: string; timeframe?: string; price: number; stop?: number; target?: number | null;
  // move
  direction?: "SURGE" | "CRASH"; move_pct?: number; zscore?: number; volume_ratio?: number | null;
}

export interface PaperState {
  enabled: boolean; cash: number | null;
  positions: { symbol: string; strategy: string; side: string; entry_time: string; entry: number; qty: number; stop: number; target: number | null }[];
  history: { symbol: string; strategy: string; side: string; entry: number; exit: number; exit_time: string; reason: string; pnl: number }[];
}

export interface Quote {
  symbol: string; provider: string; price?: number; change?: number; change_pct?: number;
  time?: string; spark?: number[]; error?: string;
}

export interface UniverseStock { symbol: string; name: string; sector: string; industry: string; region: string; sp500: boolean; themes: string[] }
export interface Universe { sectors: string[]; themes: string[]; stocks: UniverseStock[]; crypto: UniverseStock[] }

export interface PickRow {
  symbol: string; name: string; sector: string | null; score: number; eligible: boolean; price: number;
  "return_1m_%": number; "momentum_12_1_%": number; "momentum_6_1_%": number; "rel_strength_%": number;
  "trend_%": number; "volatility_%": number; reason?: string;
}
export interface PicksResult {
  preset: string; preset_info: Record<string, string>; as_of: string; risk_off: boolean;
  picks: PickRow[]; ranking: PickRow[]; stats: Record<string, number | string>;
  equity: Point[]; benchmark: Point[]; universe: Point[];
  holdings: { date: string; symbols: string[]; turnover: number; risk_off: boolean }[];
  universe_size: number; missing: string[];
  changes?: Changes;
}

export interface Mood { label: "Risk-on" | "Neutral" | "Risk-off"; explanation: string; advice: string; "spy_vs_200d_%": number; "spy_1m_%": number; "breadth_%": number | null; vix: number | null }
export interface MoverLite { symbol: string; price: number; change_pct: number }
export interface Changes { date: string | null; buy: string[]; sell: string[]; keep: string[]; provisional_skipped?: boolean }
export interface TodayBoard {
  as_of: string; mood: Mood | null;
  core: null | { preset: string; risk_off: boolean; picks: PickRow[]; changes: Changes; as_of: string;
    edge: { "cagr_%": number; "benchmark_cagr_%": number; "skill_vs_universe_%": number; start: string } };
  gainers: MoverLite[]; losers: MoverLite[];
}
