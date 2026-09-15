import React, { useEffect, useRef, useState } from 'react';
import { Alert, Linking, Modal, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Camera, type CameraDevice, useCameraDevice, useCodeScanner } from 'react-native-vision-camera';
import { launchImageLibrary } from 'react-native-image-picker';
import RNQRGenerator from 'rn-qr-generator';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';

interface PaymentQrScannerModalProps {
  visible: boolean;
  onClose: () => void;
  /** Raw QR payload; the server validates it (EMVCo, country, fixed amount). */
  onScanned: (payload: string) => void;
  hint: string;
}

/**
 * Camera + gallery QR reader for local payment QR codes (Argentina's
 * interoperable QR). Deliberately dumb: unlike AddressScannerModal it knows no
 * format, because the payload's validity is a server decision.
 */
// One camera per opening. useCodeScanner always calls its latest callback, so a
// session captured in a shared callback would always look current; a camera
// keyed by session carries its own opening's number instead, and a late result
// from an earlier opening is recognised and dropped.
const SessionCamera: React.FC<{
  device: CameraDevice; active: boolean; session: number; onCode: (value: string, session: number) => void;
}> = ({ device, active, session, onCode }) => {
  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: codes => onCode(codes[0]?.value || '', session),
  });
  return <Camera style={StyleSheet.absoluteFill} device={device} isActive={active} codeScanner={codeScanner} />;
};

export const PaymentQrScannerModal: React.FC<PaymentQrScannerModalProps> = ({ visible, onClose, onScanned, hint }) => {
  const insets = useSafeAreaInsets();
  const device = useCameraDevice('back');
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const handledRef = useRef(false);
  // Each opening is a session: a gallery decode that finishes after the
  // scanner closed (or reopened) must not deliver a result.
  const sessionRef = useRef(0);
  const visibleRef = useRef(visible);
  const [session, setSession] = useState(0);
  useEffect(() => {
    visibleRef.current = visible;
    sessionRef.current += 1;
    setSession(sessionRef.current);
    return () => { visibleRef.current = false; };
  }, [visible]);

  useEffect(() => {
    if (!visible) {
      handledRef.current = false;
      return;
    }
    (async () => {
      if ((await Camera.getCameraPermissionStatus()) === 'granted') {
        setHasPermission(true);
        return;
      }
      if ((await Camera.requestCameraPermission()) === 'granted') {
        setHasPermission(true);
        return;
      }
      setHasPermission(false);
      Alert.alert(
        'Permiso de cámara requerido',
        'Activa el acceso a la cámara en la configuración de tu dispositivo para escanear códigos QR.',
        [
          { text: 'Cancelar', style: 'cancel', onPress: onClose },
          { text: 'Abrir configuración', onPress: () => { Linking.openSettings(); onClose(); } },
        ],
      );
    })();
  }, [visible, onClose]);

  const accept = (value: string, session = sessionRef.current) => {
    if (!value || handledRef.current || !visibleRef.current || session !== sessionRef.current) return;
    handledRef.current = true;
    onScanned(value);
    onClose();
  };

  const handleGallery = async () => {
    const session = sessionRef.current;
    try {
      const result = await launchImageLibrary({ mediaType: 'photo', selectionLimit: 1 });
      const uri = result.assets?.[0]?.uri;
      if (result.didCancel || !uri) return;
      const detected = await RNQRGenerator.detect({ uri });
      if (session !== sessionRef.current || !visibleRef.current) return; // closed meanwhile
      const value = detected?.values?.[0];
      if (value) {
        accept(value, session);
      } else {
        Alert.alert('Sin código QR', 'No encontramos un código QR en esa imagen.');
      }
    } catch {
      if (session !== sessionRef.current || !visibleRef.current) return; // closed meanwhile
      Alert.alert('No se pudo leer la imagen', 'Intenta de nuevo o escanea el código con la cámara.');
    }
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.container}>
        {device && hasPermission ? (
          <SessionCamera key={session} device={device} active={visible} session={session} onCode={accept} />
        ) : (
          <View style={styles.permissionWrap}>
            <Icon name="camera-off" size={40} color={colors.text.light} />
            <Text style={styles.permissionText}>
              {hasPermission === false ? 'Sin acceso a la cámara' : 'Preparando la cámara…'}
            </Text>
          </View>
        )}
        <View style={styles.overlay} pointerEvents="none">
          <View style={styles.frame} />
          <Text style={styles.hint}>{hint}</Text>
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

// Same geometry as AddressScannerModal so both scanners feel identical.
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000000' },
  permissionWrap: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  permissionText: { color: colors.text.light, fontSize: 15 },
  overlay: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  frame: { width: 240, height: 240, borderRadius: 24, borderWidth: 3, borderColor: colors.primary },
  hint: {
    marginTop: 20, color: colors.white, fontSize: 14, fontWeight: '600', textAlign: 'center', paddingHorizontal: 32,
    textShadowColor: 'rgba(0,0,0,0.6)', textShadowRadius: 4,
  },
  closeButton: {
    position: 'absolute', right: 16, width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(0,0,0,0.45)',
    alignItems: 'center', justifyContent: 'center',
  },
  galleryButton: {
    position: 'absolute', alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 8,
    backgroundColor: 'rgba(0,0,0,0.45)', paddingHorizontal: 20, paddingVertical: 12, borderRadius: 999,
  },
  galleryButtonText: { color: colors.white, fontSize: 15, fontWeight: '600' },
});
