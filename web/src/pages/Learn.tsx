import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Hint } from "../components/Hint";
import { replayTour } from "../components/Tour";
import { GLOSSARY, glossaryEntry, learnPath, letterOf, matchesQuery, type GlossaryEntry } from "../lib/glossary";

/** Learn: a 5-minute guide, the glossary and honest expectations. Static content: no API calls. */

const ROUTINE = [
  { when: "Every day · 2 min", title: "Check Today", text: "The market mood, what to hold and any live idea. Everything is already computed: nothing to press.", to: "/", cta: "Open Today" },
  { when: "At month end", title: "Look at the picks changes", text: "The picks are reviewed once a month. Buy the new names, sell the ones that dropped out, keep the rest.", to: "/picks", cta: "Open Beat the S&P" },
  { when: "When you have a price in mind", title: "Set a price alert", text: "Instead of watching the screen, let the app tell you once a stock reaches your level.", to: "/alerts", cta: "Open Alerts" },
  { when: "Before real money", title: "Practise first", text: "Try Invest-now ideas with the practice account for a few months and watch the live track record.", to: "/now", cta: "Open Invest now" },
];

const PAGES = [
  { to: "/", name: "Today", what: "Your daily summary: market mood, what to hold now, live ideas and the latest alerts." },
  { to: "/portfolio", name: "My portfolio", what: "Turns an amount of money into a shopping list of shares, spread across sectors, and tracks drift." },
  { to: "/picks", name: "Beat the S&P", what: "The engine's long-term stocks to hold, reviewed monthly, with the honest track record." },
  { to: "/now", name: "Invest now", what: "Short-term ideas backed by news and heavy volume, each with an entry, a stop-loss and a target." },
  { to: "/alerts", name: "Alerts", what: "Your price alerts, watchlists, sudden moves and every change to the picks." },
  { to: "/discover", name: "Discover", what: "Browse the world's leading companies by sector, with live prices." },
  { to: "/charts", name: "Charts", what: "Candles, averages and an automatic reading of any market's trend." },
  { to: "/predict", name: "Predict", what: "A machine-learning ranking of which stocks may beat the others, with its measured accuracy." },
  { to: "/backtest", name: "Backtest", what: "Test a chart setup on years of past prices before trusting it." },
  { to: "/settings", name: "Settings", what: "Practice or real money, safety limits, the kill switch, theme and notifications." },
];

const LETTERS = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

/** One entry: the definition is always shown; where it is used and the example open on demand. */
function Entry({ e, active, open }: { e: GlossaryEntry; active: boolean; open: boolean }) {
  const related = (e.related ?? []).map(glossaryEntry).filter((x): x is GlossaryEntry => !!x);
  return (
    <article id={`term-${e.id}`} className={`gloss ${active ? "active" : ""}`} tabIndex={-1} aria-labelledby={`t-${e.id}`}>
      <h3 id={`t-${e.id}`} className="gloss-term">{e.term}</h3>
      <p className="gloss-def">{e.definition}</p>
      <details className="gloss-more" open={open || active}>
        <summary>In this app · example</summary>
        <dl className="gloss-kv">
          <dt>In this app</dt><dd>{e.inApp}</dd>
          <dt>Example</dt><dd>{e.example}</dd>
        </dl>
        {e.aka?.length ? <p className="gloss-aka">Also called {e.aka.join(" · ")}</p> : null}
        {related.length > 0 && (
          <p className="gloss-rel">See also {related.map((r, i) => <span key={r.id}>{i > 0 && " · "}<Link to={learnPath(r.id)}>{r.term}</Link></span>)}</p>
        )}
      </details>
    </article>
  );
}

