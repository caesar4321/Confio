import React, { useMemo, useRef, useState } from 'react';
import { LayoutChangeEvent, PanResponder, Pressable, StyleSheet, View } from 'react-native';
import Svg, { G, Line, Rect, Text as SvgText } from 'react-native-svg';

import { Text } from '../common/AppText';
import type { PerpOhlc } from '../../services/perps';
import { formatDecimal } from '../../utils/numberLocale';

const AXIS_W = 58;
const PRICE_H = 230;
const VOLUME_H = 40;
const TIME_H = 18;
const HOLD_MS = 220;
const MIN_COUNT = 20;
const MAX_COUNT = 150;
const DEFAULT_COUNT = 50;
const DOUBLE_TAP_MS = 300;
const clampCount = (n: number) => Math.min(MAX_COUNT, Math.max(MIN_COUNT, n));
const UP = '#16A34A';
const DOWN = '#DC2626';
const GRID = '#E5E7EB';

export interface ChartGuide {
  value: number;
  color: string;
  label: string;
}

/** Price decimals like formatPerpPrice, without the "$" (axis labels). */
export const axisPrice = (px: number): string => {
  const digits = Math.min(8, Math.max(2, 5 - (Math.floor(Math.log10(Math.abs(px) || 1)) + 1)));
  return formatDecimal(px, { decimals: digits });
};

/** How far back (in candles) a view anchored on `anchor` sits; 0 follows the latest. */
export const offsetOf = (candles: PerpOhlc[], anchor: number | null): number => {
  if (anchor == null || candles.length === 0) return 0;
  // The last candle at or before the anchor: new candles never move the view.
  let i = candles.length - 1;
  while (i > 0 && candles[i].time > anchor) i -= 1;
  return candles.length - 1 - i;
};

/** The candles on screen: `count` of them, ending `offset` candles before the latest. */
export const visibleWindow = (candles: PerpOhlc[], count: number, offset: number) => {
  const maxOffset = Math.max(0, candles.length - count);
  const clamped = Math.min(Math.max(0, Math.round(offset)), maxOffset);
  const end = candles.length - clamped;
  return { rows: candles.slice(Math.max(0, end - count), end), offset: clamped, maxOffset };
};

/** Low/high of the window (and of guides inside a 25% margin), padded. */
export const priceRange = (rows: PerpOhlc[], guides: number[]) => {
  let lo = Math.min(...rows.map((r) => r.low));
  let hi = Math.max(...rows.map((r) => r.high));
  const span = hi - lo || hi * 0.01 || 1;
  // A far-away liquidation price would flatten the candles: only nearby guides widen the range.
  guides.filter((g) => g >= lo - span * 0.25 && g <= hi + span * 0.25).forEach((g) => {
    lo = Math.min(lo, g);
    hi = Math.max(hi, g);
  });
  const pad = (hi - lo || span) * 0.06;
  return { lo: lo - pad, hi: hi + pad };
};

