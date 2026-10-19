/** MAYAROSERO mark: two peaks, the second rising higher. See BRAND.md. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden className="mark">
      <g fill="currentColor" transform="translate(1 -4)">
        <path d="M4 90 28 32.4 40.83 63.2 34.83 77.6 28 61.2 16 90z" />
        <path d="M34 90 64 18 94 90H82L64 46.8 46 90z" />
      </g>
    </svg>
  );
}

export function BrandLockup() {
  return (
    <div className="brand">
      <BrandMark size={30} />
      <div className="brand-text">
        <span className="brand-name">MAYAROSERO</span>
        <span className="brand-sub">Investments</span>
      </div>
    </div>
  );
}
