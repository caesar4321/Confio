import React, { useEffect, useRef } from 'react';
import { ActivityIndicator, Animated, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../../config/theme';

interface ProcessingHeroProps {
  /** "Enviando…" / "Pagando…" — or "¡Casi listo!" when complete */
  title: string;
  /** "$25.00 cUSD" — same slot and scale as SuccessHero's amount */
  amount: string;
  /** "Para María" / "En Bodega Central" */
  hint?: string;
  /** Swaps the spinner for the emerald check (the SuccessHero icon) */
  complete?: boolean;
  /** Optional slot under the hint (step line, notices) */
  children?: React.ReactNode;
}

/**
 * Processing counterpart of SuccessHero: identical layout and type scale so
 * the replace() into the success screen reads as the spinner becoming the
 * check, not as a scene change. Self-contained pulse animation.
 */
export const ProcessingHero: React.FC<ProcessingHeroProps> = ({ title, amount, hint, complete, children }) => {
  const pulse = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (complete) {
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1.25, duration: 1000, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 1, duration: 1000, useNativeDriver: true }),
      ])
    );
    loop.start();
    return () => {
      loop.stop();
      pulse.stopAnimation();
    };
  }, [complete, pulse]);

  return (
    <View style={styles.wrap}>
      <View style={styles.iconSlot}>
        {complete ? (
          <View style={styles.iconDone}>
            <Icon name="check" size={40} color={colors.white} />
          </View>
        ) : (
          <>
            <Animated.View style={[styles.pulseRing, { transform: [{ scale: pulse }] }]} />
            <View style={styles.iconBusy}>
              <ActivityIndicator size="large" color={colors.primaryDark} />
            </View>
          </>
        )}
      </View>
      <Text style={styles.title} accessibilityRole="header">{title}</Text>
      <Text style={styles.amount}>{amount}</Text>
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
      {children}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    paddingTop: 48,
    paddingBottom: 28,
    paddingHorizontal: 32,
    backgroundColor: colors.background,
  },
  iconSlot: {
    width: 88,
    height: 88,
    marginBottom: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pulseRing: {
    position: 'absolute',
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.primary,
    opacity: 0.15,
  },
  iconBusy: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconDone: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text.primary,
    textAlign: 'center',
  },
  amount: {
    fontSize: 42,
    fontWeight: 'bold',
    color: colors.primaryDark,
    marginTop: 10,
  },
  hint: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    marginTop: 10,
    lineHeight: 20,
  },
});
