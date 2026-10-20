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
  if (/^\/api\/(watchlists|alerts)\/\d+/.test(p)) return limit("Editing watchlists and alerts");
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
    case "/api/track-record": {
      try { return await load("track_record.json"); } catch {
        return { preset: "quality_momentum", as_of: new Date().toISOString(), started: null, days: 0, too_early: true,
          message: "The live record runs on the live server: from its first market close on, the picks and every Invest-now idea are saved each day and followed with real prices.",
          picks: { days: 0, curve: [], snapshots: 0, latest_date: null, current: [], risk_off: false },
          ideas: { count: 0, closed_count: 0, open_count: 0, pending_count: 0, win_rate: null, avg_r: null, "total_r_%": null, open: [], closed: [] } };
      }
    }
    case "/api/opportunities": case "/api/opportunities/scan": return load("opportunities.json");
    case "/api/paper/orders": case "/api/orders/preview": case "/api/orders": return limit("Placing orders");
    case "/api/orders/close-all": case "/api/orders/resume": return limit("The kill switch");
    case "/api/broker/positions": return { broker: "paper", mode: "paper", positions: [], orders: [] };
    case "/api/broker/status": return {
      broker: "paper", mode: "paper", connected: false, error: "Preview: no broker connection.", halted: null, confirm_seconds: 90,
      limits: { risk_per_trade_pct: 1, max_position_pct: 10, max_open_positions: 5, max_short_exposure_pct: 20, max_daily_loss_pct: 3, max_order_value: null, max_daily_loss_value: null },
    };
    case "/api/portfolio": {
      try { return await load(`portfolio_${body.risk ?? "balanced"}.json`); } catch { return limit("Building a portfolio"); }
    }
    case "/api/portfolio/drift": return { status: "no_target", target: null,
      message: "Saving a target and the weekly drift check run on the live server. This preview has no saved target." };
    case "/api/portfolio/risk": return { status: "no_target", message: "The risk view of a saved target runs on the live server." };
    case "/api/portfolio/target": return limit("Saving a target");
    case "/api/digest/preview": {
      try { return await load("digest.json"); } catch {
        let mood = "Market mood: see the Today page.";
        try { const t = await load<{ mood?: { label: string; advice?: string } | null }>("today.json"); if (t.mood) mood = `Market mood: ${t.mood.label}. ${t.mood.advice ?? ""}`.trim(); } catch { /* no snapshot */ }
        const text = ["MAYAROSERO weekly digest · preview", mood, "Picks: no change this week. The list is reviewed at each month end.",
          "Your price alerts: none fired this week.", "Live track record: runs on the live server, from its first market close on.",
          "Details in the app. Information, not advice."].join("\n");
        return { text, chars: text.length, last_sent: null, channels: [],
          schedule: { day: "Sunday", hour: 18, minute: 0, timezone: "Europe/Paris", enabled: true, text: "Sunday at 18:00 (Europe/Paris)", next: null } };
      }
    }
    case "/api/digest/send-test": return limit("Sending the digest");
    case "/api/predictions": return load(`predictions_${url.searchParams.get("horizon") ?? "5"}.json`);
    case "/api/predictions/custom": return limit("Custom rankings");
    case "/api/forecast": {
      const sym = url.searchParams.get("symbol") ?? "";
      try { return await load(`forecasts/${safeName(sym)}_${url.searchParams.get("horizon") ?? "5"}.json`); } catch { return limit(`The forecast for ${sym}`); }
    }
    case "/api/stock": {
      const sym = url.searchParams.get("symbol") ?? "";
      try { return await load(`stocks/${safeName(sym)}.json`); } catch { return limit(`The page for ${sym}`); }
    }
    case "/api/watchlists": return init.method && init.method !== "GET" ? limit("Saving watchlists")
      : [{ id: 1, name: "Magnificent 7", symbols: ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"] }];
    case "/api/alerts": return init.method === "POST" ? limit("Price alerts")
      : { kinds: { above: "Price rises to or above", below: "Price falls to or below", move: "Moves at least this % in one day (up or down)" }, alerts: [] };
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
