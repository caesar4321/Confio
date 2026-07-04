import React, { useEffect, useRef, useState } from 'react';
import { Alert, Linking, Modal, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner } from 'react-native-vision-camera';
import { launchImageLibrary } from 'react-native-image-picker';
import RNQRGenerator from 'rn-qr-generator';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

// Accepts raw 58-char addresses and algorand:// payment URIs.
const ALGORAND_ADDRESS = /[A-Z2-7]{58}/;

interface AddressScannerModalProps {
  visible: boolean;
  onClose: () => void;
  /** Called with the extracted 58-char Algorand address; modal closes itself. */
  onScanned: (address: string) => void;
}

/**
 * Minimal QR scanner for address entry (SendWithAddress and friends).
 * Unlike the Scan tab (payment invoices, server cross-checked), this only
 * extracts an Algorand address from the code and hands it back.
 */
export const AddressScannerModal: React.FC<AddressScannerModalProps> = ({ visible, onClose, onScanned }) => {
  const insets = useSafeAreaInsets();
  const device = useCameraDevice('back');
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [badCode, setBadCode] = useState(false);
  // Guard against the scanner firing multiple times for the same frame burst.
  const handledRef = useRef(false);

  useEffect(() => {
    if (!visible) {
      handledRef.current = false;
      setBadCode(false);
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
    const match = value.toUpperCase().match(ALGORAND_ADDRESS);
    if (match && !handledRef.current) {
      handledRef.current = true;
      onScanned(match[0]);
      onClose();
      return true;
    }
    return false;
  };

  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: (codes) => {
      if (handledRef.current) return;
      const value = codes[0]?.value || '';
      if (!acceptValue(value) && value) {
        setBadCode(true);
      }
    },
  });

  // Decode a QR from a photo (PHPicker / Android photo picker — no extra
  // permissions needed on modern OS versions).
  const handleGallery = async () => {
    try {
      const result = await launchImageLibrary({ mediaType: 'photo', selectionLimit: 1 });
      const uri = result.assets?.[0]?.uri;
      if (!uri) return; // user cancelled
      const detected = await RNQRGenerator.detect({ uri });
      const values = detected?.values || [];
      for (const value of values) {
        if (acceptValue(value)) return;
      }
      setBadCode(true);
    } catch {
      setBadCode(true);
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
          <Text style={styles.hint}>
            {badCode
              ? 'No se encontró una dirección Algorand en el código'
              : 'Apunta al código QR de la dirección'}
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
