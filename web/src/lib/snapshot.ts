/**
 * Preview mode (VITE_STATIC=1): the app runs without a server, answering API calls
 * from a snapshot of real market data exported by scripts/export_snapshot.py.
 */
export const STATIC = import.meta.env.VITE_STATIC === "1";

const cache = new Map<string, Promise<unknown>>();
function load<T>(file: string): Promise<T> {
  if (!cache.has(file)) cache.set(file, fetch(`./data/${file}`).then((r) => {
    if (!r.ok) throw new Error("missing");
    return r.json();
  }));
  return cache.get(file) as Promise<T>;
}

export const safeName = (s: string) => s.replace(/[^A-Za-z0-9]/g, "_");

export class PreviewLimit extends Error {}

const limit = (what: string) => {
  throw new PreviewLimit(`${what} runs on the live server. This preview shows a snapshot of real data.`);
};

/** Resolve an API call from the snapshot. */
export async function snapshotRequest(path: string, init: RequestInit = {}): Promise<unknown> {
  const url = new URL(path, "https://x");
  const p = url.pathname;
  const body = init.body ? JSON.parse(String(init.body)) : {};
  switch (p) {
    case "/api/strategies": return load("strategies.json");
    case "/api/universe": return load("universe.json");
    case "/api/live/status": return load("status.json");
    case "/api/events": return load("events.json");
    case "/api/paper": return load("paper.json");
    case "/api/quotes": {
      const all = await load<Record<string, unknown>>("quotes.json");
      return (url.searchParams.get("symbols") ?? "").split(",").filter(Boolean)
        .map((s) => all[s] ?? { symbol: s, provider: "yahoo", error: "Not in preview snapshot" });
    }
    case "/api/chart": {
      const sym = url.searchParams.get("symbol") ?? "";
      const tf = url.searchParams.get("timeframe") ?? "1d";
      try { return await load(`charts/${safeName(sym)}_${tf}.json`); } catch {
        try { return await load(`charts/${safeName(sym)}_1d.json`); } catch { return limit(`Charts for ${sym} ${tf}`); }
      }
    }
    case "/api/today": return load("today.json");
    case "/api/opportunities": case "/api/opportunities/scan": return load("opportunities.json");
    case "/api/paper/orders": return limit("Placing paper orders");
    case "/api/ai/status": return { enabled: false, how_to_enable: "Runs on the live app with a Claude API key." };
    case "/api/ai/analyze": return limit("The AI analyst");
    case "/api/picks/latest": {
      try { return await load(`picks_${url.searchParams.get("preset") ?? "quality_momentum"}.json`); } catch { return limit("This strategy"); }
    }
    case "/api/picks": {
      try { return await load(`picks_${body.preset ?? "quality_momentum"}.json`); } catch { return limit("This strategy"); }
    }
    case "/api/backtest": return load("backtest.json");
    case "/api/predict": return load("predict.json");
    case "/api/live/start": case "/api/live/stop": case "/api/live/scan": return limit("The real-time engine");
  }
  return limit("This feature");
}

export async function snapshotMeta(): Promise<{ as_of: string }> {
  return load("meta.json");
}
