import { STATIC, snapshotRequest } from "./snapshot";
import type { BacktestResult, ChartData, LiveEvent, LiveStatus, PaperState, PicksResult, PredictResult, Quote, StrategyInfo, Universe } from "./types";

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
