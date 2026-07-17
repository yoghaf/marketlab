"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp
} from "lightweight-charts";

import { SignalChartPayload, fmtPrice } from "@/lib/api";
import { labelFor } from "@/lib/labels";

type HoverCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

export function SignalPriceChart({ chartData }: { chartData?: SignalChartPayload }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<HoverCandle | null>(null);

  const normalized = useMemo(() => normalizeChartData(chartData), [chartData]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !normalized) return;

    const priceFormat = chartPriceFormat([
      normalized.entry,
      normalized.stopLoss,
      normalized.takeProfit,
      ...normalized.structureZones.flatMap((zone) => [zone.lower, zone.upper]),
      ...normalized.candles.flatMap((candle) => [candle.high, candle.low])
    ]);
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#475569",
        attributionLogo: false
      },
      grid: {
        vertLines: { color: "#eef2f7" },
        horzLines: { color: "#eef2f7" }
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: "#cbd5e1",
        scaleMargins: { top: 0.1, bottom: 0.1 }
      },
      timeScale: {
        borderColor: "#cbd5e1",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        tickMarkFormatter: (time: Time) => formatWibTime(Number(time))
      },
      localization: {
        timeFormatter: (time: Time) => formatWibDateTime(Number(time)),
        priceFormatter: (price: number) => formatChartPrice(price, priceFormat.precision)
      },
      handleScale: true,
      handleScroll: true
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#059669",
      downColor: "#dc2626",
      borderVisible: false,
      wickUpColor: "#059669",
      wickDownColor: "#dc2626",
      priceFormat: {
        type: "price",
        precision: priceFormat.precision,
        minMove: priceFormat.minMove
      },
      lastValueVisible: true,
      priceLineVisible: true
    });
    candleSeries.setData(normalized.candles);

    const boundsOptions = {
      color: "rgba(15, 23, 42, 0)",
      lineWidth: 1 as const,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false
    };
    const boundsTimes = Array.from(new Set([
      normalized.candles[0].time,
      normalized.candles[normalized.candles.length - 1].time
    ]));
    const lowerBoundsSeries = chart.addSeries(LineSeries, boundsOptions);
    lowerBoundsSeries.setData(boundsTimes.map((time) => ({
      time,
      value: Math.min(normalized.entry, normalized.stopLoss, normalized.takeProfit)
    })));
    const upperBoundsSeries = chart.addSeries(LineSeries, boundsOptions);
    upperBoundsSeries.setData(boundsTimes.map((time) => ({
      time,
      value: Math.max(normalized.entry, normalized.stopLoss, normalized.takeProfit)
    })));

    candleSeries.createPriceLine({
      price: normalized.entry,
      color: "#2563eb",
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: "ENTRY"
    });
    candleSeries.createPriceLine({
      price: normalized.stopLoss,
      color: "#dc2626",
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: "SL"
    });
    candleSeries.createPriceLine({
      price: normalized.takeProfit,
      color: "#059669",
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: "TP"
    });

    const markers: SeriesMarker<UTCTimestamp>[] = [
      {
        time: normalized.signalMarkerTime,
        position: normalized.direction === "LONG" ? "belowBar" : "aboveBar",
        color: "#2563eb",
        shape: normalized.direction === "LONG" ? "arrowUp" : "arrowDown",
        text: "ENTRY"
      }
    ];
    if (normalized.resultMarkerTime) {
      markers.push({
        time: normalized.resultMarkerTime,
        position: normalized.direction === "LONG" ? "aboveBar" : "belowBar",
        color: resultColor(normalized.resultStatus),
        shape: "circle",
        text: resultMarkerText(normalized.resultStatus)
      });
    }
    createSeriesMarkers(candleSeries, markers);

    const rewardBox = zoneElement("rgba(5, 150, 105, 0.10)", "rgba(5, 150, 105, 0.35)", "TARGET ZONE");
    const riskBox = zoneElement("rgba(220, 38, 38, 0.09)", "rgba(220, 38, 38, 0.30)", "RISK ZONE");
    const structureBoxes = normalized.structureZones.map((zone) => {
      const colors = structureZoneColors(zone.originRole);
      const element = zoneElement(
        colors.background,
        colors.border,
        `${zone.originRole.replaceAll("_", " ")} | ${zone.touchCount} touches`
      );
      container.append(element);
      return { element, zone };
    });
    container.append(rewardBox, riskBox);

    const updateZones = () => {
      positionZone(
        rewardBox,
        chart.timeScale().timeToCoordinate(normalized.signalMarkerTime),
        chart.timeScale().timeToCoordinate(normalized.boxEndMarkerTime),
        candleSeries.priceToCoordinate(normalized.entry),
        candleSeries.priceToCoordinate(normalized.takeProfit)
      );
      positionZone(
        riskBox,
        chart.timeScale().timeToCoordinate(normalized.signalMarkerTime),
        chart.timeScale().timeToCoordinate(normalized.boxEndMarkerTime),
        candleSeries.priceToCoordinate(normalized.entry),
        candleSeries.priceToCoordinate(normalized.stopLoss)
      );
      for (const { element, zone } of structureBoxes) {
        positionZone(
          element,
          chart.timeScale().timeToCoordinate(zone.startTime),
          chart.timeScale().timeToCoordinate(zone.endTime),
          candleSeries.priceToCoordinate(zone.lower),
          candleSeries.priceToCoordinate(zone.upper)
        );
      }
    };

    chart.subscribeCrosshairMove((param) => {
      const value = param.seriesData.get(candleSeries) as CandlestickData<UTCTimestamp> | undefined;
      if (!param.time || !value) {
        setHover(null);
        return;
      }
      setHover({
        time: formatWibDateTime(Number(param.time)),
        open: value.open,
        high: value.high,
        low: value.low,
        close: value.close
      });
    });
    chart.timeScale().subscribeVisibleTimeRangeChange(updateZones);
    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
      requestAnimationFrame(updateZones);
    });
    resizeObserver.observe(container);
    requestAnimationFrame(updateZones);

    return () => {
      resizeObserver.disconnect();
      chart.timeScale().unsubscribeVisibleTimeRangeChange(updateZones);
      rewardBox.remove();
      riskBox.remove();
      for (const { element } of structureBoxes) element.remove();
      chart.remove();
    };
  }, [normalized]);

  if (!chartData || !normalized) {
    return (
      <div className="flex min-h-72 items-center justify-center border-t border-line bg-field/30 px-4 text-center text-sm text-slate-500">
        Candle futures untuk chart signal ini belum tersedia.
      </div>
    );
  }

  const activeHover = hover || normalized.latest;
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <LegendDot color="bg-blue-600" label={`Entry ${fmtPrice(normalized.entry)}`} />
          <LegendDot color="bg-red-600" label={`SL ${fmtPrice(normalized.stopLoss)}`} />
          <LegendDot color="bg-emerald-600" label={`TP ${fmtPrice(normalized.takeProfit)}`} />
          <span className="rounded border border-line bg-field/50 px-2 py-1 font-semibold text-slate-600">
            {normalized.candles.length} candle futures
          </span>
          {normalized.structureZones.length ? (
            <span className="rounded border border-amber-500 bg-amber-50 px-2 py-1 font-semibold text-amber-800">
              {normalized.structureZones.length} structure zones
            </span>
          ) : null}
        </div>
        <div className="text-right text-slate-500">
          <span className="font-semibold text-ink">{labelFor(normalized.resultStatus)}</span>
          <span className="mx-2">|</span>
          {chartData.display_interval.replaceAll("_", " ")}
        </div>
      </div>

      <div className="relative">
        <div ref={containerRef} className="h-[28rem] w-full overflow-hidden sm:h-[32rem]" />
        {activeHover ? (
          <div className="pointer-events-none absolute left-3 top-3 z-20 rounded border border-line bg-white/95 px-3 py-2 text-xs shadow-sm backdrop-blur">
            <div className="mb-1 font-semibold text-ink">{activeHover.time}</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-slate-600 sm:grid-cols-4">
              <span>O <strong className="text-ink">{fmtPrice(activeHover.open)}</strong></span>
              <span>H <strong className="text-ink">{fmtPrice(activeHover.high)}</strong></span>
              <span>L <strong className="text-ink">{fmtPrice(activeHover.low)}</strong></span>
              <span>C <strong className="text-ink">{fmtPrice(activeHover.close)}</strong></span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2 text-[0.68rem] text-slate-500">
        <span>Zona berwarna adalah referensi risk/reward dari waktu signal sampai result/latest candle.</span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" className="font-semibold hover:text-ink">
          Charting by TradingView Lightweight Charts™
        </a>
      </div>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-semibold text-slate-700">
      <span className={`h-2.5 w-2.5 ${color}`} />
      {label}
    </span>
  );
}

