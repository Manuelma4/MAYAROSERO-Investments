import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/** Small "?" that reveals a plain-English explanation. Tap or hover; Esc or tap outside closes. */
export function Hint({ children, label = "What this means" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <span className="hint" ref={ref}>
      <button type="button" className="hint-btn" aria-label={label} aria-expanded={open} aria-describedby={open ? id : undefined}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open); }}>?</button>
      {open && <span role="tooltip" id={id} className="hint-pop">{children}</span>}
    </span>
  );
}
