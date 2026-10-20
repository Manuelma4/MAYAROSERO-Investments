import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/**
 * First-visit tour: five short steps through the pages that matter most. It opens once by itself,
 * is remembered in localStorage once finished or skipped, and can be replayed from the Learn page.
 * A modal dialog: focus moves into it, Tab stays inside it, Escape closes it, focus returns afterwards.
 */
const KEY = "mri.tour";
const REPLAY = "mri:tour";

const STEPS = [
  { path: "/", title: "Today", text: "Start here. The market mood, what to hold now and any live idea, on one screen. Two minutes a day is enough." },
  { path: "/picks", title: "Beat the S&P", text: "The engine's stocks to hold, best first, in equal parts. They change only at month end: buy the new names, sell the dropped ones." },
  { path: "/now", title: "Invest now", text: "Short-term ideas with an entry, a stop-loss and a target. The Invest button uses practice money: real money stays off unless you switch it on yourself." },
  { path: "/alerts", title: "Alerts", text: "Pick a stock and a price, and get told once when it gets there. Changes to the picks and sudden moves land here too." },
  { path: "/learn", title: "Learn", text: "Every word in the app explained with a small example. Tap any ? for a quick hint, then Learn more for the full entry." },
];

export function tourDone(): boolean {
  try { return localStorage.getItem(KEY) === "done"; } catch { return true; }   // no storage: never nag
}

function markDone() {
  try { localStorage.setItem(KEY, "done"); } catch { /* storage unavailable */ }
}

/** Open the tour again (Learn page button). */
export function replayTour() {
  window.dispatchEvent(new Event(REPLAY));
}

export function Tour() {
  const [step, setStep] = useState<number | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const dialog = useRef<HTMLDivElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const textId = useId();

  const go = useCallback((i: number) => {
    setStep(i);
    if (location.pathname !== STEPS[i].path) navigate(STEPS[i].path);
  }, [location.pathname, navigate]);

  const close = useCallback(() => {
    markDone();
    setStep(null);
    const back = returnTo.current;
    returnTo.current = null;
    // Return focus where it was, or to the page's main heading after the tour moved pages.
    requestAnimationFrame(() => {
      if (back && document.contains(back)) back.focus();
      else (document.querySelector("main h1") as HTMLElement | null)?.focus?.();
    });
  }, []);

  useEffect(() => {
    const onReplay = () => { returnTo.current = document.activeElement as HTMLElement | null; go(0); };
    window.addEventListener(REPLAY, onReplay);
    return () => window.removeEventListener(REPLAY, onReplay);
  }, [go]);

  // Opens by itself once, the first time Today is shown (a deep link to another page is not interrupted).
  const auto = useRef(false);
  useEffect(() => {
    if (auto.current || location.pathname !== "/" || tourDone()) return;
    auto.current = true;
    setStep(0);
  }, [location.pathname]);

  const open = step !== null;
  useEffect(() => {
    if (!open) return;
    if (!returnTo.current) returnTo.current = document.activeElement as HTMLElement | null;
  }, [open]);

  // Each step: focus the main action so Enter moves on.
  useEffect(() => { if (step !== null) primary.current?.focus(); }, [step]);

  if (step === null) return null;
  const s = STEPS[step];
  const last = step === STEPS.length - 1;

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key !== "Tab" || !dialog.current) return;
    const items = Array.from(dialog.current.querySelectorAll<HTMLElement>("button:not(:disabled)"));
    if (!items.length) return;
    const first = items[0], end = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); end.focus(); }
    else if (!e.shiftKey && document.activeElement === end) { e.preventDefault(); first.focus(); }
  };

  return (
    <div className="tour-layer">
      <div className="tour-backdrop" aria-hidden onClick={close} />
      <div ref={dialog} className="tour" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={textId} onKeyDown={onKeyDown}>
        <div className="tour-top">
          <span className="tour-step">Quick tour · {step + 1} of {STEPS.length}</span>
          <button type="button" className="tour-skip" onClick={close}>Skip tour</button>
        </div>
        <ol className="tour-dots" aria-hidden>
          {STEPS.map((x, i) => <li key={x.path} className={i <= step ? "on" : ""} />)}
        </ol>
        <h2 id={titleId} className="tour-title">{s.title}</h2>
        <p id={textId} className="tour-text">{s.text}</p>
        <div className="tour-actions">
          {step > 0 && <button type="button" className="btn" onClick={() => go(step - 1)}>Back</button>}
          <button ref={primary} type="button" className="btn primary" onClick={() => (last ? close() : go(step + 1))}>
            {last ? "Start learning" : `Next: ${STEPS[step + 1].title}`}
          </button>
        </div>
      </div>
    </div>
  );
}