function normalizeChartData(chartData?: SignalChartPayload) {
  if (!chartData?.candles?.length) return null;
  const candles = chartData.candles
    .map((candle) => ({
      time: toTimestamp(candle.open_time),
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close)
    }))
    .filter((candle) => [candle.open, candle.high, candle.low, candle.close].every(Number.isFinite))
    .sort((left, right) => Number(left.time) - Number(right.time));
  if (!candles.length) return null;

  const entry = Number(chartData.entry);
  const stopLoss = Number(chartData.stop_loss);
  const takeProfit = Number(chartData.take_profit);
  if (![entry, stopLoss, takeProfit].every(Number.isFinite)) return null;

  const signalMarkerTime = nearestCandleTime(candles, chartData.signal_time);
  const resultMarkerTime = chartData.result_time ? candleTimeAtOrBefore(candles, chartData.result_time) : null;
  const boxEndMarkerTime = candleTimeAtOrBefore(candles, chartData.box_end_time);
  const latestCandle = candles[candles.length - 1];
  const structureZones = (chartData.structure_zones || [])
    .map((zone) => ({
      lower: Number(zone.lower),
      upper: Number(zone.upper),
      originRole: zone.origin_role,
      touchCount: Number(zone.touch_count),
      startTime: candleTimeAtOrAfter(candles, zone.start_time),
      endTime: candleTimeAtOrBefore(candles, zone.end_time)
    }))
    .filter((zone) => Number.isFinite(zone.lower) && Number.isFinite(zone.upper) && zone.lower <= zone.upper);
  return {
    candles,
    entry,
    stopLoss,
    takeProfit,
    direction: chartData.direction.toUpperCase(),
    resultStatus: chartData.result_status,
    signalMarkerTime,
    resultMarkerTime,
    boxEndMarkerTime,
    structureZones,
    latest: {
      time: formatWibDateTime(Number(latestCandle.time)),
      open: latestCandle.open,
      high: latestCandle.high,
      low: latestCandle.low,
      close: latestCandle.close
    }
  };
}

