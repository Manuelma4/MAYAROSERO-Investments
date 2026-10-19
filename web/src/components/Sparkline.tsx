export function Sparkline({ data, width = 120, height = 36, className = "" }: { data?: number[]; width?: number; height?: number; className?: string }) {
  if (!data || data.length < 2) return <svg width={width} height={height} className={className} aria-hidden />;
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => [(i / (data.length - 1)) * width, height - 3 - ((v - min) / span) * (height - 6)]);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const up = data[data.length - 1] >= data[0];
  const id = `sp${Math.round(Math.random() * 1e9)}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={`spark ${up ? "up" : "down"} ${className}`} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="currentColor" stopOpacity="0.22" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${d}L${width},${height}L0,${height}Z`} fill={`url(#${id})`} />
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
