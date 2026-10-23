import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Stop } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';

type Props = { onPress: () => void; size?: number };

/** The chat's Propina button: a gold gift that reads as a reward, not a tool. */
export function TipButton({ onPress, size = 40 }: Props) {
  const r = size / 2;
  return (
    <Pressable onPress={onPress} hitSlop={6} accessibilityRole="button" accessibilityLabel="Enviar propina"
      style={({ pressed }) => [{ width: size, height: size }, pressed && styles.pressed]}>
      <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
        <Defs>
          <LinearGradient id="tipGold" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor="#FCD34D" />
            <Stop offset="1" stopColor="#F59E0B" />
          </LinearGradient>
        </Defs>
        <Circle cx={r} cy={r} r={r} fill="url(#tipGold)" />
      </Svg>
      <View style={styles.icon}>
        <Icon name="gift" size={Math.round(size * 0.48)} color="#FFFFFF" />
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  icon: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  pressed: { opacity: 0.8, transform: [{ scale: 0.95 }] },
});
