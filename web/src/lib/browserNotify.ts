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
  const title = e.type === "move"
    ? `${e.direction === "SURGE" ? "▲" : "▼"} ${e.symbol} ${e.move_pct && e.move_pct > 0 ? "+" : ""}${e.move_pct?.toFixed(2)}%`
    : `${e.side === "long" ? "LONG" : "SHORT"} setup: ${e.symbol}`;
  const body = e.type === "move"
    ? `${e.direction === "SURGE" ? "Sudden surge" : "Sudden drop"} on ${e.volume_ratio ? `${e.volume_ratio.toFixed(1)}x volume` : "high volume"}`
    : `${e.strategy} · price ${e.price} · stop ${e.stop}`;
  try { new Notification(title, { body, tag: `mri-${e.id}` }); } catch { /* ignore */ }
}
