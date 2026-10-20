import { STATIC, snapshotRequest } from "./snapshot";
import type { AIAnalysis, AlertsResult, PriceAlert, Watchlist, BacktestResult, ChartData, LiveEvent, LiveStatus, PaperState, OpportunitiesResult, OrderPlan, PaperAccount, BrokerStatus, OrderPreviewResult, BrokerPositions, ForecastResult, PicksResult, PortfolioPlan, PredictionsResult, PredictResult, StockInfo, Quote, StrategyInfo, TodayBoard, Universe } from "./types";

const TOKEN_KEY = "mri.token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string | null) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (STATIC) {
    try { return (await snapshotRequest(path, init)) as T; } catch (e) { throw new ApiError(400, (e as Error).message); }
  }
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail
        : Array.isArray(body.detail) ? body.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ")
        : detail;
    } catch { /* not json */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const qs = (o: Record<string, string | number | undefined>) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString();

export const api = {
  universe: () => request<Universe>("/api/universe"),
  opportunities: () => request<OpportunitiesResult>("/api/opportunities"),
  scanOpportunities: () => request<OpportunitiesResult>("/api/opportunities/scan", { method: "POST" }),
  paperOrder: (body: object) => request<{ mode: string; plan: OrderPlan; placed?: boolean }>("/api/paper/orders", { method: "POST", body: JSON.stringify(body) }),
  paperCloseAll: () => request<{ closed: unknown[] }>("/api/paper/close-all", { method: "POST" }),
  paperAccount: () => request<PaperAccount>("/api/paper"),
  brokerStatus: () => request<BrokerStatus>("/api/broker/status"),
  brokerPositions: () => request<BrokerPositions>("/api/broker/positions"),
  orderPreview: (body: { symbol: string; side: string }) => request<OrderPreviewResult>("/api/orders/preview", { method: "POST", body: JSON.stringify(body) }),
  orderPlace: (body: { symbol: string; side: string; confirm_token: string }) => request<{ broker: string; mode: string; plan: OrderPlan; placed: boolean; order: { id: string; status: string; qty: number } }>("/api/orders", { method: "POST", body: JSON.stringify(body) }),
  ordersCloseAll: () => request<{ broker: string; mode: string; cancelled: number; closed: unknown[]; errors: string[]; halted: boolean }>("/api/orders/close-all", { method: "POST" }),
  ordersResume: () => request<{ halted: null }>("/api/orders/resume", { method: "POST" }),
  aiStatus: () => request<{ enabled: boolean; how_to_enable: string | null }>("/api/ai/status"),
  aiAnalyze: (symbol: string) => request<AIAnalysis>(`/api/ai/analyze?${qs({ symbol })}`, { method: "POST" }),
  portfolio: (body: object) => request<PortfolioPlan>("/api/portfolio", { method: "POST", body: JSON.stringify(body) }),
  predictions: (horizon: number) => request<PredictionsResult>(`/api/predictions?${qs({ horizon })}`),
  predictionsCustom: (body: object) => request<PredictionsResult>("/api/predictions/custom", { method: "POST", body: JSON.stringify(body) }),
  forecast: (symbol: string, horizon: number) => request<ForecastResult>(`/api/forecast?${qs({ symbol, horizon })}`),
  stock: (symbol: string) => request<StockInfo>(`/api/stock?${qs({ symbol })}`),
  today: () => request<TodayBoard>("/api/today"),
  picksLatest: (preset: string) => request<PicksResult>(`/api/picks/latest?${qs({ preset })}`),
  picks: (body: object) => request<PicksResult>("/api/picks", { method: "POST", body: JSON.stringify(body) }),
  quotes: (symbols: string[]) => request<Quote[]>(`/api/quotes?${qs({ symbols: symbols.join(",") })}`),
  strategies: () => request<StrategyInfo[]>("/api/strategies"),
  chart: (p: { provider: string; exchange?: string; symbol: string; timeframe: string; limit?: number }) =>
    request<ChartData>(`/api/chart?${qs(p)}`),
  backtest: (body: object) => request<BacktestResult>("/api/backtest", { method: "POST", body: JSON.stringify(body) }),
  predict: (body: object) => request<PredictResult>("/api/predict", { method: "POST", body: JSON.stringify(body) }),
  liveStatus: () => request<LiveStatus>("/api/live/status"),
  liveStart: () => request<LiveStatus>("/api/live/start", { method: "POST" }),
  liveStop: () => request<LiveStatus>("/api/live/stop", { method: "POST" }),
  liveScan: () => request<{ events: LiveEvent[]; status: LiveStatus }>("/api/live/scan", { method: "POST" }),
  events: (type?: string, limit = 200) => request<LiveEvent[]>(`/api/events?${qs({ type, limit })}`),
  paper: () => request<PaperState>("/api/paper"),
  watchlists: () => request<Watchlist[]>("/api/watchlists"),
  saveWatchlist: (w: { id?: number; name: string; symbols: string[] }) =>
    request<Watchlist>(w.id ? `/api/watchlists/${w.id}` : "/api/watchlists", { method: w.id ? "PUT" : "POST", body: JSON.stringify({ name: w.name, symbols: w.symbols }) }),
  deleteWatchlist: (id: number) => request<{ ok: boolean }>(`/api/watchlists/${id}`, { method: "DELETE" }),
  alerts: () => request<AlertsResult>("/api/alerts"),
  addAlert: (a: { symbol: string; kind: string; value: number; note?: string }) => request<PriceAlert>("/api/alerts", { method: "POST", body: JSON.stringify(a) }),
  rearmAlert: (id: number) => request<{ ok: boolean }>(`/api/alerts/${id}/rearm`, { method: "POST" }),
  deleteAlert: (id: number) => request<{ ok: boolean }>(`/api/alerts/${id}`, { method: "DELETE" }),
};

export function eventsSocketUrl(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = getToken();
  return `${proto}://${location.host}/ws/events${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}
