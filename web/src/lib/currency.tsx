import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { ccySign, fmtMoney, fmtTime, listingCurrency, type Ccy } from "./format";
import { Hint } from "../components/Hint";

/**
 * Display currency for the whole app (Settings › Display currency), remembered in this browser.
 * "EUR" / "USD": money amounts (plans, order costs, P&L, account values) are shown in that currency, converted at
 * the live rate; stock prices stay in their listing currency with the converted value as a second line.
 * "listed": nothing is converted.
 */
export type DisplayPref = "EUR" | "USD" | "listed";

export const DISPLAY_OPTIONS: { id: DisplayPref; label: string; hint: string }[] = [
  { id: "EUR", label: "Euro €", hint: "Amounts in euros. A US stock still shows its dollar price, with the euro value next to it." },
  { id: "USD", label: "Dollar $", hint: "Amounts in dollars. A Paris stock still shows its euro price, with the dollar value next to it." },
  { id: "listed", label: "As listed", hint: "No conversion: every number in the currency it trades or is reported in." },
];

const KEY = "mri.currency";
// Yahoo FX symbols, each worth "units of that currency per 1 euro".
const FX_SYMBOLS: Record<Exclude<Ccy, "EUR">, string> = { USD: "EURUSD=X", CHF: "EURCHF=X", GBP: "EURGBP=X" };
const REFRESH_MS = 5 * 60_000;

function readPref(): DisplayPref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "USD" || v === "listed" || v === "EUR" ? v : "EUR";
  } catch { return "EUR"; }
}

interface CurrencyCtx {
  pref: DisplayPref;
  setPref: (p: DisplayPref) => void;
  /** Units of each currency per 1 euro (EUR is 1). Missing while loading or if the rate is unavailable. */
  perEur: Partial<Record<Ccy, number>>;
  /** When the rates were last fetched (ms), null before the first answer. */
  updated: number | null;
}

const Ctx = createContext<CurrencyCtx | null>(null);

/** Holds the display preference and polls the live exchange rates (every 5 minutes). */
export function CurrencyProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<DisplayPref>(readPref);
  const [perEur, setPerEur] = useState<Partial<Record<Ccy, number>>>({ EUR: 1 });
  const [updated, setUpdated] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.quotes(Object.values(FX_SYMBOLS)).then((qs) => {
      if (!alive) return;
      const next: Partial<Record<Ccy, number>> = { EUR: 1 };
      for (const [ccy, sym] of Object.entries(FX_SYMBOLS) as [Ccy, string][]) {
        const p = qs.find((q) => q.symbol === sym)?.price;
        if (p && p > 0) next[ccy] = p;
      }
      // Keep the last good rate if one symbol fails this time.
      setPerEur((prev) => ({ ...prev, ...next }));
      setUpdated(Date.now());
    }).catch(() => undefined);
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const setPref = useCallback((p: DisplayPref) => {
    try { localStorage.setItem(KEY, p); } catch { /* storage unavailable: the choice lasts for this visit */ }
    setPrefState(p);
  }, []);

  const value = useMemo(() => ({ pref, setPref, perEur, updated }), [pref, setPref, perEur, updated]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** The display currency plus converters. Every helper falls back to the original currency when a rate is missing. */
export function useCurrency() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useCurrency must be used inside CurrencyProvider");
  const { pref, perEur } = c;

  /** Currency the app shows money in; `from` itself in "as listed" mode. */
  const target = (from: Ccy | null): Ccy | null => (pref === "listed" || !from ? from : pref);
  const convert = (v: number | null | undefined, from: Ccy | null, to: Ccy | null): number | null => {
    if (v === null || v === undefined || Number.isNaN(v) || !from || !to) return null;
    if (from === to) return v;
    const a = perEur[from], b = perEur[to];
    return a && b ? (v / a) * b : null;
  };
  /** Would an amount in `from` be converted (and can it be)? */
  const converts = (from: Ccy | null) => {
    const to = target(from);
    return !!from && !!to && to !== from && convert(1, from, to) !== null;
  };
  /** "1 € = $1.16" for the rates that a `from` -> display conversion uses. */
  const rateText = (from: Ccy | null, digits = 2) => {
    const to = target(from);
    const used = [from, to].filter((x): x is Ccy => !!x && x !== "EUR" && !!perEur[x]);
    const uniq = Array.from(new Set(used));
    return uniq.length ? `1 € = ${uniq.map((x) => fmtMoney(perEur[x], x, digits)).join(" = ")}` : "";
  };
  const fxNote = (from: Ccy | null) => `Converted at today's rate ${rateText(from)}; your broker's rate and fees may differ.`;
  /** An amount shown in the display currency, as text. */
  const money = (v: number | null | undefined, from: Ccy | null, digits = 0) => {
    const to = target(from);
    const conv = convert(v, from, to);
    return conv === null ? fmtMoney(v, from, digits) : fmtMoney(conv, to, digits);
  };
  return { ...c, target, convert, converts, rateText, fxNote, money };
}

