import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { fmtBig, fmtDay, fmtNum, fmtPct, fmtPrice, fmtTime, stockPath } from "../lib/format";
import type { TermId } from "../lib/glossary";
import type { ScreenerBand, ScreenerResult, ScreenerRow, SizeBand, ValuationBand } from "../lib/types";
import { Hint } from "./Hint";
import { Empty, ErrorBox, Spinner } from "./ui";

/**
 * Discover › Screener: the whole universe (~520 stocks) is loaded once (precomputed on the server: fundamentals
 * once a day, prices every few minutes) and filtered / sorted in the browser, so every tap answers instantly.
 * Filters live in the address bar: Back from a stock page returns to the same list.
 */

type SortKey = "name" | "market_cap" | "pe" | "forward_pe" | "dividend_yield" | "change_pct" | "ret_1m" | "ret_6m"
  | "ret_12m" | "vs_200d_pct" | "from_high_pct" | "volatility" | "beta";
type Div = "" | "pays" | "2" | "4";
type Trend = "" | "up" | "down";
type Mom = "" | "positive" | "strong";

interface Filters { sector: string; size: SizeBand[]; val: ValuationBand[]; div: Div; trend: Trend; mom: Mom; sort: SortKey; order: "asc" | "desc" }

const DEFAULT: Filters = { sector: "", size: [], val: [], div: "", trend: "", mom: "", sort: "market_cap", order: "desc" };
const SIZES: SizeBand[] = ["small", "mid", "large", "mega"];
const VALS: ValuationBand[] = ["cheap", "fair", "expensive", "no_profit"];
const PAGE = 60;

const PRESETS: { id: string; label: string; hint: string; f: Partial<Filters> }[] = [
  { id: "dividend-uptrend", label: "Dividend payers in an uptrend", f: { div: "2", trend: "up", sort: "dividend_yield", order: "desc" },
    hint: "Pays at least 2% a year in dividends and trades above its 200-day average: income from companies whose price is also rising." },
  { id: "cheap-large", label: "Cheap large caps", f: { size: ["large", "mega"], val: ["cheap"], sort: "pe", order: "asc" },
    hint: "Companies worth $50 billion or more with a P/E under 15. Cheap can mean a bargain, or a business the market expects to shrink: check why." },
  { id: "momentum", label: "Strongest momentum", f: { mom: "strong", trend: "up", sort: "ret_6m", order: "desc" },
    hint: "The 20% of stocks that rose most over 6 months, still in an uptrend. Momentum tends to persist for a while, then can reverse sharply." },
];

const SORT_LABEL: Record<SortKey, string> = {
  name: "Name", market_cap: "Size (market value)", pe: "P/E", forward_pe: "Next-year P/E", dividend_yield: "Dividend yield",
  change_pct: "Today", ret_1m: "1 month", ret_6m: "6 months", ret_12m: "12 months", vs_200d_pct: "Trend (vs 200-day)",
  from_high_pct: "Below 52-week high", volatility: "Swings (volatility)", beta: "Beta",
};
/** Natural first direction when a column is picked: biggest / highest first, except cheapness and calm. */
const FIRST_ASC: SortKey[] = ["name", "pe", "forward_pe", "volatility", "beta"];

function parse(p: URLSearchParams): Filters {
  const list = <T extends string>(k: string, ok: readonly T[]) => (p.get(k) ?? "").split(",").filter((x): x is T => (ok as readonly string[]).includes(x));
  const one = <T extends string>(k: string, ok: readonly T[], d: T) => ((ok as readonly string[]).includes(p.get(k) ?? "") ? p.get(k) as T : d);
  return {
    sector: p.get("sector") ?? "", size: list("size", SIZES), val: list("val", VALS),
    div: one<Div>("div", ["pays", "2", "4"], ""), trend: one<Trend>("trend", ["up", "down"], ""), mom: one<Mom>("mom", ["positive", "strong"], ""),
    sort: one<SortKey>("sort", Object.keys(SORT_LABEL) as SortKey[], "market_cap"), order: p.get("order") === "asc" ? "asc" : "desc",
  };
}

