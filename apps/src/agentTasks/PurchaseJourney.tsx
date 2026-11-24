// Where a purchase is, drawn as a short journey: Buscar → Carrito → Pedido → Pago.
// While the assistant works the current station breathes and a dot travels toward
// the next one, with a line of small talk about what it is doing (never that
// anything was bought). When it is the person's turn the journey stands still.
// "Reduce motion" stills all of it.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, LayoutChangeEvent, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';

export type Stage = 'search' | 'cart' | 'checkout' | 'pay' | 'done';
const STATIONS: { key: Exclude<Stage, 'done'>; icon: string; label: string }[] = [
  { key: 'search', icon: 'search', label: 'Buscar' },
  { key: 'cart', icon: 'shopping-cart', label: 'Carrito' },
  { key: 'checkout', icon: 'package', label: 'Pedido' },
  { key: 'pay', icon: 'zap', label: 'Pago' },
];
// What it is doing, said lightly. Never that something was bought, ordered or paid.
const SMALL_TALK: Record<Exclude<Stage, 'done'>, string[]> = {
  search: ['Recorriendo los pasillos de {site}…', 'Comparando opciones…', 'Leyendo la letra chiquita…'],
  cart: ['Poniéndolo en el carrito…', 'Revisando que solo vaya lo tuyo…', 'Camino a la caja…'],
  checkout: ['Pasando por la caja…', 'Eligiendo cómo pagar, sin tarjeta…', 'Revisando el total…'],
  pay: ['Buscando los datos para pagar…', 'Leyendo el pedido…', 'Ya casi…'],
};
const TALK_MS = 3200;

export function stationIndex(stage: Stage | string | null | undefined): number {
  if (stage === 'done') {
    return STATIONS.length;
  }
  const index = STATIONS.findIndex((station) => station.key === stage);
  return index < 0 ? 0 : index;
}

// "Reduce motion", as state: the journey draws itself still when it is on.
export function useStill(): boolean {
  const [still, setStill] = useState(false);
  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => { if (mounted) setStill(!!enabled); })
      .catch(() => undefined);
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', (enabled) => setStill(!!enabled));
    return () => { mounted = false; sub?.remove?.(); };
  }, []);
  return still;
}

export function PurchaseJourney({ stage, working, stopped, site }: {
  stage: Stage | string | null | undefined; working: boolean; stopped?: boolean; site: string;
}) {
  const still = useStill();
  const at = stationIndex(stage);
  const moving = working && !still && at < STATIONS.length;
  const current = STATIONS[Math.min(at, STATIONS.length - 1)];
  return (
    <View accessible accessibilityRole="progressbar"
      accessibilityLabel={at >= STATIONS.length ? 'Pedido hecho'
        : `Paso ${at + 1} de ${STATIONS.length}: ${current.label}`}>
      <View style={styles.row}>
        {STATIONS.map((station, index) => (
          <React.Fragment key={station.key}>
            {index > 0 ? <Track filled={index <= at} travelling={moving && index === at + 1} /> : null}
            <Station icon={station.icon} state={index < at ? 'done' : index === at ? 'current' : 'ahead'}
              breathing={moving && index === at} stopped={!!stopped && index === at} />
          </React.Fragment>
        ))}
      </View>
      <View style={styles.labels}>
        {STATIONS.map((station, index) => (
          <Text key={station.key} style={[styles.label, index === at && styles.labelCurrent,
            index < at && styles.labelDone]} numberOfLines={1}>{station.label}</Text>
        ))}
      </View>
      {working && at < STATIONS.length ? (
        <SmallTalk lines={SMALL_TALK[current.key]} site={site} still={still} />
      ) : null}
    </View>
  );
}

