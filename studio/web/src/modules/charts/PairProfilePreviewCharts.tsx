import { useEffect, useRef, useState } from "react";
import {
  createChart,
  type BaselineData,
  type CandlestickData,
  type LineData,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PairProfilePreviewResponse } from "../../types";

type Props = {
  preview?: PairProfilePreviewResponse;
};

type PreviewIndicator = PairProfilePreviewResponse["series"]["indicators"][number];

type ZoneBand = {
  zoneId: number;
  top: PreviewIndicator;
  bottom: PreviewIndicator;
  color: string;
};

function toCandles(data: PairProfilePreviewResponse["series"] | undefined): CandlestickData[] {
  if (!data?.kline) return [];
  return data.kline.map((row) => ({
    time: row.time as UTCTimestamp,
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
  }));
}

function toLine(data: Array<{ time: number; value: number }> | undefined): LineData[] {
  if (!data) return [];
  return data.map((row) => ({ time: row.time as UTCTimestamp, value: row.value }));
}

function toBaseline(data: Array<{ time: number; value: number }> | undefined): BaselineData[] {
  if (!data) return [];
  return data.map((row) => ({ time: row.time as UTCTimestamp, value: row.value }));
}

function withAlpha(color: string | undefined, alpha: number): string {
  if (!color) return `rgba(96, 165, 250, ${alpha})`;
  const raw = color.trim();

  if (raw.startsWith("#")) {
    let hex = raw.slice(1);
    if (hex.length === 3) {
      hex = hex
        .split("")
        .map((ch) => ch + ch)
        .join("");
    }
    if (hex.length >= 6) {
      const r = Number.parseInt(hex.slice(0, 2), 16);
      const g = Number.parseInt(hex.slice(2, 4), 16);
      const b = Number.parseInt(hex.slice(4, 6), 16);
      return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
  }

  const rgba = raw.match(/^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*[\d.]+\s*\)$/i);
  if (rgba) {
    return `rgba(${rgba[1]}, ${rgba[2]}, ${rgba[3]}, ${alpha})`;
  }

  const rgb = raw.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i);
  if (rgb) {
    return `rgba(${rgb[1]}, ${rgb[2]}, ${rgb[3]}, ${alpha})`;
  }

  return `rgba(96, 165, 250, ${alpha})`;
}

function zoneTag(name: string): { zoneId: number; side: "TOP" | "BOTTOM" } | null {
  const matched = name.trim().toUpperCase().match(/^ZONE([1-4])_(TOP|BOTTOM)$/);
  if (!matched) return null;
  return {
    zoneId: Number.parseInt(matched[1], 10),
    side: matched[2] as "TOP" | "BOTTOM",
  };
}

function splitIndicators(indicators: PreviewIndicator[]): { zoneBands: ZoneBand[]; plainIndicators: PreviewIndicator[] } {
  const zoneTop = new Map<number, PreviewIndicator>();
  const zoneBottom = new Map<number, PreviewIndicator>();
  const zoneNames = new Set<string>();

  for (const indicator of indicators) {
    const tagged = zoneTag(indicator.name);
    if (!tagged) continue;
    zoneNames.add(indicator.name);
    if (tagged.side === "TOP") {
      zoneTop.set(tagged.zoneId, indicator);
    } else {
      zoneBottom.set(tagged.zoneId, indicator);
    }
  }

  const zoneBands: ZoneBand[] = [];
  for (let zoneId = 1; zoneId <= 4; zoneId += 1) {
    const top = zoneTop.get(zoneId);
    const bottom = zoneBottom.get(zoneId);
    if (!top || !bottom) continue;
    zoneBands.push({
      zoneId,
      top,
      bottom,
      color: top.color ?? bottom.color ?? "#60a5fa",
    });
    zoneNames.delete(top.name);
    zoneNames.delete(bottom.name);
  }

  const plainIndicators = indicators.filter((indicator) => !zoneNames.has(indicator.name) && zoneTag(indicator.name) === null);
  return { zoneBands, plainIndicators };
}

export function PairProfilePreviewCharts({ preview }: Props) {
  const [showIndicators, setShowIndicators] = useState(true);
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!preview?.series || !chartRef.current) return;

    const width = Math.max(320, chartRef.current.clientWidth || 960);
    const chart = createChart(chartRef.current, {
      width,
      height: 360,
      layout: { background: { color: "#0b1220" }, textColor: "#cbd5e1" },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
    });
    const klineSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      borderUpColor: "#22c55e",
      wickUpColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      wickDownColor: "#ef4444",
    });
    klineSeries.setData(toCandles(preview.series));

    const markers = (preview.series.markers ?? []).map((marker) => ({
      ...marker,
      time: marker.time as UTCTimestamp,
    })) as SeriesMarker<UTCTimestamp>[];
    if (markers.length > 0) {
      klineSeries.setMarkers(markers);
    }

    const allIndicators = showIndicators ? preview.series.indicators ?? [] : [];
    const { zoneBands, plainIndicators } = splitIndicators(allIndicators);

    for (const zone of zoneBands.sort((a, b) => a.zoneId - b.zoneId)) {
      const topData = toBaseline(zone.top.points);
      const bottomData = toLine(zone.bottom.points);
      if (topData.length < 2 || bottomData.length < 2) continue;

      const bottomPrice = bottomData[0]?.value;
      if (typeof bottomPrice === "number" && Number.isFinite(bottomPrice)) {
        const baselineSeries = chart.addBaselineSeries({
          baseValue: { type: "price", price: bottomPrice },
          topLineColor: withAlpha(zone.color, 0),
          topFillColor1: withAlpha(zone.color, 0.2),
          topFillColor2: withAlpha(zone.color, 0.06),
          bottomLineColor: withAlpha(zone.color, 0),
          bottomFillColor1: withAlpha(zone.color, 0),
          bottomFillColor2: withAlpha(zone.color, 0),
          lineWidth: 1,
          lastValueVisible: false,
          priceLineVisible: false,
          crosshairMarkerVisible: false,
        });
        baselineSeries.setData(topData);
      }

      const topLineSeries = chart.addLineSeries({
        color: withAlpha(zone.color, 0.92),
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      topLineSeries.setData(toLine(zone.top.points));

      const bottomLineSeries = chart.addLineSeries({
        color: withAlpha(zone.color, 0.92),
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      bottomLineSeries.setData(bottomData);
    }

    for (const indicator of plainIndicators) {
      const lineSeries = chart.addLineSeries({
        color: indicator.color ?? "#22d3ee",
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      lineSeries.setData(toLine(indicator.points));
    }

    return () => {
      chart.remove();
    };
  }, [preview, showIndicators]);

  const indicators = preview?.series?.indicators ?? [];
  const hasIndicators = indicators.length > 0;

  return (
    <div className="charts-panel pair-preview-charts">
      <div className="chart-block">
        <div className="chart-title-row">
          <div className="chart-title">交易对指标与区域图</div>
          <button type="button" className="chart-toggle-btn" onClick={() => setShowIndicators((prev) => !prev)}>
            {showIndicators ? "隐藏指标" : "显示指标"}
          </button>
        </div>
        {showIndicators && hasIndicators ? (
          <div className="indicator-legend">
            {indicators.map((item) => (
              <span key={item.name} className="indicator-chip">
                <i style={{ backgroundColor: item.color ?? "#22d3ee" }} />
                {item.name}
              </span>
            ))}
          </div>
        ) : null}
        {showIndicators && !hasIndicators ? <div className="chart-hint">暂无可显示指标线。</div> : null}
        <div ref={chartRef} />
      </div>
    </div>
  );
}
