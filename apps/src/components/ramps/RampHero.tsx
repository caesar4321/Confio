import React from 'react';
import {
  StyleSheet,
  TouchableOpacity,
  View,
} from 'react-native';
import { Text } from '../common/AppText';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';

import { colors } from '../../config/theme';
import { FlagLabel } from '../CountryFlag';

type Props = {
  eyebrow: string;
  /** ISO code whose round flag leads the eyebrow. */
  eyebrowCountry?: string | null;
  title: string;
  subtitle: string;
  onBack: () => void;
  compact?: boolean;
  /** "Historial" pill across from the back button (as on Guardarian's screens). */
  onHistory?: () => void;
  historyLabel?: string;
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
  eyebrowCountry,
  title,
  subtitle,
  onBack,
  compact = false,
  onHistory,
  historyLabel = 'Ver historial',
  fromColor = colors.heroField,
  toColor = colors.heroFieldDark,
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
        <View style={styles.topRow}>
          <TouchableOpacity onPress={onBack} style={styles.backButton} accessibilityRole="button" accessibilityLabel="Volver">
            <Icon name="arrow-left" size={20} color={colors.white} />
          </TouchableOpacity>
          {onHistory ? (
            <TouchableOpacity onPress={onHistory} style={styles.historyButton} accessibilityRole="button" accessibilityLabel={historyLabel}>
              <Text style={styles.historyButtonText}>Historial</Text>
            </TouchableOpacity>
          ) : null}
        </View>
        {eyebrowCountry ? (
          <FlagLabel iso={eyebrowCountry} size={14} style={styles.eyebrowRow} textStyle={[styles.eyebrow, styles.eyebrowInRow]}>
            {eyebrow}
          </FlagLabel>
        ) : (
          <Text style={styles.eyebrow}>{eyebrow}</Text>
        )}
        <Text style={[styles.title, compact && styles.titleCompact]}>{title}</Text>
        <Text style={styles.subtitle}>{subtitle}</Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  heroWrapper: {
    backgroundColor: colors.heroField,
    overflow: 'hidden',
    marginBottom: 20,
  },
  heroInner: {
    paddingHorizontal: 24,
    paddingBottom: 28,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 20,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.2)',
  },
  historyButton: {
    minWidth: 72,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
    alignItems: 'center',
  },
  historyButtonText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.white,
  },
  eyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    color: 'rgba(255,255,255,0.7)',
    marginBottom: 8,
  },
  eyebrowRow: {
    marginBottom: 8,
  },
  eyebrowInRow: {
    marginBottom: 0,
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