function matches(r: ScreenerRow, f: Filters, strong: number, q: string) {
  if (f.sector && r.sector !== f.sector) return false;
  if (f.size.length && !(r.size && f.size.includes(r.size))) return false;
  if (f.val.length && !(r.valuation && f.val.includes(r.valuation))) return false;
  const dy = r.dividend_yield;
  if (f.div === "pays" && !(dy !== null && dy > 0)) return false;
  if ((f.div === "2" || f.div === "4") && !(dy !== null && dy >= Number(f.div))) return false;
  if (f.trend === "up" && r.above_200d !== true) return false;
  if (f.trend === "down" && r.above_200d !== false) return false;
  if (f.mom === "positive" && !(r.ret_6m !== null && r.ret_6m > 0)) return false;
  if (f.mom === "strong" && !(r.momentum_pct !== null && r.momentum_pct > strong)) return false;
  if (q && ![r.symbol, r.name, r.industry].some((s) => s.toLowerCase().includes(q))) return false;
  return true;
}

function sortRows(rows: ScreenerRow[], key: SortKey, order: "asc" | "desc") {
  const have = rows.filter((r) => r[key] !== null && r[key] !== undefined);
  const missing = rows.filter((r) => r[key] === null || r[key] === undefined);
  const dir = order === "asc" ? 1 : -1;
  have.sort((a, b) => {
    const x = a[key], y = b[key];
    const c = typeof x === "string" ? x.localeCompare(String(y)) : (x as number) - (y as number);
    return c * dir || a.symbol.localeCompare(b.symbol);
  });
  return [...have, ...missing]; // stocks without the figure always last
}

const money = (v: number) => `$${fmtBig(v)}`;
function bandText(b: ScreenerBand | undefined, fmt: (v: number) => string, unit = "") {
  if (!b) return "";
  if (!b.min) return `under ${fmt(b.max ?? 0)}${unit}`;
  if (b.max === null) return `${fmt(b.min)}${unit}+`;
  return `${fmt(b.min)}–${fmt(b.max)}${unit}`;
}
const SIZE_NAME: Record<SizeBand, string> = { small: "Small", mid: "Mid", large: "Large", mega: "Mega" };
const VAL_NAME: Record<ValuationBand, string> = { cheap: "Cheap", fair: "Fair", expensive: "Expensive", no_profit: "Losing money" };

const tone = (v: number | null) => (v === null || v === 0 ? "" : v > 0 ? "up" : "down");
const Pct = ({ v, d = 1 }: { v: number | null; d?: number }) => (v === null ? <span className="muted">–</span> : <span className={tone(v)}>{fmtPct(v, d)}</span>);
const DivCell = ({ v }: { v: number | null }) => (v === null ? <span className="muted">–</span> : v === 0 ? <span className="muted">None</span> : <>{v.toFixed(1)}%</>);
const Pe = ({ v }: { v: number | null }) => (v === null ? <span className="muted">–</span> : <>{v >= 1000 ? fmtNum(v, 0) : v.toFixed(1)}</>);
const TrendCell = ({ r }: { r: ScreenerRow }) => (r.above_200d === null ? <span className="muted">–</span>
  : <span className={r.above_200d ? "up" : "down"}>{r.above_200d ? "Up" : "Down"}</span>);
const FromHigh = ({ v }: { v: number | null }) => (v === null ? <span className="muted">–</span> : v > -1 ? <>At high</> : <>{fmtPct(v, 0)}</>);
const Vol = ({ v }: { v: number | null }) => (v === null ? <span className="muted">–</span> : <>{fmtNum(v, 0)}%</>);

interface Col { key: SortKey; label: string; short?: string; term?: TermId; hint: ReactNode; cls?: string; cell: (r: ScreenerRow) => ReactNode }

