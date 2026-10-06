// Tu mes intro (founder 2026-10-05): a short, joyful full-screen moment every
// time Tu mes opens — not a celebration of the result, just delight.
//
//   0 ms     the screen floods mint; bubbles start flowing (money in drifts
//            up in mint/white, money out arcs down in sky blue)
//   120 ms   the month name springs in, big
//   420 ms   "Entró" pops in, then "Salió", while the result counts up
//   1600 ms  the takeover lifts away into the screen underneath
//
// Tap anywhere to skip. Never shown with Reduce Motion or a screen reader
// (the numbers are on the screen itself). Masked balance → amounts are ••••.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import type { MonthSummary } from '../../apollo/monthSummary';
import { capitalize, formatUsd, MASK, monthName } from '../../utils/monthSummary';
import { resultText } from './SummaryCard';

export const INTRO_HOLD_MS = 1600;
export const INTRO_EXIT_MS = 380;
const BUBBLES = 18;

/** Deterministic pseudo-random (same layout every time, stable in tests). */
function rand(seed: number) {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

type Bubble = { x: number; size: number; delay: number; drift: number; up: boolean; color: string; opacity: number };

function makeBubbles(width: number): Bubble[] {
  const palette = [colors.white, colors.flowIn.chip, colors.primaryMuted, colors.flowOut.bar, colors.white];
  return Array.from({ length: BUBBLES }, (_, i) => {
    const up = i % 4 !== 3;                       // ~3 of 4 flow in (up), the rest flow out (down)
    return {
      x: rand(i + 1) * width,
      size: 10 + Math.round(rand(i + 7) * 34),
      delay: Math.round(rand(i + 13) * 450),
      drift: (rand(i + 19) - 0.5) * 80,
      up,
      color: up ? palette[i % 3 === 0 ? 0 : i % 3] : colors.flowOut.bar,
      opacity: 0.35 + rand(i + 23) * 0.5,
    };
  });
}

function useCountUp(target: number, start: boolean, duration = 700) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!start) return undefined;
    const v = new Animated.Value(0);
    const id = v.addListener(({ value: p }) => setValue(target * p));
    Animated.timing(v, { toValue: 1, duration, easing: Easing.out(Easing.cubic), useNativeDriver: false })
      .start(() => setValue(target));
    return () => v.removeListener(id);
  }, [target, start, duration]);
  return value;
}

type Props = {
  month: number;
  summary: MonthSummary | null;
  masked: boolean;
  onDone: () => void;
};

