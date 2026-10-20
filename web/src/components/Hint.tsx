import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { TermId } from "../lib/glossary";

/**
 * Small "?" button that reveals a plain-English explanation (a disclosure, not a tooltip).
 * Click or Enter/Space toggles it; Escape, clicking elsewhere or tabbing away closes it.
 * The panel is positioned against the viewport so scroll containers (tables) never clip it.
 * `term` (a glossary id) adds a small "Learn more" link to that entry on the Learn page. Only the id type is
 * imported, so the glossary text stays in the Learn page's own chunk.
 */
export function Hint({ children, label = "What this means", term }: { children: ReactNode; label?: string; term?: TermId }) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<CSSProperties>({});
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);

  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const r = btn.current.getBoundingClientRect();
    const width = Math.min(300, window.innerWidth - 32);
    const left = Math.max(16, Math.min(r.left + r.width / 2 - width / 2, window.innerWidth - width - 16));
    setStyle({ position: "fixed", top: r.bottom + 8, left, width });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); btn.current?.focus(); } };
    const onScroll = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  return (
    <span className="hint" ref={wrap} onBlur={(e) => { if (!wrap.current?.contains(e.relatedTarget as Node)) setOpen(false); }}>
      <button ref={btn} type="button" className="hint-btn" aria-label={label} aria-expanded={open} aria-controls={id}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); }}>?</button>
      <span id={id} className="hint-pop" hidden={!open} style={style} tabIndex={-1}>
        {children}
        {term && <Link className="hint-more" to={`/learn?term=${term}`} onClick={() => setOpen(false)}>Learn more in the glossary</Link>}
      </span>
    </span>
  );
}
