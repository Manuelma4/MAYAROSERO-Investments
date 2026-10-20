import type { EarningsTiming } from "./types";

export const EARNINGS_HINT =
  "Earnings: the company publishes its quarterly results (sales, profit, outlook). Prices often jump or drop sharply right after, in either direction, so some investors wait until the results are out before buying.";

/** Short plain-English time of the report. */
export const TIMING_SHORT: Record<EarningsTiming, string> = {
  before_open: "before the market opens",
  after_close: "after the market closes",
  during: "during market hours",
  unknown: "time not announced yet",
};

/** "2026-11-17" as "Tue 17 Nov". */
export const fmtEarnDay = (iso: string) => {
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
};

/** Days from today (the viewer's calendar day) to a report date. */
export const daysUntil = (iso: string) => {
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const [y, m, d] = iso.split("-").map(Number);
  return Math.round((Date.UTC(y, m - 1, d) - today) / 86_400_000);
};

export const whenText = (days: number) =>
  days < 0 ? "already out" : days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
