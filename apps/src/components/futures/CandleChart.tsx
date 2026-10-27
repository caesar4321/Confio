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
const ZOOMS = [30, 50, 80, 120];
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
 * Japanese candlesticks with volume, for timing an entry: drag sideways to
 * go back in time, hold and drag for a crosshair with the candle's open,
 * high, low and close. Guides mark the entry and liquidation prices.
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
  const [zoom, setZoom] = useState(1);
  // The time of the right-most candle while looking back; null follows the latest.
  const [anchor, setAnchor] = useState<number | null>(null);
  const [cross, setCross] = useState<number | null>(null); // x within the plot
  const count = ZOOMS[zoom];
  const plotW = Math.max(0, width - AXIS_W);
  const step = plotW / count;

  const view = visibleWindow(candles, count, offsetOf(candles, anchor));
  const gesture = useRef({ startOffset: 0, mode: 'idle' as 'idle' | 'pan' | 'cross', timer: null as any, startX: 0, startY: 0 });
  const state = useRef({ candles, offset: view.offset, maxOffset: view.maxOffset, step });
  state.current = { candles, offset: view.offset, maxOffset: view.maxOffset, step };

  const panTo = (offset: number) => {
    const { candles: all, maxOffset } = state.current;
    const o = Math.min(maxOffset, Math.max(0, Math.round(offset)));
    setAnchor(o === 0 ? null : all[all.length - 1 - o]?.time ?? null);
  };
  const endGesture = () => {
    const g = gesture.current;
    clearTimeout(g.timer);
    g.mode = 'idle';
    setCross(null);
  };

  // The page keeps its vertical scroll: the chart takes the touch only after a
  // sideways drag (look back) or a hold (crosshair). Raw touch events start
  // the hold timer without claiming anything.
  const touch = {
    onTouchStart: (e: any) => {
      const g = gesture.current;
      g.mode = 'idle';
      g.startX = e.nativeEvent.pageX;
      g.startY = e.nativeEvent.pageY;
      g.startOffset = state.current.offset;
      const x = e.nativeEvent.locationX;
      clearTimeout(g.timer);
      g.timer = setTimeout(() => { g.mode = 'cross'; setCross(x); }, HOLD_MS);
    },
    onTouchMove: (e: any) => {
      const g = gesture.current;
      if (g.mode === 'idle' && Math.hypot(e.nativeEvent.pageX - g.startX, e.nativeEvent.pageY - g.startY) > 6) {
        clearTimeout(g.timer); // moved before the hold: a scroll or a pan, never a crosshair
      }
    },
    onTouchEnd: endGesture,
    onTouchCancel: endGesture,
  };
  const responder = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => false,
    onMoveShouldSetPanResponder: (_e, { dx, dy }) => gesture.current.mode === 'cross'
      || (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.5),
    onPanResponderGrant: () => {
      const g = gesture.current;
      if (g.mode !== 'cross') { clearTimeout(g.timer); g.mode = 'pan'; }
    },
    onPanResponderMove: (e, { dx }) => {
      const g = gesture.current;
      if (g.mode === 'cross') { setCross(e.nativeEvent.locationX); return; }
      if (state.current.step > 0) panTo(g.startOffset + dx / state.current.step);
    },
    onPanResponderTerminationRequest: () => false,
    onPanResponderRelease: endGesture,
    onPanResponderTerminate: endGesture,
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
  const { lo, hi } = priceRange(rows, shownGuides.map((g) => g.value));
  const y = (v: number) => PRICE_H - ((v - lo) / (hi - lo)) * PRICE_H;
  const maxVol = Math.max(...rows.map((r) => r.volume), 0) || 1;
  // Candles sit right-aligned, so a short history still ends at the latest.
  const left = plotW - rows.length * step;
  const xOf = (i: number) => left + i * step + step / 2;
  const body = Math.max(1, step * 0.66);
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * (i + 0.5)) / 5);
  const last = rows[rows.length - 1];
  const latest = view.offset === 0 ? last : null;
  const hovered = cross == null ? null
    : rows[Math.min(rows.length - 1, Math.max(0, Math.floor((cross - left) / step)))] ?? null;
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
          {hovered && cross != null && (
            <G>
              <Line x1={xOf(rows.indexOf(hovered))} x2={xOf(rows.indexOf(hovered))} y1={0} y2={PRICE_H + VOLUME_H}
                stroke="#111827" strokeWidth={1} strokeDasharray="3,3" />
            </G>
          )}
          {timeIdx.map((i) => (
            <SvgText key={`t${i}`} x={xOf(i)} y={PRICE_H + VOLUME_H + 13} fontSize={10} fill="#6B7280" textAnchor="middle">
              {timeLabel(rows[i].time, daily)}
            </SvgText>
          ))}
        </Svg>
      </View>
      <View style={styles.controls}>
        {view.offset > 0 ? (
          <Pressable onPress={() => setAnchor(null)} style={styles.control} accessibilityRole="button" testID="perps-candle-latest">
            <Text style={styles.controlText}>Ir al ahora ›</Text>
          </Pressable>
        ) : <View />}
        <View style={styles.zoom}>
          <Pressable onPress={() => setZoom((z) => Math.min(ZOOMS.length - 1, z + 1))} disabled={zoom === ZOOMS.length - 1}
            style={styles.control} accessibilityRole="button" accessibilityLabel="Alejar" testID="perps-candle-zoom-out">
            <Text style={[styles.controlText, zoom === ZOOMS.length - 1 && styles.controlOff]}>−</Text>
          </Pressable>
          <Pressable onPress={() => setZoom((z) => Math.max(0, z - 1))} disabled={zoom === 0}
            style={styles.control} accessibilityRole="button" accessibilityLabel="Acercar" testID="perps-candle-zoom-in">
            <Text style={[styles.controlText, zoom === 0 && styles.controlOff]}>+</Text>
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
