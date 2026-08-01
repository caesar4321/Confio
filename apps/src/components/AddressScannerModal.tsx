import React, { useEffect, useRef, useState } from 'react';
import { Alert, Linking, Modal, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner } from 'react-native-vision-camera';
import { launchImageLibrary } from 'react-native-image-picker';
import RNQRGenerator from 'rn-qr-generator';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import {
  AddressNetwork,
  NETWORK_LABEL,
  findAddress,
} from '../utils/addressNetwork';

export type { AddressNetwork };

interface AddressScannerModalProps {
  visible: boolean;
  onClose: () => void;
  /** Called with the extracted address; modal closes itself. */
  onScanned: (address: string) => void;
  /**
   * Which chain the caller is about to send on. REQUIRED on purpose: sending
   * to an address from the wrong chain burns the funds, so every call site
   * has to state its network rather than inherit a default.
   */
  network: AddressNetwork;
}

/**
 * Minimal QR scanner for address entry (SendWithAddress and friends).
 * Unlike the Scan tab (payment invoices, server cross-checked), this only
 * extracts an address for the requested network and hands it back — and
 * says so explicitly when the code holds the OTHER chain's address.
 */
export const AddressScannerModal: React.FC<AddressScannerModalProps> = ({ visible, onClose, onScanned, network }) => {
  const insets = useSafeAreaInsets();
  const device = useCameraDevice('back');
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [badCode, setBadCode] = useState(false);
  // Scanned fine, but it's the other chain's address — a different problem
  // from an unreadable code, and the one most likely to lose someone's money.
  const [wrongNetwork, setWrongNetwork] = useState(false);
  // Guard against the scanner firing multiple times for the same frame burst.
  const handledRef = useRef(false);

  useEffect(() => {
    if (!visible) {
      handledRef.current = false;
      setBadCode(false);
      setWrongNetwork(false);
      return;
    }
    (async () => {
      const status = await Camera.getCameraPermissionStatus();
      if (status === 'granted') {
        setHasPermission(true);
        return;
      }
      const requested = await Camera.requestCameraPermission();
      if (requested === 'granted') {
        setHasPermission(true);
      } else {
        setHasPermission(false);
        Alert.alert(
          'Permiso de cámara requerido',
          'Activa el acceso a la cámara en la configuración de tu dispositivo para escanear códigos QR.',
          [
            { text: 'Cancelar', style: 'cancel', onPress: onClose },
            { text: 'Abrir configuración', onPress: () => { Linking.openSettings(); onClose(); } },
          ],
        );
      }
    })();
  }, [visible, onClose]);

  const acceptValue = (value: string): boolean => {
    const address = findAddress(value, network);
    if (address && !handledRef.current) {
      handledRef.current = true;
      setWrongNetwork(false);
      onScanned(address);
      onClose();
      return true;
    }
    return false;
  };

  /** Name the failure: wrong chain reads very differently from unreadable. */
  const reportRejection = (value: string) => {
    const other: AddressNetwork = network === 'bsc' ? 'algorand' : 'bsc';
    if (findAddress(value, other)) {
      setWrongNetwork(true);
      setBadCode(false);
    } else {
      setBadCode(true);
    }
  };

  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: (codes) => {
      if (handledRef.current) return;
      const value = codes[0]?.value || '';
      if (!acceptValue(value) && value) {
        reportRejection(value);
      }
    },
  });

  // Decode a QR from a photo (PHPicker / Android photo picker — no extra
  // permissions needed on modern OS versions).
  const handleGallery = async () => {
    try {
      const result = await launchImageLibrary({ mediaType: 'photo', selectionLimit: 1 });
      if (result.didCancel) return;
      if (result.errorCode) {
        Alert.alert('No se pudo abrir la galería', result.errorMessage || result.errorCode);
        return;
      }
      const uri = result.assets?.[0]?.uri;
      if (!uri) return;
      const detected = await RNQRGenerator.detect({ uri });
      const values = detected?.values || [];
      for (const value of values) {
        if (acceptValue(value)) return;
      }
      reportRejection(values[0] || '');
    } catch (e: any) {
      // A TypeError here means the native module isn't in this binary yet
      // (app needs a full rebuild after adding the dependency) — say so
      // loudly instead of failing silently.
      const msg = String(e?.message || e);
      if (msg.includes('undefined') || msg.includes('null')) {
        Alert.alert(
          'Función no disponible',
          'Esta versión de la app no incluye el módulo de galería. Reinstala o reconstruye la app.',
        );
      } else {
        setBadCode(true);
      }
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.container}>
        {device && hasPermission ? (
          <Camera
            style={StyleSheet.absoluteFill}
            device={device}
            isActive={visible}
            codeScanner={codeScanner}
          />
        ) : (
          <View style={styles.permissionWrap}>
            <Icon name="camera-off" size={40} color={colors.text.light} />
            <Text style={styles.permissionText}>
              {hasPermission === false
                ? 'Sin acceso a la cámara'
                : 'Preparando la cámara…'}
            </Text>
          </View>
        )}

        {/* Frame overlay */}
        <View style={styles.overlay} pointerEvents="none">
          <View style={styles.frame} />
          <Text style={[styles.hint, wrongNetwork && styles.hintWarning]}>
            {wrongNetwork
              ? `Ese código tiene una dirección de ${NETWORK_LABEL[network === 'bsc' ? 'algorand' : 'bsc']}. `
                + `Para este envío necesitas una de ${NETWORK_LABEL[network]}.`
              : badCode
                ? `No se encontró una dirección de ${NETWORK_LABEL[network]} en el código`
                : `Apunta al código QR de la dirección (${NETWORK_LABEL[network]})`}
          </Text>
        </View>

        <TouchableOpacity
          style={[styles.closeButton, { top: insets.top + 12 }]}
          onPress={onClose}
          accessibilityRole="button"
          accessibilityLabel="Cerrar escáner"
        >
          <Icon name="x" size={22} color={colors.white} />
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.galleryButton, { bottom: insets.bottom + 28 }]}
          onPress={handleGallery}
          accessibilityRole="button"
          accessibilityLabel="Elegir un código QR desde la galería"
        >
          <Icon name="image" size={18} color={colors.white} />
          <Text style={styles.galleryButtonText}>Galería</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000000',
  },
  permissionWrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  permissionText: {
    color: colors.text.light,
    fontSize: 15,
  },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    justifyContent: 'center',
  },
  frame: {
    width: 240,
    height: 240,
    borderRadius: 24,
    borderWidth: 3,
    borderColor: colors.primary,
  },
  hintWarning: {
    // Literal, not colors.warning.*: those are tuned for light surfaces
    // (yellow-800 text on yellow-50). This sits on a live camera feed, so it
    // needs the light end of the ramp to stay legible.
    color: '#FDE68A',
  },
  hint: {
    marginTop: 20,
    color: colors.white,
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
    paddingHorizontal: 32,
    textShadowColor: 'rgba(0,0,0,0.6)',
    textShadowRadius: 4,
  },
  closeButton: {
    position: 'absolute',
    right: 16,
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: 'rgba(0,0,0,0.45)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  galleryButton: {
    position: 'absolute',
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: 'rgba(0,0,0,0.45)',
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 999,
  },
  galleryButtonText: {
    color: colors.white,
    fontSize: 15,
    fontWeight: '600',
  },
});
