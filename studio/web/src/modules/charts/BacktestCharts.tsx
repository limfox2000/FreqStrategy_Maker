import { useEffect, useRef, useState } from "react";
import {
  createChart,
  type CandlestickData,
  type LineData,
  type SeriesMarker,
  type UTCTimestamp,
} from "lightweight-charts";
import type { BacktestResult } from "../../types";

type Props = {
  result?: BacktestResult;
};

function toCandles(data: BacktestResult["series"]): CandlestickData[] {
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

export function BacktestCharts({ result }: Props) {
  const [showIndicators, setShowIndicators] = useState(true);
  const klineRef = useRef<HTMLDivElement>(null);
  const equityRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!result?.series || !klineRef.current || !equityRef.current) return;

    const klineWidth = Math.max(320, klineRef.current.clientWidth || 720);
    const equityWidth = Math.max(320, equityRef.current.clientWidth || 720);

    const common = {
      layout: { background: { color: "#0b1220" }, textColor: "#cbd5e1" },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
    };

    const klineChart = createChart(klineRef.current, { ...common, width: klineWidth, height: 240 });
    const klineSeries = klineChart.addCandlestickSeries({
      upColor: "#22c55e",
      borderUpColor: "#22c55e",
      wickUpColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      wickDownColor: "#ef4444",
    });
    klineSeries.setData(toCandles(result.series));
    klineSeries.setMarkers(
      (result.series.markers ?? []).map((marker) => ({
        ...marker,
        time: marker.time as UTCTimestamp,
      })) as SeriesMarker<UTCTimestamp>[],
    );

    const indicatorLines = showIndicators ? result.series.indicators ?? [] : [];
    for (const indicator of indicatorLines) {
      const indicatorSeries = klineChart.addLineSeries({
        color: indicator.color ?? "#22d3ee",
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      indicatorSeries.setData(toLine(indicator.points));
    }

    const equityChart = createChart(equityRef.current, {
      ...common,
      width: equityWidth,
      height: 180,
      handleScroll: false,
      handleScale: false,
      timeScale: { visible: false },
    });
    const equitySeries = equityChart.addLineSeries({ color: "#38bdf8", lineWidth: 2 });
    equitySeries.setData(toLine(result.series.equity));

    let syncing = false;
    const onKlineRangeChange = (range: { from: number; to: number } | null) => {
      if (!range || syncing) return;
      syncing = true;
      equityChart.timeScale().setVisibleLogicalRange(range);
      syncing = false;
    };
    klineChart.timeScale().subscribeVisibleLogicalRangeChange(onKlineRangeChange);
    const initialRange = klineChart.timeScale().getVisibleLogicalRange();
    if (initialRange) {
      equityChart.timeScale().setVisibleLogicalRange(initialRange);
    }

    return () => {
      klineChart.timeScale().unsubscribeVisibleLogicalRangeChange(onKlineRangeChange);
      klineChart.remove();
      equityChart.remove();
    };
  }, [result, showIndicators]);

  const indicators = result?.series?.indicators ?? [];
  const hasIndicators = indicators.length > 0;

  return (
    <div className="charts-panel">
      <div className="chart-block">
        <div className="chart-title-row">
          <div className="chart-title">K线、信号与技术指标</div>
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
        {showIndicators && !hasIndicators ? <div className="chart-hint">未检测到可叠加到 K 线价格轴的指标线。</div> : null}
        <div ref={klineRef} />
      </div>
      <div className="chart-block">
        <div className="chart-title">收益曲线（跟随 K 线视窗）</div>
        <div ref={equityRef} />
      </div>
    </div>
  );
}
