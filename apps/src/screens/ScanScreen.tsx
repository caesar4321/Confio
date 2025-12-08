import React, { useState, useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Dimensions, Alert, Platform, Linking } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner, CameraPermissionStatus } from 'react-native-vision-camera';
import type { Code } from 'react-native-vision-camera';
import Icon from 'react-native-vector-icons/Feather';
import { useAccount } from '../contexts/AccountContext';
import { useRoute, RouteProp, useNavigation, useFocusEffect } from '@react-navigation/native';
import { BottomTabParamList } from '../types/navigation';
import { useMutation } from '@apollo/client';
import { GET_INVOICE } from '../apollo/queries';

type ScanScreenRouteProp = RouteProp<BottomTabParamList, 'Scan'>;

export const ScanScreen = () => {
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [isFlashOn, setIsFlashOn] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [scannedSuccessfully, setScannedSuccessfully] = useState(false);
  const device = useCameraDevice('back');
  const { activeAccount } = useAccount();
  const route = useRoute<ScanScreenRouteProp>();
  const navigation = useNavigation();
  const scanMode = route.params?.mode;

  const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';

  // GraphQL mutations
  const [getInvoice] = useMutation(GET_INVOICE);

  // Debug logging
  console.log('ScanScreen - Account info:', {
    accountId: activeAccount?.id,
    accountType: activeAccount?.type,
    accountName: activeAccount?.name,
    isBusinessAccount,
    scanMode
  });

  console.log('ScanScreen - Debug info:', {
    hasPermission,
    device: device ? 'found' : 'not found',
    scanFrameSize,
    isFlashOn
  });

  useEffect(() => {
    checkPermission();
  }, []);

  const checkPermission = async () => {
    const permission = await Camera.getCameraPermissionStatus();
    if (permission === 'granted') {
      setHasPermission(true);
    } else if (permission === 'denied') {
      Alert.alert(
        'Camera Permission Required',
        'Please enable camera access in your device settings to use the QR code scanner.',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Open Settings', onPress: openSettings }
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

    console.log('QR Code scanned:', scannedData);

    // Show success indicator
    setScannedSuccessfully(true);

    // Parse the QR code data
    const qrMatch = scannedData.match(/^confio:\/\/pay\/(.+)$/);
    if (!qrMatch || !qrMatch[1]) {
      Alert.alert(
        'Invalid QR Code',
        'This QR code is not a valid Confío payment code.',
        [{ text: 'OK', style: 'default' }]
      );
      setScannedSuccessfully(false);
      return;
    }

    const invoiceId = qrMatch[1];
    console.log('Invoice ID extracted:', invoiceId);

    setIsProcessing(true);

    try {
      // SECURITY: Cross-check with server - don't trust QR code data
      // We only use the QR code to get the invoice ID, then fetch real data from server
      const { data: invoiceData } = await getInvoice({
        variables: { invoiceId }
      });

      if (!invoiceData?.getInvoice?.success) {
        const errors = invoiceData?.getInvoice?.errors || ['Invoice not found'];
        Alert.alert('Error', errors.join(', '), [{ text: 'OK' }]);
        return;
      }

      const invoice = invoiceData.getInvoice.invoice;
      console.log('Invoice details:', invoice);

      // Server-side validations:
      // 1. Invoice exists and is valid
      // 2. Invoice hasn't expired (server checks isExpired)
      // 3. Invoice is still in PENDING status
      if (invoice.isExpired) {
        Alert.alert('Invoice Expired', 'This payment request has expired.', [{ text: 'OK' }]);
        return;
      }

      // Client-side validations:
      // 1. User isn't paying their own invoice
      if (invoice.createdByUser?.id === activeAccount?.id) {
        Alert.alert('Cannot Pay Own Invoice', 'You cannot pay your own invoice.', [{ text: 'OK' }]);
        setScannedSuccessfully(false);
        return;
      }

      // Navigate to payment confirmation screen
      (navigation as any).navigate('PaymentConfirmation', {
        invoiceData: invoice
      });

    } catch (error) {
      console.error('Error processing QR code:', error);
      Alert.alert('Error', 'Failed to process the QR code. Please try again.', [{ text: 'OK' }]);
    } finally {
      setIsProcessing(false);
      setScannedSuccessfully(false);
    }
  };

  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: (codes: Code[]) => {
      if (codes.length > 0 && !isProcessing) {
        const scannedData = codes[0].value;
        handleQRCodeScanned(scannedData);
      }
    },
  });

  const toggleFlash = useCallback(() => {
    setIsFlashOn((current) => !current);
  }, []);

  // Removed prewarm HEAD /health pings

  const handleClose = () => {
    navigation.goBack();
  };

  if (hasPermission === null) {
    return (
      <View style={styles.container}>
        <Text style={styles.text}>Requesting camera permission...</Text>
      </View>
    );
  }

  if (hasPermission === false) {
    return (
      <View style={styles.container}>
        <Text style={styles.text}>No access to camera</Text>
        <TouchableOpacity style={styles.button} onPress={checkPermission}>
          <Text style={styles.buttonText}>Grant Permission</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (!device) {
    return (
      <View style={styles.container}>
        <Text style={styles.text}>No camera device found</Text>
      </View>
    );
  }



  return (
    <View style={styles.container}>
      <Camera
        style={styles.camera}
        device={device}
        isActive={true}
        codeScanner={codeScanner}
        torch={isFlashOn ? 'on' : 'off'}
        enableZoomGesture
      />

      {/* Move overlay outside Camera component */}
      <View style={styles.overlayAbsolute}>
        {/* Top overlay area with integrated header */}
        <View style={styles.topOverlay}>
          <View style={styles.headerControls}>
            <TouchableOpacity style={styles.closeButton} onPress={handleClose}>
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
                <Icon name="check-circle" size={60} color="#10B981" />
                <Text style={styles.successText}>Código QR detectado</Text>
              </View>
            )}
          </View>

          <View style={styles.sideOverlay} />
        </View>

        {/* Bottom overlay area */}
        <View style={styles.bottomOverlay}>
          {/* Scanning instruction */}
          <View style={styles.scanInstruction}>
            <Text style={styles.scanInstructionText}>Posiciona el código QR aquí</Text>
          </View>

          <Text style={styles.instructions}>
            {isProcessing
              ? 'Procesando código QR...'
              : isBusinessAccount
                ? scanMode === 'cobrar'
                  ? 'Escanea el código QR del cliente para cobrar'
                  : 'Escanea el código QR del proveedor para pagar'
                : 'Escanea un código QR de pago'
            }
          </Text>

          <TouchableOpacity style={styles.flashButton} onPress={toggleFlash}>
            <Icon name={isFlashOn ? "zap-off" : "zap"} size={24} color="#FFFFFF" />
          </TouchableOpacity>

          {isProcessing && (
            <View style={styles.loadingContainer}>
              <Text style={styles.loadingText}>Procesando...</Text>
            </View>
          )}
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
  overlay: {
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
    paddingTop: 50, // Account for status bar
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
    borderTopColor: '#00FF88',
    borderLeftColor: '#00FF88',
    top: -2,
    left: -2,
  },
  cornerBracketTopRight: {
    position: 'absolute',
    width: 35,
    height: 35,
    borderTopWidth: 4,
    borderRightWidth: 4,
    borderTopColor: '#00FF88',
    borderRightColor: '#00FF88',
    top: -2,
    right: -2,
  },
  cornerBracketBottomLeft: {
    position: 'absolute',
    width: 35,
    height: 35,
    borderBottomWidth: 4,
    borderLeftWidth: 4,
    borderBottomColor: '#00FF88',
    borderLeftColor: '#00FF88',
    bottom: -2,
    left: -2,
  },
  cornerBracketBottomRight: {
    position: 'absolute',
    width: 35,
    height: 35,
    borderBottomWidth: 4,
    borderRightWidth: 4,
    borderBottomColor: '#00FF88',
    borderRightColor: '#00FF88',
    bottom: -2,
    right: -2,
  },
  scanInstruction: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: 'rgba(0,0,0,0.8)',
    borderRadius: 20,
    marginBottom: 20,
  },
  scanInstructionText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '500',
    textAlign: 'center',
  },
  flashButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: 'rgba(0,0,0,0.8)',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 15,
  },
  instructions: {
    color: '#FFFFFF',
    fontSize: 16,
    textAlign: 'center',
    paddingHorizontal: 20,
  },
  text: {
    color: '#FFFFFF',
    fontSize: 16,
    textAlign: 'center',
    marginBottom: 16,
  },
  button: {
    backgroundColor: '#007AFF',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
  },
  buttonText: {
    color: '#FFFFFF',
    fontSize: 16,
  },
  loadingContainer: {
    marginTop: 10,
    padding: 10,
    backgroundColor: 'rgba(0,0,0,0.7)',
    borderRadius: 8,
  },
  loadingText: {
    color: '#FFFFFF',
    fontSize: 14,
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