function nearestCandleTime(candles: CandlestickData<UTCTimestamp>[], value: string): UTCTimestamp {
  const target = Number(toTimestamp(value));
  return candles.reduce((nearest, candle) =>
    Math.abs(Number(candle.time) - target) < Math.abs(Number(nearest.time) - target) ? candle : nearest
  ).time;
}

function candleTimeAtOrBefore(candles: CandlestickData<UTCTimestamp>[], value: string): UTCTimestamp {
  const target = Number(toTimestamp(value));
  let selected = candles[0].time;
  for (const candle of candles) {
    if (Number(candle.time) > target) break;
    selected = candle.time;
  }
  return selected;
}

function candleTimeAtOrAfter(candles: CandlestickData<UTCTimestamp>[], value: string): UTCTimestamp {
  const target = Number(toTimestamp(value));
  for (const candle of candles) {
    if (Number(candle.time) >= target) return candle.time;
  }
  return candles[candles.length - 1].time;
}

function toTimestamp(value: string): UTCTimestamp {
  return Math.floor(parseUtcDate(value).getTime() / 1000) as UTCTimestamp;
}

function parseUtcDate(value: string): Date {
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const hasTimeZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  return new Date(hasTimeZone ? normalized : `${normalized}Z`);
}

function chartPriceFormat(values: number[]) {
  const positive = values.filter((value) => Number.isFinite(value) && value > 0);
  const min = positive.length ? Math.min(...positive) : 1;
  let precision = 2;
  if (min < 0.0001) precision = 8;
  else if (min < 0.01) precision = 6;
  else if (min < 1) precision = 5;
  else if (min < 100) precision = 4;
  return { precision, minMove: 10 ** -precision };
}

function formatChartPrice(value: number, precision: number): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: Math.min(precision, 2),
    maximumFractionDigits: precision
  }).format(value);
}

function formatWibTime(value: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Jakarta"
  }).format(new Date(value * 1000));
}

function formatWibDateTime(value: number): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Jakarta"
  }).format(new Date(value * 1000));
}

function resultColor(status: string): string {
  if (status === "TP_HIT") return "#059669";
  if (status === "SL_HIT") return "#dc2626";
  return "#d97706";
}

function resultMarkerText(status: string): string {
  if (status === "TP_HIT") return "TP HIT";
  if (status === "SL_HIT") return "SL HIT";
  if (status === "BOTH_HIT_SAME_CANDLE") return "TP/SL SAME CANDLE";
  if (status === "OPEN") return "CURRENT";
  if (status === "STALE_FORWARD_DATA") return "LAST KNOWN";
  return "RESULT";
}

function structureZoneColors(role: string): { background: string; border: string } {
  if (role === "SUPPORT_ORIGIN") {
    return { background: "rgba(14, 116, 144, 0.08)", border: "rgba(14, 116, 144, 0.38)" };
  }
  if (role === "RESISTANCE_ORIGIN") {
    return { background: "rgba(217, 119, 6, 0.08)", border: "rgba(217, 119, 6, 0.40)" };
  }
  return { background: "rgba(124, 58, 237, 0.07)", border: "rgba(124, 58, 237, 0.34)" };
}

function zoneElement(background: string, border: string, label: string): HTMLDivElement {
  const element = document.createElement("div");
  Object.assign(element.style, {
    position: "absolute",
    display: "none",
    pointerEvents: "none",
    zIndex: "10",
    background,
    border: `1px solid ${border}`,
    color: border,
    fontSize: "10px",
    fontWeight: "700",
    padding: "3px 5px",
    overflow: "hidden"
  });
  element.textContent = label;
  return element;
}

function positionZone(
  element: HTMLDivElement,
  startX: number | null,
  endX: number | null,
  firstY: number | null,
  secondY: number | null
) {
  if (startX === null || endX === null || firstY === null || secondY === null) {
    element.style.display = "none";
    return;
  }
  const left = Math.min(startX, endX);
  const top = Math.min(firstY, secondY);
  element.style.display = "block";
  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
  element.style.width = `${Math.max(12, Math.abs(endX - startX))}px`;
  element.style.height = `${Math.max(8, Math.abs(secondY - firstY))}px`;
}
