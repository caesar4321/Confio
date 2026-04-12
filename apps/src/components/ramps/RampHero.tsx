import React from 'react';
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';

import { Gradient } from '../common/Gradient';

type Props = {
  eyebrow: string;
  title: string;
  subtitle: string;
  onBack: () => void;
  compact?: boolean;
  fromColor?: string;
  toColor?: string;
};

export const RampHero = ({
  eyebrow,
  title,
  subtitle,
  onBack,
  compact = false,
  fromColor = '#10b981',
  toColor = '#6ee7b7',
}: Props) => {
  const insets = useSafeAreaInsets();

  return (
    <View style={styles.heroWrapper}>
      <Gradient fromColor={fromColor} toColor={toColor} style={styles.heroGradient}>
        {/* Decorative circles for depth */}
        <View style={styles.decorCircleLarge} />
        <View style={styles.decorCircleSmall} />
        <View style={[styles.heroPadding, { paddingTop: Math.max(insets.top, 12) + 12 }]}>
          <TouchableOpacity onPress={onBack} style={styles.backButton}>
            <Icon name="arrow-left" size={20} color="#ffffff" />
          </TouchableOpacity>
          <Text style={styles.eyebrow}>{eyebrow}</Text>
          <Text style={[styles.title, compact && styles.titleCompact]}>{title}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>
      </Gradient>
    </View>
  );
};

const styles = StyleSheet.create({
  heroWrapper: {
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
    overflow: 'hidden',
    marginBottom: 20,
  },
  heroGradient: {
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
  },
  decorCircleLarge: {
    position: 'absolute',
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: 'rgba(255,255,255,0.06)',
    top: -60,
    right: -50,
  },
  decorCircleSmall: {
    position: 'absolute',
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: 'rgba(255,255,255,0.07)',
    bottom: -20,
    right: 60,
  },
  heroPadding: {
    paddingHorizontal: 24,
    paddingBottom: 32,
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
    color: 'rgba(255,255,255,0.6)',
    marginBottom: 8,
  },
  title: {
    fontSize: 28,
    fontWeight: '800',
    color: '#ffffff',
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
    color: 'rgba(255,255,255,0.72)',
    maxWidth: '88%',
  },
});
