import { useSyncExternalStore } from "react";

export type ThemePref = "system" | "dark" | "light";
const KEY = "mri.theme";
const listeners = new Set<() => void>();

function read(): ThemePref {
  try { return (localStorage.getItem(KEY) as ThemePref) || "system"; } catch { return "system"; }
}

export function applyTheme(pref: ThemePref = read()) {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", pref);
}

export function setThemePref(pref: ThemePref) {
  try { localStorage.setItem(KEY, pref); } catch { /* storage unavailable */ }
  applyTheme(pref);
  listeners.forEach((l) => l());
}

const media = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: light)") : null;
media?.addEventListener("change", () => listeners.forEach((l) => l()));

function snapshot(): string {
  const pref = read();
  const resolved = pref === "system" ? (media?.matches ? "light" : "dark") : pref;
  return `${pref}:${resolved}`;
}

/** Current preference and the resolved theme; re-renders on change. */
export function useTheme() {
  const snap = useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb); }, snapshot);
  const [pref, resolved] = snap.split(":") as [ThemePref, "dark" | "light"];
  return { pref, resolved };
}

export const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
