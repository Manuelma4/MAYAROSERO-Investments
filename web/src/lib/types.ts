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
  vwap?: Point[];
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
  id: number; created_at: string; type: "signal" | "move" | "opportunity" | "alert" | "picks" | "earnings"; symbol: string; time: string;
  // earnings (a pick, watchlist or held stock reports tomorrow); date = report day
  phase?: "tomorrow" | "today"; timing?: EarningsTiming; timing_text?: string; avg_move_pct?: number | null; reasons?: string[]; text?: string; eps_estimate?: number | null;
  // alert (one of the user's own price alerts fired)
  kind?: AlertKind; value?: number; note?: string;
  // picks (the Beat-the-S&P list changed at a review)
  date?: string; buy?: string[]; sell?: string[]; keep?: string[];
  // opportunity
  name?: string; change_pct?: number; headline?: string | null; entry?: number; rel_volume?: number;
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
export interface MoverLite { symbol: string; name?: string; price: number; change_pct: number }
export interface Changes { date: string | null; buy: string[]; sell: string[]; keep: string[]; provisional_skipped?: boolean }
export interface TodayBoard {
  as_of: string; mood: Mood | null;
  core: null | { preset: string; risk_off: boolean; picks: PickRow[]; changes: Changes; as_of: string;
    edge: { "cagr_%": number; "benchmark_cagr_%": number; "skill_vs_universe_%": number; start: string }; settings?: string };
  gainers: MoverLite[]; losers: MoverLite[];
}

export interface Opportunity {
  symbol: string; name: string; direction: "long" | "short"; as_of: string; price: number; change_pct: number;
  sigma: number; rel_volume: number; trend: string; pct_from_extreme: number; entry: number; stop: number;
  target: number; risk_pct: number; hold_days: number; expires_at: string; score: number;
  catalyst: string | null; headline: string | null; headline_url: string | null; headline_publisher: string | null;
  qualified: boolean; reasons: string[];
}
export interface MoverRow { symbol: string; name: string; price: number; change_pct: number; rel_volume: number | null }
export interface MoversBoard { gainers: MoverRow[]; losers: MoverRow[]; count: number; "breadth_up_%": number | null }
export interface OpportunitiesResult { as_of: string; us_market_open: boolean; items: Opportunity[]; movers?: MoversBoard | null }
export interface OrderPlan { symbol: string; side: string; entry: number; stop: number; target: number | null; qty: number; value: number; max_loss: number; risk_pct_of_equity: number }
export interface PaperPosition { symbol: string; strategy: string; side: string; entry_time: string; entry: number; qty: number; stop: number; target: number | null; price?: number | null; pnl?: number | null }
export interface RiskLimitsInfo { risk_per_trade_pct: number; max_position_pct: number; max_open_positions: number; max_short_exposure_pct: number; max_daily_loss_pct: number; max_order_value: number | null; max_daily_loss_value: number | null }
export interface BrokerStatus {
  broker: string; mode: "paper" | "live"; connected: boolean; error: string | null; halted: { day: string; at: string; reason: string; persistent?: boolean } | null;
  limits: RiskLimitsInfo; confirm_seconds: number; equity?: number; buying_power?: number; cash?: number; currency?: string; blocked?: boolean; live_block?: string | null;
}
export interface OrderPreviewResult {
  broker: string; mode: "paper" | "live"; plan: OrderPlan; confirm_token: string; expires_in: number; currency: string; equity: number; buying_power: number | null;
  eur: { usd_per_eur: number; value: number; max_loss: number } | null; order_type: string; hold_days: number | null; expires_at: string | null; can_place: boolean; block_reason: string | null;
}
export interface BrokerPosition { symbol: string; side: string; qty: number; entry: number; price: number | null; pnl: number | null }
export interface BrokerPositions { broker: string; mode: "paper" | "live"; positions: BrokerPosition[]; orders: { id: string; symbol: string; side: string; qty: number; stop: number; target: number | null; opened_at: string; close_by: string; status: string; reason?: string }[] }
export interface PaperAccount { enabled: boolean; cash: number; equity: number; open_pnl: number; positions: PaperPosition[]; history: { symbol: string; strategy: string; side: string; entry: number; exit: number; exit_time: string; reason: string; pnl: number }[] }

export interface AIAnalysis {
  symbol: string; as_of: string; model: string; technical: string; news: string; fundamentals: string;
  bull_case: string; bear_case: string; verdict: "favorable" | "neutral" | "avoid"; confidence: number;
  summary: string; main_risk: string; invalidation: string;
}