/**
 * A money amount (plan amount, cost, P&L, account value) in the display currency.
 * When converted, hovering shows the original amount and the rate used.
 */
export function Money({ v, from, digits = 0, className }: { v: number | null | undefined; from: Ccy | null; digits?: number; className?: string }) {
  const cur = useCurrency();
  const conv = cur.converts(from);
  return (
    <span className={className} title={conv && v != null ? `${fmtMoney(v, from, digits)}. ${cur.fxNote(from)}` : undefined}>
      {cur.money(v, from, digits)}
    </span>
  );
}

/**
 * A price in its listing currency ("$531.13" for AAPL, "€612.40" for MC.PA, points for indices), with the value
 * in the display currency after it ("$531.13 · ≈ €457") when that differs. `alt`: "inline" (default), "stack" (the
 * converted value on its own line) or "hover" (only in the tooltip, for dense tables and grids).
 */
export function Price({ v, symbol, ccy, alt = "inline", digits, className = "" }: {
  v: number | null | undefined; symbol?: string; ccy?: Ccy | null; alt?: "inline" | "stack" | "hover"; digits?: number; className?: string;
}) {
  const cur = useCurrency();
  const from = ccy !== undefined ? ccy : listingCurrency(symbol ?? "");
  const to = cur.target(from);
  const conv = cur.converts(from) && v != null ? cur.convert(v, from, to) : null;
  const main = fmtMoney(v, from, digits);
  if (conv === null) return <span className={className || undefined}>{main}</span>;
  const altText = `≈ ${fmtMoney(conv, to, Math.abs(conv) >= 100 ? 0 : 2)}`;
  return (
    <span className={`${className} ${alt === "stack" ? "fx-stack" : ""}`.trim() || undefined} title={`${main} ${altText}. ${cur.fxNote(from)}`}>
      {main}{alt !== "hover" && <span className="fx-alt">{alt === "stack" ? "" : " · "}{altText}</span>}
    </span>
  );
}

/** Small "≈ € at 1 € = $1.16 (?)" note for a card or section whose prices get a converted second line. */
export function FxRate({ from = "USD" }: { from?: Ccy }) {
  const cur = useCurrency();
  const to = cur.target(from);
  if (!to || !cur.converts(from)) return null;
  return <span className="muted small fx-rate">≈ {ccySign(to)} at {cur.rateText(from)}<FxHint from={from} /></span>;
}

/** The "?" next to a section with converted numbers: which rate, and that the broker's will differ. */
export function FxHint({ from = "USD" }: { from?: Ccy | null }) {
  const cur = useCurrency();
  const to = cur.target(from);
  if (!from || !to || to === from) return null;
  return (
    <Hint label="About the currency conversion" term="exchange-rate">
      {cur.converts(from) ? <>{cur.fxNote(from)}{cur.updated ? ` Rate updated ${fmtTime(cur.updated / 1000)}.` : ""}</>
        : "The live exchange rate is not available right now, so these amounts are shown in their original currency."}
    </Hint>
  );
}