export function TuMesIntro({ month, summary, masked, onDone }: Props) {
  const { width, height } = useWindowDimensions();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const bubbles = useMemo(() => makeBubbles(width), [width]);
  const flow = useRef(bubbles.map(() => new Animated.Value(0))).current;
  const title = useRef(new Animated.Value(0)).current;
  const chipIn = useRef(new Animated.Value(0)).current;
  const chipOut = useRef(new Animated.Value(0)).current;
  const exit = useRef(new Animated.Value(0)).current;
  const finished = useRef(false);
  const [counting, setCounting] = useState(false);

  const income = Number(summary?.current.incomeUsd ?? 0);
  const spending = Number(summary?.current.spendingUsd ?? 0);
  const shownResult = useCountUp(income - spending, counting && Boolean(summary));

  // Accessibility first: no takeover with Reduce Motion or a screen reader.
  useEffect(() => {
    let alive = true;
    Promise.all([AccessibilityInfo.isReduceMotionEnabled(), AccessibilityInfo.isScreenReaderEnabled()])
      .then(([reduce, reader]) => { if (alive) setEnabled(!reduce && !reader); })
      .catch(() => { if (alive) setEnabled(false); });
    return () => { alive = false; };
  }, []);

  const finish = () => {
    if (finished.current) return;
    finished.current = true;
    Animated.timing(exit, { toValue: 1, duration: INTRO_EXIT_MS, easing: Easing.in(Easing.cubic), useNativeDriver: true })
      .start(() => onDone());
  };

  useEffect(() => {
    if (enabled === null) return undefined;
    if (!enabled) {
      onDone();
      return undefined;
    }
    const native = { useNativeDriver: true };
    const bubbleAnims = flow.map((v, i) => Animated.timing(v, {
      toValue: 1, duration: 1300 + (i % 5) * 120, delay: bubbles[i].delay, easing: Easing.out(Easing.quad), ...native,
    }));
    const seq = Animated.parallel([
      ...bubbleAnims,
      Animated.sequence([
        Animated.delay(120),
        Animated.spring(title, { toValue: 1, friction: 5, tension: 90, ...native }),
      ]),
      Animated.sequence([
        Animated.delay(420),
        Animated.spring(chipIn, { toValue: 1, friction: 6, tension: 120, ...native }),
      ]),
      Animated.sequence([
        Animated.delay(560),
        Animated.spring(chipOut, { toValue: 1, friction: 6, tension: 120, ...native }),
      ]),
    ]);
    seq.start();
    const count = setTimeout(() => setCounting(true), 420);
    const hold = setTimeout(finish, INTRO_HOLD_MS);
    return () => {
      seq.stop();
      clearTimeout(count);
      clearTimeout(hold);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  if (!enabled) return null;

  const money = (v: number) => (masked ? MASK : formatUsd(v, { whole: true }));
  const pop = (v: Animated.Value) => ({
    opacity: v,
    transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [0.6, 1] }) }],
  });

  return (
    <Animated.View
      style={[StyleSheet.absoluteFill, styles.root, {
        opacity: exit.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }),
        transform: [
          { translateY: exit.interpolate({ inputRange: [0, 1], outputRange: [0, -height * 0.18] }) },
          { scale: exit.interpolate({ inputRange: [0, 1], outputRange: [1, 0.92] }) },
        ],
      }]}
      testID="tumes-intro"
      importantForAccessibility="no-hide-descendants"
      accessibilityElementsHidden
    >
      <Pressable style={StyleSheet.absoluteFill} onPress={finish} testID="tumes-intro-skip">
        {bubbles.map((b, i) => (
          <Animated.View
            key={i}
            pointerEvents="none"
            style={[styles.bubble, {
              left: b.x - b.size / 2,
              top: b.up ? height * 0.9 : height * 0.12,
              width: b.size, height: b.size, borderRadius: b.size / 2,
              backgroundColor: b.color,
              opacity: flow[i].interpolate({ inputRange: [0, 0.15, 0.85, 1], outputRange: [0, b.opacity, b.opacity, 0] }),
              transform: [
                { translateY: flow[i].interpolate({ inputRange: [0, 1], outputRange: [0, (b.up ? -1 : 1) * height * 0.75] }) },
                { translateX: flow[i].interpolate({ inputRange: [0, 1], outputRange: [0, b.drift] }) },
                { scale: flow[i].interpolate({ inputRange: [0, 0.5, 1], outputRange: [0.4, 1.1, 0.9] }) },
              ],
            }]}
          />
        ))}

        <View style={styles.center} pointerEvents="none">
          <Animated.View style={pop(title)}>
            <Text style={styles.month} maxFontSizeMultiplier={1.3}>{capitalize(monthName(month))}</Text>
          </Animated.View>
          {summary && (
            <>
              <Animated.View style={[styles.result, pop(title)]}>
                <Text style={styles.resultText} maxFontSizeMultiplier={1.2} numberOfLines={1} adjustsFontSizeToFit>
                  {resultText(counting ? shownResult : 0, masked)}
                </Text>
              </Animated.View>
              <View style={styles.chips}>
                <Animated.View style={[styles.chip, pop(chipIn)]}>
                  <Text style={styles.chipText} maxFontSizeMultiplier={1.3}>↓ Entró {money(income)}</Text>
                </Animated.View>
                <Animated.View style={[styles.chip, pop(chipOut)]}>
                  <Text style={[styles.chipText, styles.chipOut]} maxFontSizeMultiplier={1.3}>↑ Salió {money(spending)}</Text>
                </Animated.View>
              </View>
            </>
          )}
        </View>
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: { backgroundColor: colors.heroField, zIndex: 50, elevation: 50, overflow: 'hidden' },
  bubble: { position: 'absolute' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 24 },
  month: { fontSize: 44, lineHeight: 52, fontWeight: '800', color: colors.onHeroField, letterSpacing: -0.5 },
  result: { marginTop: 10 },
  resultText: { fontSize: 36, lineHeight: 44, fontWeight: '700', color: colors.onHeroField, fontVariant: ['tabular-nums'] },
  chips: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 10, marginTop: 18 },
  chip: { backgroundColor: colors.white, borderRadius: 999, paddingHorizontal: 16, paddingVertical: 9 },
  chipText: { fontSize: 16, fontWeight: '700', color: colors.flowIn.textSmall, fontVariant: ['tabular-nums'] },
  chipOut: { color: colors.flowOut.text },
});
