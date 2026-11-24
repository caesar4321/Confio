// The moment an order is done: the check springs in, a burst of confetti in
// Confío's colours, the same buzz a payment's success screen gives. Played once,
// and only when the card saw it happen (never when an old card scrolls back).
// "Reduce motion" keeps the check and the words, without the burst.
import React, { useEffect, useMemo, useRef } from 'react';
import { AccessibilityInfo, Animated, Easing, Platform, StyleSheet, Vibration, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { useStill } from './PurchaseJourney';

const CONFETTI = [colors.primary, colors.primaryDark, colors.secondary, colors.accent, '#F59E0B', '#F472B6'];
const PIECES = 18;

// As a payment's success screen does (PaymentSuccessScreen).
export function buzz() {
  try {
    Vibration.vibrate(Platform.OS === 'ios' ? 50 : [0, 50, 30, 50]);
  } catch {
    // no vibrator: nothing to feel
  }
}

export function PurchaseDone({ celebrate }: { celebrate: boolean }) {
  const still = useStill();
  const pop = useRef(new Animated.Value(celebrate ? 0 : 1)).current;
  useEffect(() => {
    if (!celebrate) {
      return;
    }
    buzz();
    AccessibilityInfo.announceForAccessibility?.('Pedido hecho');
    Animated.spring(pop, { toValue: 1, friction: 4, tension: 120, useNativeDriver: true }).start();
    // Once, when it happens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <View style={styles.done}>
      {celebrate && !still ? <Confetti /> : null}
      <Animated.View style={[styles.badge, { transform: [{ scale: pop }] }]}>
        <Icon name="check" size={22} color={colors.white} />
      </Animated.View>
      <Text style={styles.headline}>¡Pedido hecho!</Text>
    </View>
  );
}

// Each piece flies out from the badge, turns, and falls away. Its path is fixed by its place in
// the burst (no dice: the same burst every time, and a test can read it).
function Confetti() {
  const flight = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(flight, { toValue: 1, duration: 1400, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
  }, [flight]);
  const pieces = useMemo(() => Array.from({ length: PIECES }, (_, index) => {
    const angle = (index / PIECES) * Math.PI * 2 + (index % 2 ? 0.18 : -0.12);
    const reach = 46 + ((index * 37) % 52);
    return {
      key: index, color: CONFETTI[index % CONFETTI.length], round: index % 3 === 0,
      x: Math.cos(angle) * reach, y: Math.sin(angle) * reach - 18, fall: 26 + ((index * 13) % 30),
      turn: `${(index % 2 ? 1 : -1) * (160 + ((index * 53) % 220))}deg`,
    };
  }), []);
  return (
    <View pointerEvents="none" style={styles.burst} testID="purchase-confetti">
      {pieces.map((piece) => (
        <Animated.View key={piece.key} style={[styles.piece, piece.round && styles.pieceRound, {
          backgroundColor: piece.color,
          opacity: flight.interpolate({ inputRange: [0, 0.08, 0.7, 1], outputRange: [0, 1, 1, 0] }),
          transform: [
            { translateX: flight.interpolate({ inputRange: [0, 1], outputRange: [0, piece.x] }) },
            { translateY: flight.interpolate({ inputRange: [0, 0.6, 1], outputRange: [0, piece.y, piece.y + piece.fall] }) },
            { rotate: flight.interpolate({ inputRange: [0, 1], outputRange: ['0deg', piece.turn] }) },
          ],
        }]} />
      ))}
    </View>
  );
}

const BADGE = 44;
const styles = StyleSheet.create({
  done: { alignItems: 'center', marginTop: 4, marginBottom: 2 },
  badge: { width: BADGE, height: BADGE, borderRadius: BADGE / 2, backgroundColor: colors.primaryDark,
    alignItems: 'center', justifyContent: 'center' },
  headline: { marginTop: 8, fontSize: 20, fontWeight: '800', color: colors.onHeroField },
  burst: { position: 'absolute', top: BADGE / 2, left: '50%', width: 0, height: 0, alignItems: 'center',
    justifyContent: 'center' },
  piece: { position: 'absolute', width: 7, height: 11, borderRadius: 2 },
  pieceRound: { width: 8, height: 8, borderRadius: 4 },
});
