import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Animated } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

type Props = {
  amountMicros: number;
  assetId: string;
  onPressDetails: () => void;
  onDismiss: () => void;
  style?: any;
};

// Map known asset IDs to display symbols/colors
function resolveAsset(assetId: string): { symbol: string; bg: string; fg: string } {
  const idNum = parseInt(assetId, 10);
  // Known asset IDs per current network (testnet)
  const CUSD_IDS = [744151197, 744368179];
  const CONFIO_IDS = [744150851];
  if (CUSD_IDS.includes(idNum)) {
    return { symbol: 'cUSD', bg: '#ecfeff', fg: '#0e7490' };
  }
  if (CONFIO_IDS.includes(idNum)) {
    return { symbol: 'CONFIO', bg: '#f5f3ff', fg: '#6d28d9' };
  }
  return { symbol: 'ASA', bg: '#f1f5f9', fg: '#0f172a' };
}

export const InviteClaimBanner: React.FC<Props> = ({ amountMicros, assetId, onPressDetails, onDismiss, style }) => {
  const token = resolveAsset(assetId);
  const amount = (amountMicros || 0) / 1_000_000;

  // Simple entrance animation
  const slide = useRef(new Animated.Value(30)).current;
  const fade = useRef(new Animated.Value(0)).current;
  const confetti = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.spring(slide, { toValue: 0, useNativeDriver: true, friction: 10, tension: 60 }),
      Animated.timing(fade, { toValue: 1, duration: 250, useNativeDriver: true }),
    ]).start(() => {
      // brief confetti pop
      Animated.sequence([
        Animated.timing(confetti, { toValue: 1, duration: 220, useNativeDriver: true }),
        Animated.timing(confetti, { toValue: 0, duration: 600, useNativeDriver: true }),
      ]).start();
    });
  }, [slide, fade, confetti]);

  return (
    <Animated.View
      style={[
        styles.wrapper,
        { transform: [{ translateY: slide }], opacity: fade },
        style,
      ]}
    >
      <View style={[styles.container, { backgroundColor: token.bg, shadowColor: token.fg }]}>        
        <View style={[styles.iconCircle, { backgroundColor: token.fg }]}>          
          <Text style={styles.emoji}>🎉</Text>
        </View>

        <View style={styles.content}>
          <Text style={[styles.title, { color: token.fg }]}>¡Sorpresa! Recibiste una invitación</Text>
          <View style={styles.row}>            
            <Text style={[styles.amount, { color: token.fg }]}>
              {amount.toFixed(2)}
            </Text>
            <View style={[styles.chip, { borderColor: token.fg }]}>              
              <Text style={[styles.chipText, { color: token.fg }]}>{token.symbol}</Text>
            </View>
          </View>
          <TouchableOpacity onPress={onPressDetails} activeOpacity={0.8} style={styles.cta}>
            <Text style={[styles.ctaText, { color: token.fg }]}>Ver detalles</Text>
            <Icon name="chevron-right" size={16} color={token.fg} />
          </TouchableOpacity>
        </View>

        <TouchableOpacity onPress={onDismiss} hitSlop={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <Icon name="x" size={18} color={token.fg} />
        </TouchableOpacity>

        {/* Confetti flair */}
        <Animated.View style={[styles.confetti, { opacity: confetti }]}>          
          <Text style={styles.confettiText}>✨</Text>
          <Text style={styles.confettiText}>🪅</Text>
          <Text style={styles.confettiText}>✨</Text>
        </Animated.View>
      </View>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    left: 20,
    right: 20,
    bottom: 110,
  },
  container: {
    borderRadius: 16,
    padding: 14,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderWidth: 0,
    shadowOpacity: 0.18,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 6 },
    elevation: 4,
  },
  iconCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emoji: {
    fontSize: 16,
    color: '#fff',
  },
  content: { flex: 1 },
  title: {
    fontWeight: '700',
    fontSize: 14,
    marginBottom: 4,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  amount: {
    fontSize: 16,
    fontWeight: '700',
  },
  chip: {
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  chipText: {
    fontSize: 12,
    fontWeight: '600',
  },
  cta: {
    marginTop: 6,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  ctaText: {
    fontWeight: '600',
    fontSize: 13,
  },
  confetti: {
    position: 'absolute',
    top: -8,
    right: 10,
    flexDirection: 'row',
    gap: 4,
  },
  confettiText: { fontSize: 12 },
});

export default InviteClaimBanner;