export interface PlanLine { symbol: string; name: string; role: "core" | "satellite" | "anchor" | "cash"; sector: string | null; weight: number; amount: number; price: number | null; shares: number; invested: number; stop: number | null; note: string }
export interface PortfolioPlan {
  currency: "EUR" | "USD"; fx_usd_per_unit: number; risk: string; amount: number; lines: PlanLine[]; cash: number;
  by_role: Record<string, number>; by_sector: Record<string, number>;
  risk_metrics: Partial<Record<"volatility_%" | "spy_volatility_%" | "beta" | "return_1y_%" | "spy_return_1y_%" | "max_drawdown_1y_%" | "spy_max_drawdown_1y_%", number>>;
  track_record: PlanTrack;
  changes: Changes | null; core_risk_off: boolean; as_of: string; mix: Record<string, number>;
  standard_mix?: Record<string, number>;
  weighting?: PlanWeighting;
  risk_view?: PortfolioRiskView;
}
export interface PlanTrack {
  start: string; method?: "plan" | "approx"; "cagr_%": number; "spy_cagr_%": number; "max_drawdown_%": number; "spy_max_drawdown_%": number;
  "volatility_%"?: number; "spy_volatility_%"?: number; "month_1in20_%"?: number; "spy_month_1in20_%"?: number;
  sharpe?: number; spy_sharpe?: number; "months_beating_spy_%"?: number; "turnover_per_year_%"?: number;
}
export interface PlanWeighting {
  method: "equal_risk" | "inverse_volatility"; target_x: number; budget_applied: boolean; summary: string[];
  x_spy?: number; x_spy_start?: number; to_cash?: number; moved_to_index?: number;
}

export interface MonthLoss { "loss_95_%": number; loss_95: number; "loss_99_%": number; loss_99: number; "avg_worst_5_%": number | null; p_loss_10: number; p_gain: number; "median_%": number }
export interface WorstDrop { "drop_%": number; peak: string; trough: string; recovered: string | null; fall_days: number; recovery_days: number | null; underwater_days: number }
export interface RiskContributor { symbol: string; "weight_%": number; "risk_share_%": number }
export interface SectorRisk { sector: string; "weight_%": number; "risk_share_%": number }
export interface PortfolioRiskView {
  status: "ok" | "empty" | "short" | "error" | "no_target"; message?: string;
  currency?: "EUR" | "USD"; amount?: number; as_of?: string; start?: string; days?: number; horizon_days?: number; paths?: number;
  invested_share?: number; ideas_share?: number; ideas_stop_loss?: number | null; cash_share?: number;
  month?: { plan: MonthLoss; spy: MonthLoss };
  histogram?: { "edges_%": number[]; plan: number[]; spy: number[] };
  worst_drop?: { plan: WorstDrop; spy: WorstDrop };
  "volatility_%"?: number; "spy_volatility_%"?: number; "volatility_now_%"?: number; "spy_volatility_now_%"?: number; beta?: number | null;
  diversification?: { holdings: number; avg_correlation: number | null; equal_size_count: number; independent_bets: number | null;
    contributors: RiskContributor[]; top_contributor: RiskContributor | null; sectors: SectorRisk[]; top_sector: SectorRisk | null };
  summary?: string[]; method?: string; notes?: string[]; currency_risk?: boolean;
  target?: { saved_at: string; risk: string };
}

export interface PortfolioTarget {
  saved_at: string; amount: number; currency: "EUR" | "USD"; risk: string; weights: Record<string, number>;
  names: Record<string, string>; ideas_share: number; bucket_share: number;
}
export interface DriftRow { symbol: string | null; name: string; in_plan: boolean; "current_%": number; "target_%": number; drift: number; amount: number }
export interface DriftTrade { symbol: string; name: string; amount: number }
export interface PortfolioDrift {
  status: "no_target" | "empty" | "not_invested" | "on_target" | "drifted"; message: string; target: PortfolioTarget | null;
  source?: string; currency?: string; account_value?: number | null; rows?: DriftRow[]; buy?: DriftTrade[]; sell?: DriftTrade[];
  max_drift?: number; total_drift?: number; breached?: boolean; suggestion?: string; position_limit?: number; total_limit?: number; as_of?: string;
}
export interface DigestPreview {
  text: string; chars: number; last_sent: string | null; channels: string[];
  schedule: { day: string; hour: number; minute: number; timezone: string; enabled: boolean; text: string; next: string | null };
}

export interface RankedItem { symbol: string; name: string; sector: string | null; score: number; decile: number; p_outperform: number; p_underperform: number; price: number; "change_1d_%": number; reason: string }
export interface PredictionsResult {
  horizon: number; horizon_label: string; as_of: string; quality_sentence: string; edge_sentence: string; universe_size: number;
  validation: { ic_mean: number; ic_t_stat: number; ic_positive_share: number; "top_minus_bottom_per_period_%": number; has_edge: boolean; dates_tested: number };
  items: RankedItem[];
}
export interface ForecastResult {
  symbol: string;
  monte_carlo: { horizon: number; last_price: number; p_up: number; p_down: number; range_5_95: [number, number]; median: number; "annual_vol_%": number;
    "p_move_up_5%": number; "p_move_down_5%": number; fan: Record<"p5" | "p25" | "p50" | "p75" | "p95", number[]>; fan_times: number[] };
  volume_profile: { bins: { price: number; volume: number; share: number }[]; poc: number | null; value_area: [number | null, number | null] };
  ranking: (RankedItem & { horizon: number }) | null;
}

