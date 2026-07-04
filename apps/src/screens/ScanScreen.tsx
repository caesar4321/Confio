import React, { useState, useCallback, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Dimensions, Alert, Platform, Linking, AppState, AppStateStatus } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner, CameraPermissionStatus } from 'react-native-vision-camera';
import type { Code } from 'react-native-vision-camera';
import { launchImageLibrary } from 'react-native-image-picker';
import RNQRGenerator from 'rn-qr-generator';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { useAccount } from '../contexts/AccountContext';
import { useRoute, RouteProp, useNavigation, useFocusEffect, useIsFocused } from '@react-navigation/native';
import { BottomTabParamList } from '../types/navigation';
import { useMutation } from '@apollo/client';
import { GET_INVOICE } from '../apollo/queries';

type ScanScreenRouteProp = RouteProp<BottomTabParamList, 'Scan'>;

export const ScanScreen = () => {
  const insets = useSafeAreaInsets();
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [isFlashOn, setIsFlashOn] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [scannedSuccessfully, setScannedSuccessfully] = useState(false);
  const device = useCameraDevice('back');
  const { activeAccount } = useAccount();
  const route = useRoute<ScanScreenRouteProp>();
  const navigation = useNavigation();
  const scanMode = route.params?.mode;

  // Navigation focus state
  const isFocused = useIsFocused();
  // App foreground/background state
  const appState = useRef(AppState.currentState);
  const [isAppActive, setIsAppActive] = useState(appState.current === 'active');

  const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';

  // GraphQL mutations
  const [getInvoice] = useMutation(GET_INVOICE);

  // Debug logging

  // Monitor AppState to disable camera when app is in background
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextAppState) => {
      appState.current = nextAppState;
      setIsAppActive(nextAppState === 'active');
    });

    return () => {
      subscription.remove();
    };
  }, []);


  useEffect(() => {
    checkPermission();
  }, []);

  const checkPermission = async () => {
    const permission = await Camera.getCameraPermissionStatus();
    if (permission === 'granted') {
      setHasPermission(true);
    } else if (permission === 'denied') {
      Alert.alert(
        'Permiso de cámara requerido',        'Activa el acceso a la cámara en la configuración de tu dispositivo para escanear códigos QR.',
        [
          { text: 'Cancelar', style: 'cancel' },
          { text: 'Abrir configuración', onPress: openSettings }
        ]
      );
      setHasPermission(false);
    } else {
      const newPermission = await Camera.requestCameraPermission();
      setHasPermission(newPermission === 'granted');
    }
  };

  const openSettings = () => {
    if (Platform.OS === 'ios') {
      Linking.openURL('app-settings:');
    } else {
      Linking.openSettings();
    }
  };

  const handleQRCodeScanned = async (scannedData: string) => {
    if (isProcessing) return; // Prevent multiple processing


    // Show success indicator
    setScannedSuccessfully(true);

    // Parse the QR code data

    // 1. Check for Verification QR Code (Universal Link or URI Scheme)
    const verifyMatch = scannedData.match(/verify\/([a-zA-Z0-9]+)/);
    if (verifyMatch && verifyMatch[1]) {
      const hash = verifyMatch[1];
      setIsProcessing(true);
      setScannedSuccessfully(true);

      // Navigate to dedicated Verify screen
      setTimeout(() => {
        (navigation as any).navigate('VerifyTransaction', { hash });
        setIsProcessing(false);
        setScannedSuccessfully(false);
      }, 500);
      return;
    }

    // 2. Check for Payment QR Code (Custom Scheme OR Universal Link via HTTPS)
    const schemeMatch = scannedData.match(/^confio:\/\/pay\/(.+)$/);
    const httpsMatch = scannedData.match(/^https:\/\/confio\.lat\/pay\/(.+)$/);
    const validMatch = schemeMatch || httpsMatch;

    if (!validMatch || !validMatch[1]) {
      Alert.alert(
        'Código QR inválido',
        'Este código QR no es un código de pago válido de Confío.',
        [{ text: 'Entendido', style: 'default' }]
      );
      setScannedSuccessfully(false);
      return;
    }

    const invoiceId = validMatch[1];

    setIsProcessing(true);

    try {
      // SECURITY: Cross-check with server - don't trust QR code data
      // We only use the QR code to get the invoice ID, then fetch real data from server
      const { data: invoiceData } = await getInvoice({
        variables: { invoiceId: invoiceId as string }
      });

      if (!invoiceData?.getInvoice?.success) {
        const errors = invoiceData?.getInvoice?.errors || ['Factura no encontrada'];
        Alert.alert('Error', errors.join(', '), [{ text: 'Entendido' }]);
        return;
      }

      const invoice = invoiceData.getInvoice.invoice;

      // Server-side validations:
      // 1. Invoice exists and is valid
      // 2. Invoice hasn't expired (server checks isExpired)
      // 3. Invoice is still in PENDING status
      if (invoice.isExpired) {
        Alert.alert('Factura expirada', 'Esta solicitud de pago ha expirado.', [{ text: 'Entendido' }]);
        return;
      }

      // Client-side validations:
      // 1. User isn't paying their own invoice
      if (invoice.createdByUser?.id === activeAccount?.id) {
        Alert.alert('Aviso', 'No puedes pagar tu propia factura.', [{ text: 'Entendido' }]);
        setScannedSuccessfully(false);
        return;
      }

      // Navigate to payment confirmation screen
      (navigation as any).navigate('PaymentConfirmation', {
        invoiceData: invoice
      });

    } catch (error) {
      Alert.alert('Error', 'No se pudo procesar el código QR. Intenta de nuevo.', [{ text: 'Entendido' }]);
    } finally {
      setIsProcessing(false);
      setScannedSuccessfully(false);
    }
  };

  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: (codes: Code[]) => {
      // Only scan if focused, active, and not already processing
      if (codes.length > 0 && !isProcessing && isFocused && isAppActive) {
        const scannedData = codes[0].value;
        if (scannedData) {
          handleQRCodeScanned(scannedData);
        }
      }
    },
  });

  const toggleFlash = useCallback(() => {
    setIsFlashOn((current) => !current);
  }, []);

  // Decode a payment QR from a saved photo (screenshot sent by WhatsApp is
  // the common real-world case). Same pipeline as a live scan.
  const handleGallery = useCallback(async () => {
    if (isProcessing) return;
    try {
      const result = await launchImageLibrary({ mediaType: 'photo', selectionLimit: 1 });
      const uri = result.assets?.[0]?.uri;
      if (!uri) return; // user cancelled
      const detected = await RNQRGenerator.detect({ uri });
      const value = detected?.values?.[0];
      if (value) {
        handleQRCodeScanned(value);
      } else {
        Alert.alert('Sin código QR', 'No se encontró un código QR en la imagen.', [{ text: 'Entendido' }]);
      }
    } catch {
      Alert.alert('Sin código QR', 'No se pudo leer un código QR de la imagen.', [{ text: 'Entendido' }]);
    }
  }, [isProcessing]);

  // Removed prewarm HEAD /health pings

  const handleClose = () => {
    navigation.goBack();
  };

  if (hasPermission === null) {
    return (
      <View style={styles.container}>
        <Icon name="camera" size={40} color={colors.text.light} />
        <Text style={styles.text}>Solicitando permiso de cámara…</Text>
      </View>
    );
  }

  if (hasPermission === false) {
    return (
      <View style={styles.container}>
        <Icon name="camera-off" size={40} color={colors.text.light} />
        <Text style={styles.text}>Sin acceso a la cámara</Text>
        <Button
          title="Conceder permiso"
          onPress={checkPermission}
          style={{ minWidth: 200 }}
        />
      </View>
    );
  }

  if (!device) {
    return (
      <View style={styles.container}>
        <Icon name="camera-off" size={40} color={colors.text.light} />
        <Text style={styles.text}>No se encontró cámara</Text>
      </View>
    );
  }

  // Calculate if camera should be active
  // STRICT RULE: Only active if screen is focused AND app is in foreground AND not processing a scan
  // This prevents background scanning when payment modal is up
  const isActive = isFocused && isAppActive && !isProcessing;

  return (
    <View style={styles.container}>
      <Camera
        style={styles.camera}
        device={device}
        isActive={isActive}
        codeScanner={codeScanner}
        torch={isFlashOn && isActive ? 'on' : 'off'}
        enableZoomGesture
      />

      {/* Move overlay outside Camera component */}
      <View style={styles.overlayAbsolute}>
        {/* Top overlay area with integrated header */}
        <View style={[styles.topOverlay, { paddingTop: insets.top + 8 }]}>
          <View style={styles.headerControls}>
            <TouchableOpacity style={styles.closeButton} onPress={handleClose} accessibilityRole="button" accessibilityLabel="Cerrar escáner">
              <Icon name="x" size={24} color="#FFFFFF" />
            </TouchableOpacity>
            {isBusinessAccount && scanMode && (
              <View style={styles.modeIndicator}>
                <Text style={styles.modeIndicatorText}>
                  {scanMode === 'cobrar' ? 'Cobrar' : 'Pagar'}
                </Text>
              </View>
            )}
          </View>
        </View>

        {/* Middle area with scan frame */}
        <View style={styles.middleRow}>
          <View style={styles.sideOverlay} />

          <View style={styles.scanFrame}>
            {/* Corner brackets for better visual indication */}
            <View style={styles.cornerBracket} />
            <View style={styles.cornerBracketTopRight} />
            <View style={styles.cornerBracketBottomLeft} />
            <View style={styles.cornerBracketBottomRight} />

            {scannedSuccessfully && (
              <View style={styles.successOverlay}>
                <Icon name="check-circle" size={60} color={colors.primaryDark} />
                <Text style={styles.successText}>Código QR detectado</Text>
              </View>
            )}
          </View>

          <View style={styles.sideOverlay} />
        </View>

        {/* Bottom overlay area: ONE instruction line + the two tools */}
        <View style={styles.bottomOverlay}>
          <Text style={styles.instructions}>
            {isProcessing
              ? 'Procesando código QR…'
              : isBusinessAccount
                ? scanMode === 'cobrar'
                  ? 'Escanea el código QR del cliente para cobrar'
                  : 'Escanea el código QR del proveedor para pagar'
                : 'Escanea un código QR de pago'
            }
          </Text>

          <View style={styles.toolsRow}>
            <TouchableOpacity style={styles.toolButton} onPress={toggleFlash} accessibilityRole="button" accessibilityLabel={isFlashOn ? "Apagar linterna" : "Encender linterna"}>
              <Icon name={isFlashOn ? "zap-off" : "zap"} size={22} color={colors.white} />
            </TouchableOpacity>
            <TouchableOpacity style={styles.toolButton} onPress={handleGallery} accessibilityRole="button" accessibilityLabel="Elegir un código QR desde la galería">
              <Icon name="image" size={22} color={colors.white} />
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </View>
  );
};

