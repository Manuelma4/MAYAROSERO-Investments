export const fmtPrice = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6;
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

export const fmtPct = (v: number | null | undefined, digits = 1, sign = true) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (Number(v.toFixed(digits)) === 0) return `${(0).toFixed(digits)}%`; // never "-0.00%"
  return `${sign && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
};

export const fmtNum = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits });

export const fmtTime = (iso: string | number) => {
  const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const fmtDate = (sec: number) =>
  new Date(sec * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });

export const tone = (v: number | null | undefined) => (v === null || v === undefined || v === 0 ? "" : v > 0 ? "up" : "down");

export const fmtBig = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  return a >= 1e12 ? `${(v / 1e12).toFixed(2)}T` : a >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : fmtNum(v, 0);
};

export const stockPath = (symbol: string) => `/stock/${encodeURIComponent(symbol)}`;

/** "2026-09-30" (or an ISO timestamp) as "30 Sep 2026". */
export const fmtDay = (iso: string | null | undefined) => {
  if (!iso) return "–";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

/** Currencies the app can show money in. */
export type Ccy = "USD" | "EUR" | "CHF" | "GBP";

// Yahoo suffix -> trading currency. London (.L) is left out on purpose: Yahoo quotes it in pence.
const SUFFIX_CCY: Record<string, Ccy> = {
  PA: "EUR", MC: "EUR", DE: "EUR", F: "EUR", AS: "EUR", MI: "EUR", BR: "EUR", LS: "EUR", HE: "EUR", VI: "EUR", IR: "EUR",
  SW: "CHF",
};

/**
 * The currency a symbol's price is quoted in, or null when the price is not money:
 * index points (^GSPC), exchange rates (EURUSD=X) and listings whose currency is unknown.
 * "AAPL" -> USD, "MC.PA" -> EUR, "NESN.SW" -> CHF, "BTC/USDT" -> USD (a dollar stablecoin), "GC=F" -> USD.
 */
export function listingCurrency(symbol: string): Ccy | null {
  const s = symbol.trim().toUpperCase();
  if (!s || s.startsWith("^") || s.endsWith("=X")) return null;
  if (s.includes("/")) {
    const quote = s.slice(s.indexOf("/") + 1);
    return quote === "EUR" ? "EUR" : /^(USD|USDT|USDC|BUSD|FDUSD)$/.test(quote) ? "USD" : null;
  }
  if (s.endsWith("=F")) return "USD";
  const dot = s.lastIndexOf(".");
  if (dot < 0) return "USD";
  return SUFFIX_CCY[s.slice(dot + 1)] ?? null;
}

const CCY_SIGN: Record<Ccy, string> = { USD: "$", EUR: "€", CHF: "CHF ", GBP: "£" };
export const ccySign = (c: Ccy) => CCY_SIGN[c].trim();
export const isCcy = (c: string | null | undefined): c is Ccy => !!c && c in CCY_SIGN;
/** Account currencies as brokers report them ("USDT" at an exchange counts as dollars). */
export const asCcy = (c: string | null | undefined): Ccy | null => {
  const u = (c ?? "").toUpperCase();
  return /^(USDT|USDC|BUSD|FDUSD)$/.test(u) ? "USD" : isCcy(u) ? u : null;
};

/** "$531.13", "€10,000", "CHF 80.12", "−€300". Without `digits`: price-style precision. */
export function fmtMoney(v: number | null | undefined, ccy: Ccy | null, digits?: number): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  const body = digits === undefined ? fmtPrice(a)
    : a.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${v < 0 ? "−" : ""}${ccy ? CCY_SIGN[ccy] : ""}${body}`;
}

/** A price in its listing currency: "$531.13" for AAPL, "€612.40" for MC.PA, "6,712.35" for ^GSPC. */
export const fmtListed = (v: number | null | undefined, symbol: string) => fmtMoney(v, listingCurrency(symbol));
