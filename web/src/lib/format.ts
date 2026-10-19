export const fmtPrice = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6;
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

export const fmtPct = (v: number | null | undefined, digits = 1, sign = true) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${sign && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;

export const fmtNum = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits });

export const fmtTime = (iso: string | number) => {
  const d = typeof iso === "number" ? new Date(iso * 1000) : new Date(iso);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

export const fmtDate = (sec: number) =>
  new Date(sec * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });

export const tone = (v: number | null | undefined) => (v === null || v === undefined || v === 0 ? "" : v > 0 ? "up" : "down");