const { width } = Dimensions.get('window');
const scanFrameSize = width * 0.7;

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000000',
    justifyContent: 'center',
    alignItems: 'center',
  },
  camera: {
    flex: 1,
    width: '100%',
  },
  overlayAbsolute: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    flex: 1,
    width: '100%',
    height: '100%',
  },
  closeButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modeIndicator: {
    backgroundColor: 'rgba(0,0,0,0.7)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  modeIndicatorText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  topOverlay: {
    flex: 0.7,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'flex-start',
  },
  headerControls: {
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  middleRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  sideOverlay: {
    flex: 1,
    height: scanFrameSize,
    backgroundColor: 'rgba(0,0,0,0.7)',
  },
  bottomOverlay: {
    flex: 1.3,
    backgroundColor: 'rgba(0,0,0,0.7)',
    alignItems: 'center',
    justifyContent: 'flex-start',
    paddingTop: 15,
    paddingBottom: 20,
  },
  scanFrame: {
    width: scanFrameSize,
    height: scanFrameSize,
    position: 'relative',
    justifyContent: 'center',
    alignItems: 'center',
  },
  cornerBracket: {
    position: 'absolute',
    width: 35,
    height: 35,
    borderTopWidth: 4,
    borderLeftWidth: 4,
    borderTopColor: colors.primary,
    borderLeftColor: colors.primary,
    top: -2,
    left: -2,
  },
  cornerBracketTopRight: {
    position: 'absolute',
    width: 35,
    height: 35,
    borderTopWidth: 4,
    borderRightWidth: 4,
    borderTopColor: colors.primary,
    borderRightColor: colors.primary,
    top: -2,
    right: -2,
  },
  cornerBracketBottomLeft: {
    position: 'absolute',
    width: 35,
    height: 35,
    borderBottomWidth: 4,
    borderLeftWidth: 4,
    borderBottomColor: colors.primary,
    borderLeftColor: colors.primary,
    bottom: -2,
    left: -2,
  },
  cornerBracketBottomRight: {
    position: 'absolute',
    width: 35,
    height: 35,
    borderBottomWidth: 4,
    borderRightWidth: 4,
    borderBottomColor: colors.primary,
    borderRightColor: colors.primary,
    bottom: -2,
    right: -2,
  },
  toolsRow: {
    flexDirection: 'row',
    gap: 20,
    marginTop: 20,
  },
  toolButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: 'rgba(0,0,0,0.8)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  instructions: {
    color: '#FFFFFF',
    fontSize: 16,
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  text: {
    color: colors.white,
    fontSize: 16,
    textAlign: 'center',
    marginTop: 12,
    marginBottom: 16,
  },

  successOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.7)',
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1,
  },
  successText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
    marginTop: 10,
    textAlign: 'center',
  },

}); 
