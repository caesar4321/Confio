import React from 'react';
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';

import { colors } from '../../config/theme';

type Props = {
  eyebrow: string;
  title: string;
  subtitle: string;
  onBack: () => void;
  compact?: boolean;
  /** Top gradient stop — defaults to the brand field (primary → primaryDark). */
  fromColor?: string;
  /** Bottom gradient stop. */
  toColor?: string;
};

/**
 * Shared hero for the ramp flows (TopUp/Sell/History/Instructions) — the
 * app-wide brand field: vertical gradient + cropped coin ring. Padding lives
 * on heroInner because Yoga insets absolute children by parent padding.
 */
export const RampHero = ({
  eyebrow,
  title,
  subtitle,
  onBack,
  compact = false,
  fromColor = colors.primary,
  toColor = colors.primaryDark,
}: Props) => {
  const insets = useSafeAreaInsets();

  return (
    <View style={styles.heroWrapper}>
      <Svg style={StyleSheet.absoluteFill}>
        <Defs>
          <SvgLinearGradient id="rampHeroField" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={fromColor} />
            <Stop offset="1" stopColor={toColor} />
          </SvgLinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#rampHeroField)" />
        <Circle cx="105%" cy="30%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
      </Svg>
      <View style={[styles.heroInner, { paddingTop: Math.max(insets.top, 12) + 12 }]}>
        <TouchableOpacity onPress={onBack} style={styles.backButton} accessibilityRole="button" accessibilityLabel="Volver">
          <Icon name="arrow-left" size={20} color={colors.white} />
        </TouchableOpacity>
        <Text style={styles.eyebrow}>{eyebrow}</Text>
        <Text style={[styles.title, compact && styles.titleCompact]}>{title}</Text>
        <Text style={styles.subtitle}>{subtitle}</Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  heroWrapper: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
    marginBottom: 20,
  },
  heroInner: {
    paddingHorizontal: 24,
    paddingBottom: 28,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.15)',
    marginBottom: 20,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.2)',
  },
  eyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    color: 'rgba(255,255,255,0.7)',
    marginBottom: 8,
  },
  title: {
    fontSize: 28,
    fontWeight: '800',
    color: colors.white,
    marginBottom: 10,
    lineHeight: 34,
  },
  titleCompact: {
    fontSize: 24,
    lineHeight: 30,
  },
  subtitle: {
    fontSize: 14,
    lineHeight: 22,
    color: 'rgba(255,255,255,0.8)',
    maxWidth: '88%',
  },
});
