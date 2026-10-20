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
        <p className="lead learn-lead">Realistically, expect the default strategy to beat the S&amp;P&nbsp;500 by about 1–2% a year at best, with slightly bigger drops. It is not proven, it will have bad years, and the way you size and spread your money matters more than any single pick.</p>
        <div className="kpis learn-kpis">
          <div className="kpi"><span className="kpi-label">Core + momentum, per year<Hint term="cagr">Average yearly growth of the default Beat-the-S&amp;P strategy (60% S&amp;P&nbsp;500 index + 40% in the 10 strongest momentum stocks, monthly review) in the test from January 2015 to October 2026, costs included, stocks counted only while in the index. Without 2026 (a big chip-stock year): about 16% vs 13.4%.</Hint></span><span className="kpi-value">≈ 18.6%</span><span className="kpi-sub">backtest; realistic edge ≈ +1–2%/yr</span></div>
          <div className="kpi"><span className="kpi-label">S&amp;P 500, per year<Hint term="spy">What simply holding SPY (dividends included) did over the same years. Doing nothing is the bar to beat.</Hint></span><span className="kpi-value">≈ 13.7%</span><span className="kpi-sub">SPY, dividends included</span></div>
          <div className="kpi"><span className="kpi-label">Worst drop<Hint term="drawdown">The biggest fall from a peak in the test (early 2020). Keeping 60% in the index kept the drop close to the market's; the momentum stocks alone fell 40%.</Hint></span><span className="kpi-value down">−36%</span><span className="kpi-sub">S&amp;P 500 −34%</span></div>
          <div className="kpi"><span className="kpi-label">3-year periods ahead<Hint term="benchmark">Every 3-year stretch since 2015, starting each month: in 83% of them the strategy grew faster than the S&amp;P&nbsp;500 (worst stretch: 3% a year behind). The stretches overlap, so this is weaker evidence than it sounds. Single months: ahead in 59%.</Hint></span><span className="kpi-value">83%</span><span className="kpi-sub">8 of 12 calendar years ahead</span></div>
        </div>
        <div className="honest-grid">
          <div>
            <h3 className="learn-sub">What the test really shows</h3>
            <p>We wrote down 14 candidate strategies in advance, chose using only 2015-2020, then checked on 2021-2026. The pre-registered winner did not pass, and the default, Core + momentum, was picked from extra robustness runs made after we had seen the 2021-2026 results, so that period is not a clean test. In the backtest it made 18.6% a year vs 13.7%, but about half of that lead is 2026 alone and a handful of chip, storage and vaccine stocks (MU, SNDK, WDC, STX, DELL, NVDA, MRNA).</p><p>A second, independent review tried to break it. No look-ahead was found, and it survives different start dates, review days, 0.25% trading costs and a one-day delay. But without its 7 biggest winners, with 0.5% costs, or with a realistic allowance for companies that left the index, the edge shrinks to about zero outside 2026. Its honest summary: about +1–2% a year over the S&amp;P&nbsp;500, with drops 2–3 points deeper, not proven.</p><p>The simplest investable version needs no stock picking: 60% in an S&amp;P&nbsp;500 fund + 40% in a momentum fund such as SPMO (Invesco S&amp;P 500 Momentum). Since late 2015 that mix did about +1.5% a year better than the S&amp;P&nbsp;500 with a slightly smaller worst drop, using real fund prices (no survivorship bias).</p>
            <p>Why we do not call it proven: after allowing for the 33 variants we tried, the chance the edge is real is about 80%, short of the 95% scientists ask for. Re-shuffling the 2015-2020 months alone, it came out ahead over 10 years in about 85% of cases. Rotating between sector funds, which we could test back to 2000 with no bias, did not beat the S&amp;P&nbsp;500 after 2013, and real momentum funds have had long losing stretches. Some bias remains in our stock test (companies that left the index are missing), so treat the figures as an upper estimate until the live track record confirms them.</p>
            <p>The ready-made plans on My portfolio use the same momentum ranking with a swings limit. In the same test: Bold (up to 60% picks) about 16.5% a year with a deeper worst drop (−39%), Balanced about 14% (the risk limit keeps it close to the S&amp;P&nbsp;500, return and swings alike), Cautious about 11% with smaller drops. Simply holding the S&amp;P&nbsp;500 stays a strong, cheap choice.</p>
          </div>
          <div>
            <h3 className="learn-sub">Why most traders lose</h3>
            <p>Studies of retail day traders find that the large majority lose money over a year. The usual reasons: trading too often (costs and spreads add up), betting too much on one idea, moving the stop-loss when wrong, and quitting a sound plan after a bad month.</p>
            <p>The app is built against those habits: few trades, a stop and a size for every idea, and a monthly rhythm.</p>
          </div>
          <div>
            <h3 className="learn-sub">Why small and spread out wins</h3>
            <p>Risking 1% per idea means ten losses in a row still leave 90% of your account. Ten equal positions mean one stock halving costs you 5%, not 50%. Spreading across sectors protects you when one whole industry falls.</p>
            <p>Big drops will happen. In 2020 and 2022 the index fell 25 to 34%, the default strategy fell 36% at its worst, and the momentum stocks on their own about 40%. Only invest money you will not need for five years or more.</p>
          </div>
          <div>
            <h3 className="learn-sub">A good plan for a beginner</h3>
            <p>Keep most of your money in a broad index fund (the default strategy already keeps 60% there), follow the routine above, and use the practice account for short-term ideas until you understand why they win and lose.</p>
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
