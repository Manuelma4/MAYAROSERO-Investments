import type { Provider } from "../lib/types";
import { Field } from "./ui";

export interface MarketSel { provider: Provider; exchange: string; symbol: string; timeframe: string }

const TIMEFRAMES: Record<Provider, string[]> = {
  yahoo: ["5m", "15m", "30m", "1h", "4h", "1d", "1wk"],
  ccxt: ["1m", "5m", "15m", "1h", "4h", "1d", "1w"],
};

export const PRESETS: { label: string; sel: MarketSel }[] = [
  { label: "S&P 500", sel: { provider: "yahoo", exchange: "binance", symbol: "^GSPC", timeframe: "1d" } },
  { label: "Nasdaq 100", sel: { provider: "yahoo", exchange: "binance", symbol: "^NDX", timeframe: "1d" } },
  { label: "CAC 40", sel: { provider: "yahoo", exchange: "binance", symbol: "^FCHI", timeframe: "1d" } },
  { label: "DAX", sel: { provider: "yahoo", exchange: "binance", symbol: "^GDAXI", timeframe: "1d" } },
  { label: "Apple", sel: { provider: "yahoo", exchange: "binance", symbol: "AAPL", timeframe: "1d" } },
  { label: "NVIDIA", sel: { provider: "yahoo", exchange: "binance", symbol: "NVDA", timeframe: "1d" } },
  { label: "BTC", sel: { provider: "ccxt", exchange: "binance", symbol: "BTC/USDT", timeframe: "4h" } },
  { label: "ETH", sel: { provider: "ccxt", exchange: "binance", symbol: "ETH/USDT", timeframe: "4h" } },
];

export function MarketPicker({ value, onChange, multi = false }: { value: MarketSel; onChange: (v: MarketSel) => void; multi?: boolean }) {
  const set = (patch: Partial<MarketSel>) => onChange({ ...value, ...patch });
  return (
    <>
      <Field label="Market">
        <select value={value.provider} onChange={(e) => {
          const provider = e.target.value as Provider;
          set({ provider, timeframe: TIMEFRAMES[provider].includes(value.timeframe) ? value.timeframe : "1d",
            symbol: provider === "ccxt" ? "BTC/USDT" : "AAPL" });
        }}>
          <option value="yahoo">Stocks / indices (Yahoo)</option>
          <option value="ccxt">Crypto (ccxt)</option>
        </select>
      </Field>
      {value.provider === "ccxt" && (
        <Field label="Exchange">
          <select value={value.exchange} onChange={(e) => set({ exchange: e.target.value })}>
            {["binance", "bybit", "okx", "kraken", "coinbase", "bitget"].map((x) => <option key={x}>{x}</option>)}
          </select>
        </Field>
      )}
      <Field label={multi ? "Symbols (comma separated)" : "Symbol"} wide={multi}>
        <input value={value.symbol} spellCheck={false} onChange={(e) => set({ symbol: e.target.value.toUpperCase() })}
          placeholder={value.provider === "ccxt" ? "BTC/USDT" : "AAPL, ^GSPC, MC.PA"} />
      </Field>
      <Field label="Timeframe">
        <select value={value.timeframe} onChange={(e) => set({ timeframe: e.target.value })}>
          {TIMEFRAMES[value.provider].map((x) => <option key={x}>{x}</option>)}
        </select>
      </Field>
    </>
  );
}
