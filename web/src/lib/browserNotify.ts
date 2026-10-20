import type { LiveEvent } from "./types";

const KEY = "mri.browserNotifications";

export const browserNotifySupported = () => typeof window !== "undefined" && "Notification" in window;

export function browserNotifyEnabled(): boolean {
  try { return browserNotifySupported() && Notification.permission === "granted" && localStorage.getItem(KEY) !== "off"; } catch { return false; }
}

export async function setBrowserNotify(on: boolean): Promise<boolean> {
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* storage unavailable */ }
  if (!on || !browserNotifySupported()) return false;
  const perm = Notification.permission === "default" ? await Notification.requestPermission() : Notification.permission;
  return perm === "granted";
}

export function notifyEvent(e: LiveEvent) {
  if (!browserNotifyEnabled()) return;
  if (e.type === "opportunity") {
    try {
      new Notification(`Invest now: ${e.symbol} ${(e.change_pct ?? 0) > 0 ? "+" : ""}${e.change_pct?.toFixed(1)}%`, { body: e.headline ?? "", tag: `mri-${e.id}` });
    } catch { /* ignore */ }
    return;
  }
  if (e.type === "picks") {
    try { new Notification("Beat the S&P: picks updated", { body: `Buy ${e.buy?.join(", ") || "nothing new"} · Sell ${e.sell?.join(", ") || "nothing"}`, tag: `mri-${e.id}` }); } catch { /* ignore */ }
    return;
  }
  if (e.type === "earnings") {
    try { new Notification(`Earnings ${e.phase === "today" ? "today" : "tomorrow"}: ${e.symbol}`, { body: earningsText(e), tag: `mri-${e.id}` }); } catch { /* ignore */ }
    return;
  }
  if (e.type === "alert") {
    try { new Notification(`Price alert: ${e.symbol} ${e.price?.toFixed(2) ?? ""}`, { body: e.note || alertText(e), tag: `mri-${e.id}` }); } catch { /* ignore */ }
    return;
  }
  const title = e.type === "move"
    ? `${e.direction === "SURGE" ? "▲" : "▼"} ${e.symbol} ${e.move_pct && e.move_pct > 0 ? "+" : ""}${e.move_pct?.toFixed(2)}%`
    : `${e.side === "long" ? "LONG" : "SHORT"} setup: ${e.symbol}`;
  const body = e.type === "move"
    ? `${e.direction === "SURGE" ? "Sudden surge" : "Sudden drop"} on ${e.volume_ratio ? `${e.volume_ratio.toFixed(1)}x volume` : "high volume"}`
    : `${e.strategy} · price ${e.price} · stop ${e.stop}`;
  try { new Notification(title, { body, tag: `mri-${e.id}` }); } catch { /* ignore */ }
}

export function alertText(e: { kind?: string; value?: number; change_pct?: number }): string {
  if (e.kind === "move") return `Moved ${(e.change_pct ?? 0) > 0 ? "+" : ""}${e.change_pct?.toFixed(1)}% today (your alert: ${e.value}%)`;
  return `Price went ${e.kind === "above" ? "above" : "below"} ${e.value}`;
}

export function earningsText(e: { timing?: string; timing_text?: string; avg_move_pct?: number | null; reasons?: string[] }): string {
  const when = e.timing && e.timing !== "unknown" ? `Reports ${e.timing_text}. ` : "";
  const move = e.avg_move_pct != null ? `Typical move after its results: ±${e.avg_move_pct.toFixed(1)}%. ` : "Prices often jump or drop after results. ";
  const why = e.reasons?.length ? `(${e.reasons.join(", ")})` : "";
  return `${when}${move}${why}`.trim();
}
