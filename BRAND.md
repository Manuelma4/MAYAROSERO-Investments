# MAYAROSERO Investments: brand guidelines

## Positioning
Market intelligence with the discipline of an engineering company: real-time
alerts, charts and a stock-selection engine built to beat the S&P 500.
Tone: precise, calm, confident. Never hype, never promises of returns.

Visual language: **aerospace minimalism**, in the spirit of Tesla and SpaceX.
Black and white, hairline rules, sharp geometry, wide engineered type, and color
used only where the data needs it.

## The mark
Two peaks, the second rising higher than the first: the portfolio overtaking
the market. Together they form an **M**.

Construction (viewBox 100×100, see `web/public/brand/mark.svg`):
- Every leg uses the same slope (rise/run = 2.4) and the same horizontal stroke (12 units).
- The left peak's inner leg is cut parallel to the right peak's outer edge with an
  even 4-unit gap, so the peaks interlock without touching.
- Pure geometry (no masks or effects), so it renders crisply from 16 px favicons to billboards.

Files in `web/public/brand/`: `mark.svg` (currentColor), `mark-white.svg`,
`mark-black.svg`, `app-icon.svg`, `wordmark.svg`. App icons and the social preview
(`icon-*.png`, `apple-touch-icon.png`, `og-image.png`) live in `web/public/`.

Rules: mark in pure white on black or pure black on white only. Clear space = the
gap between the peaks x3. Minimum 16 px. No gradients, outlines, shadows or rotation.

## Wordmark
**MAYAROSERO** set in Michroma, tracking +30%; **INVESTMENTS** below in Barlow
Medium, tracking +62%, 60% opacity. The mark sits left of the wordmark, its height
matching the two lines of type.

## Color
| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg` | `#000000` | `#FFFFFF` | Background |
| `--surface` | `#0A0A0B` | `#FFFFFF` | Cards |
| `--surface-2` | `#111113` | `#F4F4F5` | Inputs, hover |
| `--line` | `#1F1F23` | `#E6E6E9` | Hairlines, grid |
| `--text` | `#F5F5F7` | `#0A0A0B` | Primary text, primary buttons |
| `--text-2` | `#8E8E96` | `#5F5F68` | Secondary text, labels |
| `--up` | `#2FD67B` | `#0F9D58` | Price up, gains, long |
| `--down` | `#FF4B55` | `#E0242F` | Price down, losses, short |

The brand itself is monochrome. Green and red are reserved for market direction,
so color always means something.

## Typography
- **Michroma** (display): page titles in uppercase, the wordmark. Never for numbers.
- **Barlow** (DIN-style): interface and all figures. Labels are uppercase 10.5–12 px with
  +14–18% tracking; prices use tabular figures.

## Interface principles
1. Data is the hero; chrome is hairlines.
2. Sharp 4 px corners, 1 px rules, no shadows, no gradients.
3. Primary action = solid white (dark) / solid black (light) with uppercase tracked text.
4. Live by default: ticker tape, live connection indicator, real-time alert feed.
5. Mobile is first-class: installable app (PWA), bottom navigation.
6. Honesty: backtests show their caveats; predictions show their validated edge or say there is none.