function columns(res: ScreenerResult): Col[] {
  const sb = res.bands.size, vb = res.bands.valuation;
  return [
    { key: "market_cap", label: "Size", term: "market-cap",
      hint: <>What the whole company is worth on the stock market (share price × number of shares), in US dollars. Small {bandText(sb[0], money)}, Mid {bandText(sb[1], money)}, Large {bandText(sb[2], money)}, Mega {bandText(sb[3], money)}. Every S&amp;P 500 company is big; these groups split them.</>,
      cell: (r) => (r.market_cap === null ? <span className="muted">–</span> : <><span>{money(r.market_cap)}</span>{r.size && <span className="muted small"> {SIZE_NAME[r.size]}</span>}</>) },
    { key: "pe", label: "P/E", term: "pe-ratio",
      hint: <>Price ÷ profit per share over the last 12 months: how many years of today's profit you pay for. Under {vb[0]?.max} = cheap, {vb[1]?.min}–{vb[1]?.max} = fair, over {vb[2]?.min} = expensive. A dash means the company lost money (no profit, so no P/E).</>,
      cell: (r) => <Pe v={r.pe} /> },
    { key: "forward_pe", label: "Next-yr P/E", term: "pe-ratio", cls: "hide-md",
      hint: "The same, using analysts' profit forecast for the next 12 months. Lower than the P/E means profits are expected to grow. Forecasts can be wrong.",
      cell: (r) => <Pe v={r.forward_pe} /> },
    { key: "dividend_yield", label: "Dividend", term: "dividend-yield",
      hint: "Cash the company pays its shareholders each year, as a percentage of the share price. None = it pays no dividend.",
      cell: (r) => <DivCell v={r.dividend_yield} /> },
    { key: "change_pct", label: "Today",
      hint: "Price move since yesterday's close (stock prices are about 15 minutes delayed).", cell: (r) => <Pct v={r.change_pct} d={2} /> },
    { key: "ret_1m", label: "1M", cls: "hide-lg", hint: "Price change over the last month (about 21 trading days), dividends counted.", cell: (r) => <Pct v={r.ret_1m} /> },
    { key: "ret_6m", label: "6M", term: "momentum",
      hint: "Price change over the last 6 months, dividends counted. The Momentum filter ranks stocks by this.", cell: (r) => <Pct v={r.ret_6m} /> },
    { key: "ret_12m", label: "12M", hint: "Price change over the last 12 months, dividends counted. Past returns don't predict future ones.", cell: (r) => <Pct v={r.ret_12m} /> },
    { key: "vs_200d_pct", label: "Trend", term: "200-day-average",
      hint: "Up = the price is above its 200-day average (about 10 months of prices): the long-term trend is rising. Down = below it.",
      cell: (r) => <TrendCell r={r} /> },
    { key: "from_high_pct", label: "From high", term: "52-week-high",
      hint: "How far the price is below its highest point of the last 12 months. At high = within 1% of it; −40% = far below.",
      cell: (r) => <FromHigh v={r.from_high_pct} /> },
    { key: "volatility", label: "Swings", term: "volatility",
      hint: "How much the price swings in a year, from the last 3 months of daily moves. Around 20% is calm for a stock; 50% or more is very jumpy.",
      cell: (r) => <Vol v={r.volatility} /> },
    { key: "beta", label: "Beta", term: "beta", cls: "hide-lg",
      hint: "How much the stock tends to move when the S&P 500 moves 1%. Beta 1.5 = about 1.5%; 0.5 = about half as much.",
      cell: (r) => (r.beta === null ? <span className="muted">–</span> : <>{fmtNum(r.beta, 2)}</>) },
  ];
}

function ChipGroup<T extends string>({ label, hint, term, options, names, value, onChange }: {
  label: string; hint: ReactNode; term?: TermId; options: T[]; names: (o: T) => ReactNode; value: T[]; onChange: (v: T[]) => void;
}) {
  return (
    <div className="scr-filter" role="group" aria-label={label}>
      <span className="scr-label">{label}<Hint term={term}>{hint}</Hint></span>
      <div className="scr-chips">
        {options.map((o) => {
          const on = value.includes(o);
          return <button key={o} type="button" className={`chip btn-chip ${on ? "active" : ""}`} aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}>{names(o)}</button>;
        })}
      </div>
    </div>
  );
}

