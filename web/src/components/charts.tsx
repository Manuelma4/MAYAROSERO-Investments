import { useEffect, useRef } from "react";
import {
  CandlestickSeries, ColorType, HistogramSeries, LineSeries, createChart, createSeriesMarkers,
  type IChartApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { cssVar as css, useTheme } from "../lib/theme";
import type { Candle, Point } from "../lib/types";

function baseChart(el: HTMLElement): IChartApi {
  return createChart(el, {
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--text-2"), fontFamily: "inherit", attributionLogo: false },
    grid: { vertLines: { color: css("--grid") }, horzLines: { color: css("--grid") } },
    rightPriceScale: { borderColor: css("--line") },
    timeScale: { borderColor: css("--line"), timeVisible: true },
    crosshair: { mode: 0 },
  });
}

const t = (s: number) => s as UTCTimestamp;

export const SERIES = { ema20: "#4F9DFF", ema50: "#F5A524", ema200: "#B57BFF", band: "#6B7489" };
export const upColor = () => css("--up");
export const downColor = () => css("--down");

export interface Overlay { data: Point[]; color: string; width?: number; dashed?: boolean; title?: string }
export interface Marker { time: number; position: "aboveBar" | "belowBar"; color: string; shape: "arrowUp" | "arrowDown" | "circle"; text?: string }

export function PriceChart({ candles, overlays = [], markers = [], height = 460 }:
  { candles: Candle[]; overlays?: Overlay[]; markers?: Marker[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();

  useEffect(() => {
    if (!ref.current) return;
    const chart = baseChart(ref.current);
    const up = css("--up"), down = css("--down");
    const series = chart.addSeries(CandlestickSeries, {
      upColor: up, downColor: down, wickUpColor: up, wickDownColor: down, borderVisible: false,
    });
    series.setData(candles.map((c) => ({ time: t(c.time), open: c.open, high: c.high, low: c.low, close: c.close })));

    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(candles.map((c) => ({ time: t(c.time), value: c.volume, color: c.close >= c.open ? css("--up-soft") : css("--down-soft") })));

    for (const o of overlays) {
      const s = chart.addSeries(LineSeries, {
        color: o.color, lineWidth: (o.width ?? 1) as 1, lineStyle: o.dashed ? 2 : 0,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: o.title ?? "",
      });
      s.setData(o.data.map((p) => ({ time: t(p.time), value: p.value })));
    }
    const sorted = [...markers].sort((a, b) => a.time - b.time);
    createSeriesMarkers(series, sorted.map((m) => ({ ...m, time: t(m.time) })) as SeriesMarker<Time>[]);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles, overlays, markers, resolved]);

  return <div className="chart" ref={ref} style={{ height }} />;
}

export function LinesChart({ series, height = 260 }: { series: Overlay[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const chart = baseChart(ref.current);
    for (const o of series) {
      const s = chart.addSeries(LineSeries, { color: o.color, lineWidth: (o.width ?? 2) as 2, lineStyle: o.dashed ? 2 : 0, priceLineVisible: false, title: o.title ?? "" });
      s.setData(o.data.map((p) => ({ time: t(p.time), value: p.value })));
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, resolved]);
  return <div className="chart" ref={ref} style={{ height }} />;
}
