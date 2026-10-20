import { STATIC, snapshotRequest } from "./snapshot";
import type { AIAnalysis, BacktestResult, ChartData, LiveEvent, LiveStatus, PaperState, OpportunitiesResult, OrderPlan, PaperAccount, PicksResult, PredictResult, Quote, StrategyInfo, TodayBoard, Universe } from "./types";

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
  aiStatus: () => request<{ enabled: boolean; how_to_enable: string | null }>("/api/ai/status"),
  aiAnalyze: (symbol: string) => request<AIAnalysis>(`/api/ai/analyze?${qs({ symbol })}`, { method: "POST" }),
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
};

export function eventsSocketUrl(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = getToken();
  return `${proto}://${location.host}/ws/events${token ? `?token=${encodeURIComponent(token)}` : ""}`;
}
