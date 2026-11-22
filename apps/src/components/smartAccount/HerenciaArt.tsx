// Herencia Digital: the inheritance promise as a picture (react-native-svg
// only). Two people side by side under one soft light, a dashed line handing
// over from one to the other with a heart on it: family and continuity,
// never death, a padlock or a sparkle (tokens.ts). Decorative: hidden from
// screen readers, the copy next to it carries the meaning.
import React from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import Svg, { Circle, Defs, Ellipse, LinearGradient, Path, RadialGradient, Rect, Stop } from 'react-native-svg';
import { colors } from '../../config/theme';
import { SA } from './tokens';

const PALETTE = {
  // On the account's deep emerald field.
  onDeep: {
    glow: colors.primary, // '#34D399'
    glowOpacity: 0.38,
    ring: SA.onDeep,
    ringOpacity: 0.14,
    owner: SA.onDeepMuted, // '#A7F3D0'
    heir: SA.onDeep,
    link: SA.onDeepMuted,
    heart: SA.onDeep,
    ground: SA.onDeep,
    groundOpacity: 0.12,
  },
  // On a white or mint card.
  onLight: {
    glow: colors.primary,
    glowOpacity: 0.28,
    ring: SA.deep,
    ringOpacity: 0.1,
    owner: SA.deep,
    heir: colors.primary,
    link: SA.mintText,
    heart: SA.mintText,
    ground: SA.deep,
    groundOpacity: 0.08,
  },
} as const;

/** Two figures and a heart; `width` sets the size (aspect 3:2). */
export function HerenciaArt({ width = 240, variant = 'onDeep', style }: {
  width?: number; variant?: keyof typeof PALETTE; style?: StyleProp<ViewStyle>;
}) {
  const p = PALETTE[variant];
  const id = `herencia-${variant}`;
  return (
    <View
      style={style}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      testID="herencia-art"
    >
      <Svg width={width} height={(width * 2) / 3} viewBox="0 0 240 160">
        <Defs>
          <RadialGradient id={`${id}-glow`} cx="50%" cy="56%" r="50%">
            <Stop offset="0" stopColor={p.glow} stopOpacity={p.glowOpacity} />
            <Stop offset="1" stopColor={p.glow} stopOpacity={0} />
          </RadialGradient>
        </Defs>
        <Rect x={0} y={0} width={240} height={160} fill={`url(#${id}-glow)`} />
        <Circle cx={120} cy={90} r={66} fill="none" stroke={p.ring} strokeOpacity={p.ringOpacity} strokeWidth={1.5} />
        <Ellipse cx={120} cy={138} rx={78} ry={7} fill={p.ground} fillOpacity={p.groundOpacity} />
        {/* The owner */}
        <Circle cx={94} cy={74} r={16} fill={p.owner} />
        <Path d="M64 136 C64 112 78 98 94 98 C110 98 124 112 124 136 Z" fill={p.owner} />
        {/* The person they chose */}
        <Circle cx={150} cy={86} r={13} fill={p.heir} />
        <Path d="M126 136 C126 117 137 106 150 106 C163 106 174 117 174 136 Z" fill={p.heir} />
        {/* The hand-over, with a heart on it */}
        <Path
          d="M100 50 C112 26 140 26 150 64"
          fill="none"
          stroke={p.link}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeDasharray="2 7"
        />
        <Path
          d="M124 44 C124 44 112 36.5 112 29.5 C112 25.6 115 23 118.4 23 C120.8 23 122.8 24.4 124 26.4 C125.2 24.4 127.2 23 129.6 23 C133 23 136 25.6 136 29.5 C136 36.5 124 44 124 44 Z"
          fill={p.heart}
        />
      </Svg>
    </View>
  );
}

/** The account's deep emerald field as a soft diagonal gradient, behind a hero. */
// Sized from its own measured box: a percentage-sized Svg can paint at its
// first, smaller layout on iOS and leave a darker rectangle in the hero.
export function DeepField() {
  const [size, setSize] = React.useState<{ w: number; h: number } | null>(null);
  return (
    <View
      style={[StyleSheet.absoluteFill, { backgroundColor: SA.deep }]}
      onLayout={(e) => {
        const { width: w, height: h } = e.nativeEvent.layout;
        setSize((s) => (s && s.w === w && s.h === h ? s : { w, h }));
      }}
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
    >
      {size ? (
    <Svg
      width={size.w}
      height={size.h}
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
    >
      <Defs>
        <LinearGradient id="sa-deep-field" x1="0" y1="0" x2="1" y2="1">
          <Stop offset="0" stopColor={SA.deep} />
          <Stop offset="1" stopColor={SA.deepPressed} />
        </LinearGradient>
      </Defs>
      <Rect x={0} y={0} width={100} height={100} fill="url(#sa-deep-field)" />
    </Svg>
      ) : null}
    </View>
  );
}
