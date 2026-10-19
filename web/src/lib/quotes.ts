import { useEffect, useState } from "react";
import { api } from "./api";
import type { Quote } from "./types";

/** Polls /api/quotes; prices refresh every `refreshMs` (server caches ~60 s). */
export function useQuotes(symbols: string[], refreshMs = 30_000) {
  const key = symbols.join(",");
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!key) { setLoading(false); return; }
    let alive = true;
    const load = () => api.quotes(key.split(","))
      .then((qs) => { if (alive) setQuotes(Object.fromEntries(qs.map((q) => [q.symbol, q]))); })
      .catch(() => undefined)
      .finally(() => alive && setLoading(false));
    load();
    const id = setInterval(load, refreshMs);
    return () => { alive = false; clearInterval(id); };
  }, [key, refreshMs]);
  return { quotes, loading };
}