const timeLabel = (ms: number, daily: boolean) => {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  if (daily) return `${d.getDate()}/${pad(d.getMonth() + 1)}`;
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/**
 * Japanese candlesticks with volume, for timing an entry, handled like an
 * exchange app: drag sideways to go back in time, pinch to zoom, hold for a
 * crosshair (price at the finger, the candle's open/high/low/close) that stays
 * until a tap, double tap for the latest candles. Guides mark the entry and
 * liquidation prices.
 */
export function CandleChart({
  candles,
  daily,
  guides = [],
  emptyText,
  testID,
}: {
  candles: PerpOhlc[];
  daily: boolean;
  guides?: ChartGuide[];
  emptyText: string;
  testID?: string;
}) {
  const [width, setWidth] = useState(0);
  const [count, setCount] = useState(DEFAULT_COUNT); // candles across the plot
  // The time of the right-most candle while looking back; null follows the latest.
  const [anchor, setAnchor] = useState<number | null>(null);
  // The crosshair, kept as a candle time and a price so new candles never move it.
  const [cross, setCross] = useState<{ time: number; price: number } | null>(null);
  const plotW = Math.max(0, width - AXIS_W);
  const step = plotW / count;

  const view = visibleWindow(candles, Math.round(count), offsetOf(candles, anchor));
  const range = view.rows.length >= 2 ? priceRange(view.rows, guides.filter((g) => Number.isFinite(g.value) && g.value > 0).map((g) => g.value)) : null;
  const gesture = useRef({
    mode: 'idle' as 'idle' | 'pan' | 'cross' | 'pinch',
    timer: null as any, startX: 0, startY: 0, startAt: 0, originX: 0, originY: 0,
    startOffset: 0, baseDx: 0, pinchDist: 0, pinchCount: DEFAULT_COUNT, lastTap: 0,
    multi: false, // a second finger touched during this gesture: never a tap
    wandered: false, // moved past the tap distance at any point: never a tap
  });
  const state = useRef({ candles, rows: view.rows, offset: view.offset, maxOffset: view.maxOffset, step, plotW, range, cross });
  state.current = { candles, rows: view.rows, offset: view.offset, maxOffset: view.maxOffset, step, plotW, range, cross };

  const panTo = (offset: number) => {
    const { candles: all, maxOffset } = state.current;
    const o = Math.min(maxOffset, Math.max(0, Math.round(offset)));
    setAnchor(o === 0 ? null : all[all.length - 1 - o]?.time ?? null);
  };
  /** A point in the plot → the candle under it and the price at its height. */
  const pointAt = (pageX: number, pageY: number) => {
    const { rows, step: st, plotW: pw, range: rg } = state.current;
    const g = gesture.current;
    if (!rg || rows.length === 0 || st <= 0) return null;
    const x = Math.min(pw, Math.max(0, pageX - g.originX));
    const yy = Math.min(PRICE_H, Math.max(0, pageY - g.originY));
    const left = pw - rows.length * st;
    const row = rows[Math.min(rows.length - 1, Math.max(0, Math.floor((x - left) / st)))];
    return { time: row.time, price: rg.hi - (yy / PRICE_H) * (rg.hi - rg.lo) };
  };
  const distance = (touches: any[]) => Math.hypot(touches[0].pageX - touches[1].pageX, touches[0].pageY - touches[1].pageY);

  // The page keeps its vertical scroll: the chart takes the touch only for a
  // sideways drag (look back), a hold or a shown crosshair (crosshair), or two
  // fingers (zoom). Raw touch events start the hold timer without claiming.
  const touch = {
    onTouchStart: (e: any) => {
      const g = gesture.current;
      const n = e.nativeEvent;
      if ((n.touches?.length ?? 1) > 1) {
        // Another finger: a pinch starts over from here (no jump), and it is no tap.
        clearTimeout(g.timer);
        g.multi = true;
        g.pinchDist = 0;
        return;
      }
      g.multi = false;
      g.wandered = false;
      g.mode = state.current.cross ? 'cross' : 'idle';
      g.startX = n.pageX;
      g.startY = n.pageY;
      g.startAt = Date.now();
      // The plot's corner on screen (the svg fills this view).
      g.originX = n.pageX - n.locationX;
      g.originY = n.pageY - n.locationY;
      g.startOffset = state.current.offset;
      clearTimeout(g.timer);
      if (g.mode === 'idle') {
        g.timer = setTimeout(() => {
          g.mode = 'cross';
          const point = pointAt(g.startX, g.startY);
          if (point) setCross(point);
        }, HOLD_MS);
      }
    },
    onTouchMove: (e: any) => {
      const g = gesture.current;
      if (Math.hypot(e.nativeEvent.pageX - g.startX, e.nativeEvent.pageY - g.startY) > 6) {
        g.wandered = true;
        if (g.mode === 'idle') clearTimeout(g.timer); // moved before the hold: a scroll or a pan, never a crosshair
      }
    },
    onTouchEnd: (e: any) => {
      const g = gesture.current;
      clearTimeout(g.timer);
      if ((e.nativeEvent.touches?.length ?? 0) > 0) {
        g.pinchDist = 0; // a finger is still down: the next pinch move takes a new baseline
        return;
      }
      const tap = !g.multi && !g.wandered && Date.now() - g.startAt < HOLD_MS;
      if (tap) {
        if (state.current.cross) setCross(null); // a tap puts the crosshair away
        else if (Date.now() - g.lastTap < DOUBLE_TAP_MS) { setAnchor(null); setCount(DEFAULT_COUNT); }
        g.lastTap = Date.now();
      }
      g.mode = 'idle';
    },
    onTouchCancel: () => { clearTimeout(gesture.current.timer); gesture.current.mode = 'idle'; },
  };
  const responder = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => false,
    onMoveShouldSetPanResponder: (e, { dx, dy }) => (e.nativeEvent.touches?.length ?? 1) > 1
      || gesture.current.mode === 'cross'
      || (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.5),
    onPanResponderGrant: () => {
      const g = gesture.current;
      g.baseDx = 0;
      if (g.mode === 'idle') { clearTimeout(g.timer); g.mode = 'pan'; }
    },
    onPanResponderMove: (e, { dx }) => {
      const g = gesture.current;
      const touches = e.nativeEvent.touches ?? [];
      if (touches.length > 1) {
        g.multi = true;
        clearTimeout(g.timer);
        if (g.mode !== 'pinch' || g.pinchDist <= 0) {
          g.mode = 'pinch';
          g.pinchDist = distance(touches);
          g.pinchCount = state.current.step > 0 ? state.current.plotW / state.current.step : DEFAULT_COUNT;
        }
        const d = distance(touches);
        if (g.pinchDist > 0 && d > 0) setCount(clampCount((g.pinchCount * g.pinchDist) / d));
        return;
      }
      if (g.mode === 'pinch') {
        // Down to one finger: keep going as a pan from where the pinch left the chart.
        g.mode = state.current.cross ? 'cross' : 'pan';
        g.startOffset = state.current.offset;
        g.baseDx = dx;
        g.pinchDist = 0;
      }
      if (g.mode === 'cross') {
        const point = pointAt(e.nativeEvent.pageX, e.nativeEvent.pageY);
        if (point) setCross(point);
        return;
      }
      if (g.mode === 'pan' && state.current.step > 0) panTo(g.startOffset + (dx - g.baseDx) / state.current.step);
    },
    onPanResponderTerminationRequest: () => false,
    onPanResponderRelease: () => { clearTimeout(gesture.current.timer); },
    onPanResponderTerminate: () => { clearTimeout(gesture.current.timer); gesture.current.mode = 'idle'; },
  }), []);

  const rows = view.rows;
  if (rows.length < 2 || width === 0) {
    return (
      <View onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)}
        style={[styles.empty, { height: PRICE_H + VOLUME_H + TIME_H }]} testID={testID}>
        <Text style={styles.emptyText}>{rows.length < 2 ? emptyText : ''}</Text>
      </View>
    );
  }

  const shownGuides = guides.filter((g) => Number.isFinite(g.value) && g.value > 0);
  const { lo, hi } = range!;
  const y = (v: number) => PRICE_H - ((v - lo) / (hi - lo)) * PRICE_H;
  const maxVol = Math.max(...rows.map((r) => r.volume), 0) || 1;
  // Candles sit right-aligned, so a short history still ends at the latest.
  const left = plotW - rows.length * step;
  const xOf = (i: number) => left + i * step + step / 2;
  const body = Math.max(1, step * 0.66);
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * (i + 0.5)) / 5);
  const last = rows[rows.length - 1];
  const latest = view.offset === 0 ? last : null;
  const hoveredIdx = cross == null ? -1 : rows.findIndex((r) => r.time === cross.time);
  const hovered = hoveredIdx >= 0 ? rows[hoveredIdx] : null;
  const crossY = cross && cross.price >= lo && cross.price <= hi ? y(cross.price) : null;
  const shown = hovered ?? last;
  const shownUp = shown.close >= shown.open;
  const timeIdx = [0.15, 0.5, 0.85].map((f) => Math.min(rows.length - 1, Math.floor(rows.length * f)));

  return (
    <View testID={testID}>
      <View style={styles.ohlc} testID="perps-candle-ohlc">
        {([['A', shown.open], ['Máx', shown.high], ['Mín', shown.low], ['C', shown.close]] as [string, number][]).map(([k, v]) => (
          <Text key={k} style={styles.ohlcItem}>
            <Text style={styles.ohlcKey}>{k} </Text>
            <Text style={{ color: shownUp ? UP : DOWN }}>{axisPrice(v)}</Text>
          </Text>
        ))}
        <Text style={styles.ohlcTime}>{timeLabel(shown.time, daily)}</Text>
      </View>
      <View onLayout={(e: LayoutChangeEvent) => setWidth(e.nativeEvent.layout.width)} {...touch} {...responder.panHandlers}>
        <Svg width={width} height={PRICE_H + VOLUME_H + TIME_H}>
          {ticks.map((t) => (
            <G key={t}>
              <Line x1={0} x2={plotW} y1={y(t)} y2={y(t)} stroke={GRID} strokeWidth={1} />
              {/* The latest price's tag owns its spot on the axis. */}
              {(!latest || Math.abs(y(t) - y(latest.close)) > 14) && (
                <SvgText x={plotW + 6} y={y(t) + 4} fontSize={10} fill="#6B7280">{axisPrice(t)}</SvgText>
              )}
            </G>
          ))}
          {rows.map((r, i) => {
            const up = r.close >= r.open;
            const color = up ? UP : DOWN;
            const top = y(Math.max(r.open, r.close));
            const h = Math.max(1, Math.abs(y(r.open) - y(r.close)));
            const vh = (r.volume / maxVol) * (VOLUME_H - 4);
            return (
              <G key={r.time}>
                <Line x1={xOf(i)} x2={xOf(i)} y1={y(r.high)} y2={y(r.low)} stroke={color} strokeWidth={1} />
                <Rect x={xOf(i) - body / 2} y={top} width={body} height={h} fill={color} />
                <Rect x={xOf(i) - body / 2} y={PRICE_H + VOLUME_H - vh} width={body} height={vh} fill={color} opacity={0.35} />
              </G>
            );
          })}
          {shownGuides.filter((g) => g.value >= lo && g.value <= hi).map((g) => (
            <G key={g.label}>
              <Line x1={0} x2={plotW} y1={y(g.value)} y2={y(g.value)} stroke={g.color} strokeWidth={1.2} strokeDasharray="5,4" />
              <SvgText x={4} y={y(g.value) - 4} fontSize={10} fontWeight="bold" fill={g.color}>{g.label}</SvgText>
            </G>
          ))}
          {latest && (
            <G>
              <Line x1={0} x2={plotW} y1={y(latest.close)} y2={y(latest.close)}
                stroke={latest.close >= latest.open ? UP : DOWN} strokeWidth={1} strokeDasharray="2,3" />
              <Rect x={plotW + 1} y={y(latest.close) - 9} width={AXIS_W - 1} height={18} rx={4}
                fill={latest.close >= latest.open ? UP : DOWN} />
              <SvgText x={plotW + 5} y={y(latest.close) + 4} fontSize={10} fontWeight="bold" fill="#FFFFFF">
                {axisPrice(latest.close)}
              </SvgText>
            </G>
          )}
          {timeIdx.map((i) => (
            <SvgText key={`t${i}`} x={xOf(i)} y={PRICE_H + VOLUME_H + 13} fontSize={10} fill="#6B7280" textAnchor="middle">
              {timeLabel(rows[i].time, daily)}
            </SvgText>
          ))}
          {hovered && (
            <G testID="perps-candle-crosshair">
              <Line x1={xOf(hoveredIdx)} x2={xOf(hoveredIdx)} y1={0} y2={PRICE_H + VOLUME_H}
                stroke="#111827" strokeWidth={1} strokeDasharray="3,3" />
              {crossY != null && (
                <>
                  <Line x1={0} x2={plotW} y1={crossY} y2={crossY} stroke="#111827" strokeWidth={1} strokeDasharray="3,3" />
                  <Rect x={plotW + 1} y={crossY - 9} width={AXIS_W - 1} height={18} rx={4} fill="#111827" />
                  <SvgText x={plotW + 5} y={crossY + 4} fontSize={10} fontWeight="bold" fill="#FFFFFF">
                    {axisPrice(cross!.price)}
                  </SvgText>
                </>
              )}
              <Rect x={Math.min(plotW - 44, Math.max(0, xOf(hoveredIdx) - 22))} y={PRICE_H + VOLUME_H + 1} width={44} height={16}
                rx={4} fill="#111827" />
              <SvgText x={Math.min(plotW - 22, Math.max(22, xOf(hoveredIdx)))} y={PRICE_H + VOLUME_H + 13} fontSize={10}
                fontWeight="bold" fill="#FFFFFF" textAnchor="middle">
                {timeLabel(hovered.time, daily)}
              </SvgText>
            </G>
          )}
        </Svg>
      </View>
      <View style={styles.controls}>
        {view.offset > 0 ? (
          <Pressable onPress={() => setAnchor(null)} style={styles.control} accessibilityRole="button" testID="perps-candle-latest">
            <Text style={styles.controlText}>Ir al ahora ›</Text>
          </Pressable>
        ) : <View />}
        <View style={styles.zoom}>
          <Pressable onPress={() => setCount((n) => clampCount(n * 1.5))} disabled={count >= MAX_COUNT}
            style={styles.control} accessibilityRole="button" accessibilityLabel="Alejar" testID="perps-candle-zoom-out">
            <Text style={[styles.controlText, count >= MAX_COUNT && styles.controlOff]}>−</Text>
          </Pressable>
          <Pressable onPress={() => setCount((n) => clampCount(n / 1.5))} disabled={count <= MIN_COUNT}
            style={styles.control} accessibilityRole="button" accessibilityLabel="Acercar" testID="perps-candle-zoom-in">
            <Text style={[styles.controlText, count <= MIN_COUNT && styles.controlOff]}>+</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: { alignItems: 'center', justifyContent: 'center' },
  emptyText: { fontSize: 12, color: '#6B7280' },
  ohlc: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginBottom: 6 },
  ohlcItem: { fontSize: 12, fontWeight: '700' },
  ohlcKey: { color: '#6B7280', fontWeight: '600' },
  ohlcTime: { fontSize: 11, color: '#6B7280', marginLeft: 'auto' },
  controls: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 },
  zoom: { flexDirection: 'row', gap: 6 },
  control: { minHeight: 32, minWidth: 36, paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center',
    borderRadius: 8, backgroundColor: '#F3F4F6' },
  controlText: { fontSize: 14, fontWeight: '800', color: '#111827' },
  controlOff: { color: '#D1D5DB' },
});