function Station({ icon, state, breathing, stopped }: {
  icon: string; state: 'done' | 'current' | 'ahead'; breathing: boolean; stopped: boolean;
}) {
  const halo = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!breathing) {
      halo.setValue(0);
      return undefined;
    }
    const loop = Animated.loop(Animated.timing(halo, {
      toValue: 1, duration: 1500, easing: Easing.out(Easing.quad), useNativeDriver: true,
    }));
    loop.start();
    return () => loop.stop();
  }, [breathing, halo]);
  return (
    <View style={styles.stationBox}>
      {breathing ? (
        <Animated.View pointerEvents="none" style={[styles.halo, {
          opacity: halo.interpolate({ inputRange: [0, 1], outputRange: [0.45, 0] }),
          transform: [{ scale: halo.interpolate({ inputRange: [0, 1], outputRange: [1, 1.9] }) }],
        }]} />
      ) : null}
      <View style={[styles.station, state === 'done' && styles.stationDone, state === 'current' && styles.stationCurrent,
        stopped && styles.stationStopped]}>
        <Icon name={state === 'done' ? 'check' : icon} size={16}
          color={state === 'done' ? colors.white : state === 'current' && !stopped ? colors.onHeroField : '#9CA3AF'} />
      </View>
    </View>
  );
}

function Track({ filled, travelling }: { filled: boolean; travelling: boolean }) {
  const [width, setWidth] = useState(0);
  const dot = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!travelling || !width) {
      dot.setValue(0);
      return undefined;
    }
    const loop = Animated.loop(Animated.timing(dot, {
      toValue: 1, duration: 1300, easing: Easing.inOut(Easing.quad), useNativeDriver: true,
    }));
    loop.start();
    return () => loop.stop();
  }, [travelling, width, dot]);
  const measure = (event: LayoutChangeEvent) => setWidth(event.nativeEvent.layout.width);
  return (
    <View style={[styles.track, filled && styles.trackFilled]} onLayout={measure}>
      {travelling && width ? (
        <Animated.View pointerEvents="none" style={[styles.dot, {
          opacity: dot.interpolate({ inputRange: [0, 0.15, 0.85, 1], outputRange: [0, 1, 1, 0] }),
          transform: [{ translateX: dot.interpolate({ inputRange: [0, 1], outputRange: [0, Math.max(0, width - 8)] }) }],
        }]} />
      ) : null}
    </View>
  );
}

function SmallTalk({ lines, site, still }: { lines: string[]; site: string; still: boolean }) {
  const [index, setIndex] = useState(0);
  const fade = useRef(new Animated.Value(1)).current;
  const said = useMemo(() => lines.map((line) => line.replace('{site}', site)), [lines, site]);
  useEffect(() => { setIndex(0); fade.setValue(1); }, [said, fade]);
  useEffect(() => {
    if (still || said.length < 2) {
      return undefined;
    }
    const timer = setInterval(() => {
      Animated.timing(fade, { toValue: 0, duration: 220, useNativeDriver: true }).start(() => {
        setIndex((value) => (value + 1) % said.length);
        Animated.timing(fade, { toValue: 1, duration: 260, useNativeDriver: true }).start();
      });
    }, TALK_MS);
    return () => clearInterval(timer);
  }, [still, said, fade]);
  return (
    <Animated.View style={{ opacity: fade }}>
      <Text style={styles.talk} numberOfLines={1}>{said[index % said.length]}</Text>
    </Animated.View>
  );
}

const SIZE = 34;
const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', marginTop: 2, paddingHorizontal: 11 },
  stationBox: { width: SIZE, height: SIZE, alignItems: 'center', justifyContent: 'center' },
  station: { width: SIZE, height: SIZE, borderRadius: SIZE / 2, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.neutralDark },
  stationDone: { backgroundColor: colors.primaryDark },
  stationCurrent: { backgroundColor: colors.primaryLight, borderWidth: 1.5, borderColor: colors.primaryDark },
  stationStopped: { backgroundColor: colors.neutralDark, borderColor: '#D1D5DB' },
  halo: { position: 'absolute', width: SIZE, height: SIZE, borderRadius: SIZE / 2, backgroundColor: colors.primary },
  track: { flex: 1, height: 3, borderRadius: 2, marginHorizontal: 4, backgroundColor: '#E5E7EB', justifyContent: 'center' },
  trackFilled: { backgroundColor: colors.primaryDark },
  dot: { position: 'absolute', left: 0, width: 8, height: 8, borderRadius: 4, backgroundColor: colors.primaryDark },
  labels: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  label: { width: 56, textAlign: 'center', fontSize: 11, color: '#9CA3AF' },
  labelCurrent: { color: colors.onHeroField, fontWeight: '700' },
  labelDone: { color: '#047857' },
  talk: { marginTop: 10, fontSize: 13, color: '#6B7280', fontStyle: 'italic' },
});