export interface StockInfo {
  symbol: string; name: string; sector: string | null; industry: string | null; region: string | null; themes: string[];
  quote: Quote; fundamentals: Record<string, number | string>;
  verdict: { status: "pick" | "ranked" | "excluded" | "not_covered" | "unknown"; rank?: number; text: string };
  ranking: RankedItem | null; idea: Opportunity | null; similar: { symbol: string; name: string; industry: string }[];
}

export interface Watchlist { id: number; name: string; symbols: string[] }
export type AlertKind = "above" | "below" | "move";
export interface PriceAlert {
  id: number; created_at: string; symbol: string; kind: AlertKind; value: number; note: string;
  active: boolean; triggered_at: string | null; triggered_price: number | null;
}
export interface AlertsResult { kinds: Record<AlertKind, string>; alerts: PriceAlert[] }

export interface TrackIdea {
  symbol: string; direction: "long" | "short"; entry: number; stop: number; target: number | null; as_of: string; valid_until: string | null;
  status: "pending" | "open" | "closed" | "invalid"; fill: number | null; fill_date: string | null; exit: number | null; exit_date: string | null;
  reason: "stop" | "target" | "time limit" | null; r: number | null; days_held: number; mark?: number;
}
export interface TrackRecord {
  preset: string; as_of: string; started: string | null; days: number; too_early: boolean; message: string;
  picks: {
    days: number; first_trade?: string | null; "return_%"?: number | null; "spy_%"?: number | null; "excess_%"?: number | null; "universe_%"?: number | null;
    "max_drawdown_%"?: number | null; "spy_max_drawdown_%"?: number | null; "turnover_%"?: number; rebalances?: number; "days_beating_spy_%"?: number | null;
    curve: { date: string; time: number; picks: number; spy: number }[]; holdings?: Record<string, number>;
    snapshots: number; latest_date: string | null; current: { symbol: string; weight: number; price: number | null }[]; risk_off: boolean;
  };
  ideas: { count: number; closed_count: number; open_count: number; pending_count: number; win_rate: number | null; avg_r: number | null; "total_r_%": number | null; open: TrackIdea[]; closed: TrackIdea[] };
}

export type EarningsTiming = "before_open" | "after_close" | "during" | "unknown";
export interface EarningsEvent { date: string; time: string | null; timing: EarningsTiming; timing_text?: string; eps_estimate: number | null; eps_actual?: number | null; surprise_pct?: number | null }
export interface EarningsRecord {
  symbol: string; status: "ok" | "unknown" | "none"; next: EarningsEvent | null; last: EarningsEvent | null; history?: EarningsEvent[];
  avg_move?: { "avg_abs_move_%": number; moves: { date: string; "move_%": number }[] } | null; fetched_at?: string; reason?: string;
}
export interface EarningsResult { items: EarningsRecord[]; hint: string }
export interface UpcomingEarning {
  symbol: string; name: string; date: string; time: string | null; timing: EarningsTiming; timing_text: string; days_until: number;
  eps_estimate: number | null; "avg_move_%": number | null; reports_measured: number; pick: boolean; watchlist: boolean; held: boolean;
}
export interface UpcomingEarnings { as_of: string; days: number; today: string; items: UpcomingEarning[]; last_refresh: string | null; hint: string }

export type SizeBand = "small" | "mid" | "large" | "mega";
export type ValuationBand = "cheap" | "fair" | "expensive" | "no_profit";
export interface ScreenerRow {
  symbol: string; name: string; sector: string; industry: string; region: string; currency: string | null;
  market_cap: number | null; size: SizeBand | null; pe: number | null; forward_pe: number | null; valuation: ValuationBand | null;
  dividend_yield: number | null; beta: number | null; price: number | null; change_pct: number | null;
  ret_1m: number | null; ret_6m: number | null; ret_12m: number | null; above_200d: boolean | null; vs_200d_pct: number | null;
  from_high_pct: number | null; volatility: number | null; momentum_pct: number | null; has_fundamentals: boolean; has_technicals: boolean;
}
export interface ScreenerBand { id: string; min: number; max: number | null }
export interface ScreenerCoverage {
  total: number; with_fundamentals: number; fresh: number; last_update: string | null; refreshing: boolean;
  progress: { done: number; todo: number } | null; with_technicals: number; technicals_as_of: string | null; technicals_ready: boolean;
}
export interface ScreenerResult {
  as_of: string; total: number; count: number; rows: ScreenerRow[]; coverage: ScreenerCoverage; sectors: string[];
  bands: { size: ScreenerBand[]; valuation: ScreenerBand[]; strong_momentum_pct: number };
  filters: Record<string, unknown>; sort: string; order: "asc" | "desc";
}