function SelectFilter<T extends string>({ label, hint, term, value, options, onChange }: {
  label: string; hint: ReactNode; term?: TermId; value: T; options: [T, string][]; onChange: (v: T) => void;
}) {
  return (
    <div className="scr-filter">
      <span className="scr-label" id={`scr-${label}`}>{label}<Hint term={term}>{hint}</Hint></span>
      <select aria-labelledby={`scr-${label}`} value={value} onChange={(e) => onChange(e.target.value as T)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  );
}

function RowCard({ r }: { r: ScreenerRow }) {
  return (
    <li>
      <Link to={stockPath(r.symbol)} className="scr-card">
        <span className="scr-card-top">
          <span className="avatar">{r.symbol.replace(/[-.^/].*/, "").slice(0, 4)}</span>
          <span className="pc-name"><strong className="ellipsis">{r.name}</strong><span className="muted small ellipsis">{r.symbol} · {r.sector}</span></span>
          <span className="pc-num"><span className="num">{fmtPrice(r.price)}</span><span className="small"><Pct v={r.change_pct} d={2} /></span></span>
        </span>
        <span className="scr-figs">
          <span><span className="muted">Size</span><span>{r.market_cap === null ? <span className="muted">–</span> : <>{money(r.market_cap)}{r.size && <span className="muted"> {SIZE_NAME[r.size]}</span>}</>}</span></span>
          <span><span className="muted">P/E</span><span><Pe v={r.pe} />{r.valuation && <span className="muted"> {r.valuation === "no_profit" ? "Loss" : VAL_NAME[r.valuation]}</span>}</span></span>
          <span><span className="muted">Dividend</span><span><DivCell v={r.dividend_yield} /></span></span>
          <span><span className="muted">6 months</span><span><Pct v={r.ret_6m} /></span></span>
          <span><span className="muted">Trend</span><span><TrendCell r={r} /></span></span>
          <span><span className="muted">From high</span><span><FromHigh v={r.from_high_pct} /></span></span>
        </span>
      </Link>
    </li>
  );
}

export default function Screener({ query }: { query: string }) {
  const [res, setRes] = useState<ScreenerResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const [shown, setShown] = useState(PAGE);
  const f = useMemo(() => parse(params), [params]);

  const [filtersOpen, setFiltersOpen] = useState(() => typeof window === "undefined" || window.innerWidth > 860);

  useEffect(() => {
    let alive = true;
    let timer = 0;
    // Prices every 5 minutes (company figures change once a day); every 30 s while the first figures are still loading.
    const load = () => api.screener()
      .then((d) => {
        if (!alive) return;
        setRes(d);
        setError(null);
        const loading = !d.coverage.technicals_ready || (d.coverage.refreshing && d.coverage.with_fundamentals < d.coverage.total);
        timer = window.setTimeout(load, loading ? 30_000 : 300_000);
      })
      .catch((e) => {
        if (!alive) return;
        setError(`The screener could not be loaded. ${(e as Error).message}`);
        timer = window.setTimeout(load, 60_000);
      });
    load();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  const set = (next: Partial<Filters>) => {
    const m = { ...f, ...next };
    const p = new URLSearchParams({ by: "screener" });
    if (m.sector) p.set("sector", m.sector);
    if (m.size.length) p.set("size", m.size.join(","));
    if (m.val.length) p.set("val", m.val.join(","));
    if (m.div) p.set("div", m.div);
    if (m.trend) p.set("trend", m.trend);
    if (m.mom) p.set("mom", m.mom);
    if (m.sort !== DEFAULT.sort) p.set("sort", m.sort);
    if (m.order !== DEFAULT.order) p.set("order", m.order);
    setParams(p, { replace: true });
    setShown(PAGE);
  };
  const sortBy = (key: SortKey) => set(f.sort === key ? { order: f.order === "asc" ? "desc" : "asc" } : { sort: key, order: FIRST_ASC.includes(key) ? "asc" : "desc" });
  const activePreset = PRESETS.find((p) => JSON.stringify({ ...DEFAULT, ...p.f }) === JSON.stringify(f))?.id;
  const activeCount = [f.sector, f.size.length, f.val.length, f.div, f.trend, f.mom].filter(Boolean).length;
  const filtered = activeCount > 0;

  const q = query.trim().toLowerCase();
  const rows = useMemo(() => (res ? sortRows(res.rows.filter((r) => matches(r, f, res.bands.strong_momentum_pct, q)), f.sort, f.order) : []), [res, f, q]);

  if (!res) return error ? <ErrorBox error={error} /> : <div className="empty"><Spinner /> Loading the screener…</div>;
  const cols = columns(res);
  const cov = res.coverage;
  const sb = res.bands.size, vb = res.bands.valuation;
  const preset = PRESETS.find((p) => p.id === activePreset);

  return (
    <section className="screener" aria-label="Screener">
      <ErrorBox error={error} />
      <div className="scr-presets" role="group" aria-label="Ready-made screens">
        <span className="scr-label">Start from<Hint term="screener">Ready-made filters for common questions. Pick one, then change any filter below. A screener gives a list to study, not a list to buy.</Hint></span>
        <div className="scr-chips">
          {PRESETS.map((p) => (
            <button key={p.id} type="button" className={`chip btn-chip ${activePreset === p.id ? "active" : ""}`} aria-pressed={activePreset === p.id}
              onClick={() => set(activePreset === p.id ? DEFAULT : { ...DEFAULT, ...p.f })}>{p.label}</button>))}
        </div>
        {preset && <p className="muted small scr-preset-hint">{preset.hint}</p>}
      </div>

      <details className="customize scr-box" open={filtersOpen} onToggle={(e) => setFiltersOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary>Filters <span className="muted">· {activeCount ? `${activeCount} on` : "none on: every stock is listed"}</span></summary>
      <div className="scr-filters">
        <SelectFilter label="Sector" term="sector" value={f.sector}
          hint="The kind of business: technology, health care, energy… Mixing sectors spreads your risk."
          options={[["", "All sectors"], ...res.sectors.map((s): [string, string] => [s, s])]} onChange={(sector) => set({ sector })} />
        <ChipGroup label="Size" term="market-cap" options={SIZES} value={f.size} onChange={(size) => set({ size })}
          names={(o) => SIZE_NAME[o]}
          hint={<>Company value on the stock market, in US dollars. Small {bandText(sb[0], money)}, Mid {bandText(sb[1], money)}, Large {bandText(sb[2], money)}, Mega {bandText(sb[3], money)}. Bigger companies tend to swing less.</>} />
        <ChipGroup label="Valuation" term="pe-ratio" options={VALS} value={f.val} onChange={(val) => set({ val })}
          names={(o) => VAL_NAME[o]}
          hint={<>By P/E (price ÷ yearly profit per share). Cheap: under {vb[0]?.max}. Fair: {vb[1]?.min}–{vb[1]?.max}. Expensive: over {vb[2]?.min}. Losing money: no profit over the last 12 months. Fast-growing companies often look expensive; cheap ones can be shrinking.</>} />
        <SelectFilter<Div> label="Dividend" term="dividend-yield" value={f.div}
          hint="Yearly cash paid to shareholders as a % of the price. The S&P 500 as a whole pays a bit over 1%."
          options={[["", "Any"], ["pays", "Pays a dividend"], ["2", "2% or more"], ["4", "4% or more"]]} onChange={(div) => set({ div })} />
        <SelectFilter<Trend> label="Trend" term="uptrend" value={f.trend}
          hint="Uptrend: the price is above its 200-day average (about 10 months), so the long-term direction is up. The Beat-the-S&P picks only buy uptrends."
          options={[["", "Any"], ["up", "In an uptrend"], ["down", "In a downtrend"]]} onChange={(trend) => set({ trend })} />
        <SelectFilter<Mom> label="Momentum" term="momentum" value={f.mom}
          hint={`Stocks that rose most over 6 months tend to keep doing better for a while. Strongest = the top ${100 - res.bands.strong_momentum_pct}% of all ${res.total} stocks.`}
          options={[["", "Any"], ["positive", "Rising over 6 months"], ["strong", `Strongest ${100 - res.bands.strong_momentum_pct}%`]]} onChange={(mom) => set({ mom })} />
      </div>
      </details>

      <div className="scr-head">
        <h2 className="section-title">{rows.length} of {res.total} stocks{q && ` matching "${query.trim()}"`}
          <Hint>Company figures (size, P/E, dividend, beta) come from Yahoo Finance and are refreshed once a day before the US market opens. Prices, returns and trend are recomputed every few minutes (about 15 minutes delayed).</Hint></h2>
        <div className="scr-tools">
          <label className="scr-sort scr-phone">
            <span className="sr-only">Sort by</span>
            <select value={f.sort} onChange={(e) => sortBy(e.target.value as SortKey)} aria-label="Sort by">
              {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => <option key={k} value={k}>Sort: {SORT_LABEL[k]}</option>)}
            </select>
          </label>
          <button type="button" className="btn small scr-phone" onClick={() => set({ order: f.order === "asc" ? "desc" : "asc" })}
            aria-label={`Order: ${f.order === "asc" ? "lowest first" : "highest first"}. Tap to reverse.`}>{f.order === "asc" ? "Low → high" : "High → low"}</button>
          {filtered && <button type="button" className="btn small ghost" onClick={() => set({ ...DEFAULT, sort: f.sort, order: f.order })}>Clear filters</button>}
        </div>
      </div>
      <p className="muted small scr-coverage" role="status">
        {cov.refreshing && cov.with_fundamentals < cov.total
          ? <>Loading company figures in the background, a few stocks per second: {cov.with_fundamentals} of {cov.total} so far. Size, P/E and dividend filters skip stocks not loaded yet.</>
          : cov.with_fundamentals < cov.total
            ? <>Company figures for {cov.with_fundamentals} of {cov.total} stocks{cov.last_update ? `, updated ${fmtDay(cov.last_update)}` : ""}; the others are retried later.</>
            : <>Company figures for all {cov.total} stocks{cov.last_update ? `, updated ${fmtDay(cov.last_update)}` : ""}.</>}
        {" "}{cov.technicals_ready ? `Prices as of ${fmtTime(cov.technicals_as_of ?? res.as_of)}.` : "Prices are loading."}
      </p>

      {rows.length === 0 ? (
        <Empty>No stock matches all these filters{q ? ` and "${query.trim()}"` : ""}. Remove one (for example Valuation or Size) to see more.</Empty>
      ) : (
        <>
          <div className="table-wrap scr-table">
            <table>
              <thead>
                <tr>
                  <th aria-sort={f.sort === "name" ? (f.order === "asc" ? "ascending" : "descending") : "none"}>
                    <button type="button" className="th-sort" onClick={() => sortBy("name")}>Company{f.sort === "name" && <span aria-hidden>{f.order === "asc" ? " ↑" : " ↓"}</span>}</button>
                  </th>
                  {cols.map((c) => (
                    <th key={c.key} className={`r ${c.cls ?? ""}`} aria-sort={f.sort === c.key ? (f.order === "asc" ? "ascending" : "descending") : "none"}>
                      <button type="button" className="th-sort" onClick={() => sortBy(c.key)}>{c.label}{f.sort === c.key && <span aria-hidden>{f.order === "asc" ? " ↑" : " ↓"}</span>}</button>
                      <Hint term={c.term}>{c.hint}</Hint>
                    </th>))}
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((r) => (
                  <tr key={r.symbol}>
                    <td>
                      <Link className="asset" to={stockPath(r.symbol)}>
                        <span className="avatar">{r.symbol.replace(/[-.^/].*/, "").slice(0, 4)}</span>
                        <span><strong className="scr-name">{r.name}</strong><span className="muted small">{r.symbol} · {r.sector}</span></span>
                      </Link>
                    </td>
                    {cols.map((c) => <td key={c.key} className={`r num ${c.cls ?? ""}`}>{c.cell(r)}</td>)}
                  </tr>))}
              </tbody>
            </table>
          </div>
          <ul className="scr-cards">{rows.slice(0, shown).map((r) => <RowCard key={r.symbol} r={r} />)}</ul>
          {rows.length > shown && (
            <div className="scr-more">
              <button type="button" className="btn" onClick={() => setShown(shown + PAGE)}>Show {Math.min(PAGE, rows.length - shown)} more</button>
              <span className="muted small">Showing {shown} of {rows.length}</span>
            </div>)}
        </>
      )}
      <p className="muted small scr-note">A screen narrows {res.total} stocks down to a list worth studying; it is not a buy list. Past returns don't predict future ones, and cheap or high-dividend stocks can be cheap for a reason.</p>
    </section>
  );
}
