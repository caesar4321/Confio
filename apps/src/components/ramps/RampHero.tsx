import React from 'react';
import {
  Platform,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
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
  fromColor = '#059669',
  toColor = '#34d399',
}: Props) => {
  return (
    <View style={styles.heroWrapper}>
      <Gradient fromColor={fromColor} toColor={toColor} style={styles.heroGradient}>
        <View style={styles.heroPadding}>
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
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
    overflow: 'hidden',
    marginBottom: 20,
  },
  heroGradient: {
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  heroPadding: {
    paddingHorizontal: 24,
    paddingTop: Platform.OS === 'android' ? (StatusBar.currentHeight || 24) + 12 : 16,
    paddingBottom: 28,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.18)',
    marginBottom: 16,
  },
  eyebrow: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: 'rgba(255,255,255,0.75)',
    marginBottom: 6,
  },
  title: {
    fontSize: 26,
    fontWeight: '800',
    color: '#ffffff',
    marginBottom: 8,
  },
  titleCompact: {
    fontSize: 23,
    lineHeight: 29,
  },
  subtitle: {
    fontSize: 14,
    lineHeight: 21,
    color: 'rgba(255,255,255,0.8)',
  },
});
