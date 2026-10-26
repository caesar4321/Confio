import React, { useMemo, useRef, useState } from 'react';
import { LayoutChangeEvent, PanResponder, Pressable, StyleSheet, View } from 'react-native';

import { Text } from '../common/AppText';
import { leverageColor, leverageWord } from '../../utils/perpsPresentation';

/**
 * Leverage, chosen by touch: a track that warms from emerald to red as the
 * multiplier climbs, quick presets, and the word for how risky it is. Up to
 * the market's own Hyperliquid maximum: Confío sets no cap. Accessible as an
 * adjustable control (VoiceOver/TalkBack swipe up/down).
 */
export function LeverageSlider({
  value,
  max,
  onChange,
  disabled = false,
}: {
  value: number;
  max: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  const [width, setWidth] = useState(0);
  const widthRef = useRef(0);
  const maxRef = useRef(max);
  maxRef.current = max;
  const clamp = (v: number) => Math.max(1, Math.min(maxRef.current, Math.round(v)));
  const fromX = (x: number) => clamp(1 + (Math.max(0, Math.min(widthRef.current, x)) / (widthRef.current || 1))
    * (maxRef.current - 1));

  const responder = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => !disabled,
    onMoveShouldSetPanResponder: () => !disabled,
    onPanResponderGrant: (e) => onChange(fromX(e.nativeEvent.locationX)),
    onPanResponderMove: (e) => onChange(fromX(e.nativeEvent.locationX)),
    onPanResponderTerminationRequest: () => false,
  }), [disabled, onChange]); // eslint-disable-line react-hooks/exhaustive-deps

  const onLayout = (e: LayoutChangeEvent) => {
    widthRef.current = e.nativeEvent.layout.width;
    setWidth(e.nativeEvent.layout.width);
  };
  const t = max <= 1 ? 0 : (value - 1) / (max - 1);
  const tint = leverageColor(value, max);
  const presets = Array.from(new Set([1, 2, 3, 5, 10, 20, 40].filter((p) => p <= max).concat(max)));

  return (
    <View style={disabled && styles.disabled}>
      <View style={styles.head}>
        <Text style={[styles.value, { color: tint }]}>{value}x</Text>
        <View style={[styles.word, { backgroundColor: `${tint}1A` }]}>
          <Text style={[styles.wordText, { color: tint }]}>{leverageWord(value, max)}</Text>
        </View>
      </View>
      <View
        style={styles.trackHit}
        onLayout={onLayout}
        {...responder.panHandlers}
        accessible
        accessibilityRole="adjustable"
        accessibilityLabel="Apalancamiento"
        accessibilityValue={{ min: 1, max, now: value, text: `${value} veces` }}
        accessibilityActions={[{ name: 'increment' }, { name: 'decrement' }]}
        onAccessibilityAction={(e) => onChange(clamp(value + (e.nativeEvent.actionName === 'increment' ? 1 : -1)))}
      >
        <View style={styles.track}>
          <View style={[styles.fill, { width: `${t * 100}%`, backgroundColor: tint }]} />
        </View>
        {width > 0 && (
          <View pointerEvents="none" style={[styles.thumb, { left: t * width - 14, borderColor: tint }]} />
        )}
      </View>
      <View style={styles.presets}>
        {presets.map((p) => {
          const active = p === value;
          return (
            <Pressable
              key={p}
              onPress={() => !disabled && onChange(p)}
              style={[styles.preset, active && { backgroundColor: leverageColor(p, max) }]}
              accessibilityRole="button"
              accessibilityLabel={`${p} veces`}
              accessibilityState={{ selected: active }}
            >
              <Text style={[styles.presetText, active && styles.presetTextActive]}>
                {p === max && p !== 1 ? `Máx ${p}x` : `${p}x`}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  disabled: { opacity: 0.5 },
  head: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  value: { fontSize: 30, fontWeight: '800' },
  word: { borderRadius: 10, paddingHorizontal: 10, paddingVertical: 4 },
  wordText: { fontSize: 12, fontWeight: '800' },
  trackHit: { height: 40, justifyContent: 'center', marginTop: 6 },
  track: { height: 8, borderRadius: 4, backgroundColor: '#E5E7EB', overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 4 },
  thumb: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
    borderWidth: 3,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
  presets: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  preset: { paddingHorizontal: 12, minHeight: 34, justifyContent: 'center', borderRadius: 17, backgroundColor: '#F3F4F6' },
  presetText: { fontSize: 13, fontWeight: '700', color: '#374151' },
  presetTextActive: { color: '#FFFFFF' },
});
