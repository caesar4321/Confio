import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Linking, Modal, Platform, Pressable, StyleSheet, View } from 'react-native';
import MapView, { Region } from 'react-native-maps';
import Icon from 'react-native-vector-icons/Feather';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import { Pin, getPreciseFix } from '../../utils/deliveryLocation';
import { KitButton } from './kit';

type Props = {
  visible: boolean;
  /** Where the map opens: the current pin, else the store's city. */
  initial?: Pin | null;
  fallbackCenter?: Pin | null;
  onClose: () => void;
  onConfirm: (pin: Pin) => void;
};

const FAILURE_COPY = {
  denied: 'Permite la ubicación precisa de Confío en los ajustes (toca aquí), o mueve el mapa a mano hasta tu puerta.',
  disabled: 'Tu ubicación está apagada. Actívala (toca aquí), o mueve el mapa a mano hasta tu puerta.',
  unavailable: 'No pudimos ver tu ubicación. Mueve el mapa a mano hasta tu puerta.',
} as const;

const openLocationSettings = (failure: 'denied' | 'disabled') => () => {
  if (failure === 'disabled' && Platform.OS === 'android') {
    Linking.sendIntent('android.settings.LOCATION_SOURCE_SETTINGS').catch(() => { void Linking.openSettings(); });
    return;
  }
  void Linking.openSettings();
};

// About 400 m across: close enough to see the street and the door.
const STREET = { latitudeDelta: 0.004, longitudeDelta: 0.004 };
const CITY = { latitudeDelta: 0.08, longitudeDelta: 0.08 };

/**
 * "Marca dónde entregar": the map moves under a fixed pin, like Yango or
 * Rappi. Opens on the existing pin, else the phone's position, else the
 * store's city; the buyer drags to the exact door and confirms.
 */
export const LocationPickerModal = ({ visible, initial, fallbackCenter, onClose, onConfirm }: Props) => {
  const insets = useSafeAreaInsets();
  const map = useRef<MapView>(null);
  const [center, setCenter] = useState<Pin | null>(initial ?? null);
  const [locating, setLocating] = useState(false);
  // Why "Usar mi ubicación" found nothing, said plainly (null = nothing to say).
  const [failure, setFailure] = useState<'denied' | 'disabled' | 'unavailable' | null>(null);
  // A fix that arrives after the buyer dragged the map, or after the picker
  // closed/reopened, is stale: only the latest asked-for lookup applies.
  const generation = useRef(0);
  const dragged = useRef(false);

  const goTo = (pin: Pin, delta = STREET) => {
    setCenter(pin);
    map.current?.animateToRegion({ ...pin, ...delta }, 400);
  };

  const locate = async (explicit: boolean) => {
    const mine = ++generation.current;
    if (explicit) dragged.current = false; // "Usar mi ubicación" re-centers on purpose
    setLocating(true);
    setFailure(null);
    try {
      const fix = await getPreciseFix();
      if (mine !== generation.current || dragged.current) return;
      if ('pin' in fix) goTo(fix.pin);
      else setFailure(fix.error);
    } finally {
      if (mine === generation.current) setLocating(false);
    }
  };

  // Each opening starts from the current pin, or looks for the phone.
  useEffect(() => {
    generation.current += 1; // any lookup from a previous opening is stale
    dragged.current = false;
    if (!visible) return;
    if (initial) {
      setCenter(initial);
    } else {
      setCenter(fallbackCenter ?? null);
      void locate(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);
  // Unmounting with a lookup pending: its answer must not set state.
  useEffect(() => () => { generation.current += 1; }, []);

  // The phone's position may arrive after opening: the map then starts there.
  const start = initial ?? fallbackCenter ?? center;
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} presentationStyle="fullScreen">
      <View style={styles.screen}>
        {start ? (
          <MapView
            ref={map}
            style={StyleSheet.absoluteFill}
            initialRegion={{ ...start, ...(initial ? STREET : CITY) }}
            onRegionChangeComplete={(r: Region) => setCenter({ latitude: r.latitude, longitude: r.longitude })}
            onPanDrag={() => { dragged.current = true; }}
            showsUserLocation
            showsMyLocationButton={false}
            toolbarEnabled={false}
            testID="location-map"
          />
        ) : (
          <View style={[StyleSheet.absoluteFill, styles.waiting]}>
            <ActivityIndicator color={colors.primaryDark} />
            <Text style={styles.waitingText}>Buscando tu ubicación…</Text>
          </View>
        )}

        {/* The pin stays at the center; its tip marks the point. */}
        <View pointerEvents="none" style={styles.pinWrap}>
          <Icon name="map-pin" size={40} color={colors.primaryDeep} style={styles.pin} />
        </View>

        <View style={[styles.top, { paddingTop: insets.top + 8 }]}>
          <Pressable onPress={onClose} style={styles.roundButton} accessibilityLabel="Cerrar" hitSlop={8}>
            <Icon name="x" size={20} color={colors.textFlat} />
          </Pressable>
          <View style={styles.hintBubble}>
            <Text style={styles.hintText}>Mueve el mapa hasta tu puerta</Text>
          </View>
        </View>

        <View style={[styles.bottom, { paddingBottom: Math.max(insets.bottom, 16) }]}>
          <Pressable onPress={() => { void locate(true); }} style={styles.locate} disabled={locating}
            accessibilityRole="button" testID="location-use-gps">
            {locating ? <ActivityIndicator color={colors.primaryDeep} />
              : <Icon name="navigation" size={16} color={colors.primaryDeep} />}
            <Text style={styles.locateText}>Usar mi ubicación</Text>
          </Pressable>
          {failure ? (
            <Text style={styles.denied} testID="location-failure"
              onPress={failure === 'unavailable' ? undefined : openLocationSettings(failure)}>
              {FAILURE_COPY[failure]}
            </Text>
          ) : null}
          <KitButton testID="location-confirm" label="Confirmar ubicación" icon="check" disabled={!center}
            onPress={() => { if (center) onConfirm(center); }} />
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.neutralDark },
  waiting: { alignItems: 'center', justifyContent: 'center', gap: 10 },
  waitingText: { fontSize: 14, color: colors.text.secondary },
  pinWrap: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  // Lift the icon by half its height so its tip, not its middle, is the center.
  pin: { marginTop: -40 },
  top: { position: 'absolute', left: 16, right: 16, flexDirection: 'row', alignItems: 'center', gap: 10 },
  roundButton: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center', elevation: 3, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 4, shadowOffset: { width: 0, height: 2 } },
  hintBubble: { flex: 1, backgroundColor: colors.white, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 10, elevation: 3, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 4, shadowOffset: { width: 0, height: 2 } },
  hintText: { fontSize: 14, fontWeight: '600', color: colors.textFlat, textAlign: 'center' },
  bottom: { position: 'absolute', left: 0, right: 0, bottom: 0, backgroundColor: colors.white, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 16, gap: 10 },
  locate: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 10, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  locateText: { fontSize: 15, fontWeight: '600', color: colors.primaryDeep },
  denied: { fontSize: 13, color: colors.warning.text, textAlign: 'center' },
});