export default function Learn() {
  const [params] = useSearchParams();
  const term = params.get("term");
  const [query, setQuery] = useState("");
  const [openAll, setOpenAll] = useState(false);
  const search = useRef<HTMLInputElement>(null);

  const sorted = useMemo(() => [...GLOSSARY].sort((a, b) => a.term.localeCompare(b.term, "en", { sensitivity: "base" })), []);
  const shown = useMemo(() => sorted.filter((e) => matchesQuery(e, query)), [sorted, query]);
  const groups = useMemo(() => {
    const m = new Map<string, GlossaryEntry[]>();
    for (const e of shown) { const l = letterOf(e); m.set(l, [...(m.get(l) ?? []), e]); }
    return [...m.entries()];
  }, [shown]);
  const present = new Set(groups.map(([l]) => l));
  // A short search result opens its entries: the example is what the person came for.
  const openEntries = openAll || (query.trim() !== "" && shown.length <= 4);

  // Deep link from a hint (/learn?term=id): show every entry, then bring that one into view.
  useEffect(() => {
    if (!term || !glossaryEntry(term)) return;
    setQuery("");
    const t = setTimeout(() => {
      const el = document.getElementById(`term-${term}`);
      el?.scrollIntoView({ block: "start" });
      el?.focus({ preventScroll: true });
    }, 30);
    return () => clearTimeout(t);
  }, [term]);

  const jump = (id: string) => {
    const el = document.getElementById(id);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="page learn">
      <section className="hero-x">
        <p className="eyebrow">Learn · plain English</p>
        <h1 className="display">Learn</h1>
        <p className="muted lead">How to use this app, what every word in it means, and what to honestly expect. Ten minutes here makes every other page easier.</p>
        <div className="hero-actions">
          <button type="button" className="btn primary" onClick={replayTour}>Take the quick tour</button>
          <button type="button" className="btn" onClick={() => jump("guide")}>5-minute guide</button>
          <button type="button" className="btn" onClick={() => jump("honest")}>Honest expectations</button>
          <button type="button" className="btn" onClick={() => jump("glossary")}>Glossary</button>
        </div>
      </section>

      {/* 1. How to use this app */}
      <section id="guide" className="learn-section" aria-labelledby="guide-h">
        <h2 id="guide-h" className="section-title">How to use this app in 5 minutes</h2>
        <h3 className="learn-sub">A simple routine</h3>
        <ol className="routine">
          {ROUTINE.map((r, i) => (
            <li key={r.title}>
              <span className="routine-n" aria-hidden>{String(i + 1).padStart(2, "0")}</span>
              <span className="kpi-label">{r.when}</span>
              <strong className="routine-title">{r.title}</strong>
              <p className="muted small">{r.text}</p>
              <Link to={r.to} className="link">{r.cta}</Link>
            </li>))}
        </ol>
        <h3 className="learn-sub">What each page is for</h3>
        <ul className="page-list">
          {PAGES.map((p) => (
            <li key={p.to}>
              <Link to={p.to} className="page-list-name">{p.name}</Link>
              <span className="muted small">{p.what}</span>
            </li>))}
        </ul>
      </section>

      {/* 2. Honest expectations */}
      <section id="honest" className="learn-section" aria-labelledby="honest-h">
        <h2 id="honest-h" className="section-title">Honest expectations</h2>
        <p className="lead learn-lead">The engine has a modest, real-looking edge in tests. It is not proven, it will have bad years, and the way you size and spread your money matters more than any single pick.</p>
        <div className="kpis learn-kpis">
          <div className="kpi"><span className="kpi-label">Picks, per year<Hint term="cagr">Average yearly growth of the Beat-the-S&amp;P picks in the test from January 2015 to October 2026: 10 stocks, monthly review, costs included, survivorship bias corrected.</Hint></span><span className="kpi-value">≈ 17%</span><span className="kpi-sub">in the test since 2015</span></div>
          <div className="kpi"><span className="kpi-label">S&amp;P 500, per year<Hint term="spy">What simply holding SPY (dividends included) did over the same years. Doing nothing is the bar to beat.</Hint></span><span className="kpi-value">≈ 14%</span><span className="kpi-sub">SPY, dividends included</span></div>
          <div className="kpi"><span className="kpi-label">Worst drop<Hint term="drawdown">The biggest fall from a peak in the test. The picks fell further than the index at their worst: higher returns came with a bumpier ride.</Hint></span><span className="kpi-value down">−39%</span><span className="kpi-sub">S&amp;P 500 −34%</span></div>
          <div className="kpi"><span className="kpi-label">Months ahead<Hint term="benchmark">Share of single months where the picks beat the S&amp;P 500. About half: the edge only shows over years, not weeks.</Hint></span><span className="kpi-value">49%</span><span className="kpi-sub">of months beat the index</span></div>
        </div>
        <div className="honest-grid">
          <div>
            <h3 className="learn-sub">What the test really shows</h3>
            <p>Holding the top 10 S&amp;P 500 stocks by momentum, reviewed monthly, grew about 17% a year since 2015 against about 14% for the S&amp;P 500. Before we corrected a test mistake (counting stocks before they joined the index), the same test claimed 37% a year: a reminder of how easily backtests flatter.</p>
            <p>Some bias remains, so treat 17% as an upper estimate. Three to four points a year over ten years is a lot of money, but it is not proven until it shows up in the live track record.</p>
            <p>The ready-made plans on My portfolio mix the picks with the S&amp;P 500 and cash so their swings match their label (Cautious, Balanced, Bold). With those limits, the same test gave about 11% a year for each level, below the S&amp;P 500's 14%, with smaller drops for Cautious. In plain words: so far the picks add excitement more than return once risk is controlled, and simply holding the S&amp;P 500 is a strong, cheap default.</p>
          </div>
          <div>
            <h3 className="learn-sub">Why most traders lose</h3>
            <p>Studies of retail day traders find that the large majority lose money over a year. The usual reasons: trading too often (costs and spreads add up), betting too much on one idea, moving the stop-loss when wrong, and quitting a sound plan after a bad month.</p>
            <p>The app is built against those habits: few trades, a stop and a size for every idea, and a monthly rhythm.</p>
          </div>
          <div>
            <h3 className="learn-sub">Why small and spread out wins</h3>
            <p>Risking 1% per idea means ten losses in a row still leave 90% of your account. Ten equal positions mean one stock halving costs you 5%, not 50%. Spreading across sectors protects you when one whole industry falls.</p>
            <p>Big drops will happen. In 2020 and 2022 the index fell 25 to 34%, and at their worst the picks fell 39%. Only invest money you will not need for five years or more.</p>
          </div>
          <div>
            <h3 className="learn-sub">A good plan for a beginner</h3>
            <p>Keep most of your money in a broad index fund or the monthly picks, follow the routine above, and use the practice account for short-term ideas until you understand why they win and lose.</p>
            <p>You do not need to be an expert. You need a plan you can stick with when the market is scary. This page is here whenever a word is unclear.</p>
          </div>
        </div>
        <p className="caveat">Figures from the app's own test of the default picks (January 2015 to October 2026, 10 stocks, monthly review, 0.10% costs per trade, taxes not included). Past results do not guarantee future ones. Market information and education, not financial advice.</p>
      </section>
      {/* 3. Glossary: the reference, last */}
      <section id="glossary" className="learn-section" aria-labelledby="glossary-h">
        <h2 id="glossary-h" className="section-title">Glossary · {GLOSSARY.length} terms</h2>
        <p className="muted small learn-howto">Search a word or tap a letter. Each entry says what it means; open it to see where you meet it in this app and a small example with numbers.</p>
        <div className="gloss-controls">
          <div className="search gloss-search">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
            <input ref={search} type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search a term, e.g. stop-loss or P/E" aria-label="Search the glossary" aria-controls="gloss-results"
              onKeyDown={(e) => { if (e.key === "Escape" && query) { e.preventDefault(); setQuery(""); } }} />
            {query && <button type="button" className="text-btn gloss-clear" onClick={() => { setQuery(""); search.current?.focus(); }}>Clear</button>}
          </div>
          <span className="muted small" role="status" aria-live="polite">{query ? `${shown.length} of ${GLOSSARY.length} terms` : `${GLOSSARY.length} terms`}</span>
          <button type="button" className="btn small gloss-toggle" aria-pressed={openAll} onClick={() => setOpenAll(!openAll)}>{openAll ? "Hide examples" : "Show all examples"}</button>
        </div>
        <nav className="az" aria-label="Glossary letters">
          {LETTERS.map((l) => (
            <button key={l} type="button" disabled={!present.has(l)} onClick={() => jump(`letter-${l}`)} aria-label={l === "#" ? "Terms starting with a number" : `Terms starting with ${l}`}>{l}</button>))}
        </nav>
        <div id="gloss-results">
          {groups.length === 0 ? (
            <div className="empty">
              No term matches "{query}". Try a shorter word, or <button type="button" className="text-btn" onClick={() => { setQuery(""); search.current?.focus(); }}>clear the search</button>.
            </div>
          ) : groups.map(([letter, entries]) => (
            <section key={letter} id={`letter-${letter}`} className="gloss-group" aria-label={`Letter ${letter}`}>
              <span className="gloss-letter" aria-hidden>{letter}</span>
              <div className="gloss-list">
                {entries.map((e) => <Entry key={e.id} e={e} active={e.id === term} open={openEntries} />)}
              </div>
            </section>))}
        </div>
      </section>

    </div>
  );
}
