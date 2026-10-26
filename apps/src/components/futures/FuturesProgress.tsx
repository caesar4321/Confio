import React, { useEffect, useRef } from 'react';
import { ActivityIndicator, Animated, Modal, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../common/AppText';
import type { PerpsStep } from '../../services/perps';

export type ProgressKind = 'open' | 'close' | 'margin' | 'resume';

const STEPS: Record<ProgressKind, { key: PerpsStep; label: string; hint: string }[]> = {
  open: [
    { key: 'exit', label: 'Saliendo de tus dólares', hint: 'Firmas una sola vez con tu llave' },
    { key: 'bridge', label: 'Cruzando a Hyperliquid', hint: 'Normalmente tarda unos segundos' },
    { key: 'open', label: 'Abriendo tu posición', hint: 'Margen aislado, al mejor precio del momento' },
  ],
  margin: [
    { key: 'exit', label: 'Saliendo de tus dólares', hint: 'Firmas una sola vez con tu llave' },
    { key: 'bridge', label: 'Cruzando a Hyperliquid', hint: 'Normalmente tarda unos segundos' },
    { key: 'open', label: 'Sumando el margen', hint: 'Tu precio de liquidación se aleja' },
  ],
  close: [
    { key: 'close', label: 'Cerrando tu posición', hint: 'Al mejor precio del momento' },
    { key: 'return', label: 'Volviendo a BNB Chain', hint: 'Normalmente tarda unos segundos' },
    { key: 'enter', label: 'Entrando a tus dólares', hint: 'Queda en tu saldo de Confío' },
  ],
  resume: [
    { key: 'bridge', label: 'Revisando la transferencia', hint: 'Seguimos donde quedó' },
    { key: 'open', label: 'Terminando el paso pendiente', hint: 'Con tu firma' },
    { key: 'enter', label: 'Listo en tus dólares', hint: 'Cuando corresponde' },
  ],
};

/**
 * One full-screen moment while money crosses chains: each step lights up as
 * it starts and checks off when the next begins. Nothing to tap — the steps
 * are short, and if anything takes long the server keeps going on its own.
 */
export function FuturesProgress({
  visible,
  kind,
  current,
  title,
}: {
  visible: boolean;
  kind: ProgressKind;
  current: PerpsStep | null;
  title: string;
}) {
  const steps = STEPS[kind];
  const index = current === 'done' ? steps.length : Math.max(0, steps.findIndex((s) => s.key === current));
  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!visible) return undefined;
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1, duration: 700, useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 0, duration: 700, useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [visible, pulse]);

  return (
    <Modal visible={visible} transparent animationType="fade" statusBarTranslucent>
      <View style={styles.backdrop}>
        <View style={styles.card} accessibilityLiveRegion="polite">
          <Text style={styles.title}>{title}</Text>
          {steps.map((step, i) => {
            const done = i < index;
            const active = i === index;
            return (
              <View key={step.key} style={styles.row}>
                <View style={styles.rail}>
                  <Animated.View
                    style={[
                      styles.dot,
                      done && styles.dotDone,
                      active && styles.dotActive,
                      active && { opacity: pulse.interpolate({ inputRange: [0, 1], outputRange: [1, 0.55] }) },
                    ]}
                  >
                    {done ? <Icon name="check" size={14} color="#FFFFFF" /> : active
                      ? <ActivityIndicator size="small" color="#FFFFFF" /> : null}
                  </Animated.View>
                  {i < steps.length - 1 && <View style={[styles.line, done && styles.lineDone]} />}
                </View>
                <View style={styles.text}>
                  <Text style={[styles.label, !done && !active && styles.labelIdle]}>{step.label}</Text>
                  {active && <Text style={styles.hint}>{step.hint}</Text>}
                </View>
              </View>
            );
          })}
          <Text style={styles.footer}>Tu dinero siempre queda en cuentas a tu nombre.</Text>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(15,23,42,0.55)', justifyContent: 'center', padding: 24 },
  card: { backgroundColor: '#FFFFFF', borderRadius: 24, padding: 22 },
  title: { fontSize: 19, fontWeight: '800', color: '#111827', marginBottom: 18 },
  row: { flexDirection: 'row', minHeight: 58 },
  rail: { width: 30, alignItems: 'center' },
  dot: { width: 26, height: 26, borderRadius: 13, backgroundColor: '#E5E7EB', alignItems: 'center', justifyContent: 'center' },
  dotDone: { backgroundColor: '#10B981' },
  dotActive: { backgroundColor: '#0F172A' },
  line: { flex: 1, width: 2, backgroundColor: '#E5E7EB', marginVertical: 2 },
  lineDone: { backgroundColor: '#10B981' },
  text: { flex: 1, paddingLeft: 12, paddingTop: 3 },
  label: { fontSize: 15, fontWeight: '700', color: '#111827' },
  labelIdle: { color: '#9CA3AF' },
  hint: { fontSize: 12, color: '#6B7280', marginTop: 2 },
  footer: { fontSize: 12, color: '#9CA3AF', textAlign: 'center', marginTop: 8 },
});
