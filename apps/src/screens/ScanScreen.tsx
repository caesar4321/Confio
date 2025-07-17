import React, { useState, useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Dimensions, Alert, Platform, Linking } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner, CameraPermissionStatus } from 'react-native-vision-camera';
import type { Code } from 'react-native-vision-camera';
import Icon from 'react-native-vector-icons/Feather';
import { useAccountManager } from '../hooks/useAccountManager';
import { useScan } from '../contexts/ScanContext';

interface ScanScreenProps {
  isBusiness?: boolean;
}

export const ScanScreen = ({ isBusiness: isBusinessProp }: ScanScreenProps = {}) => {
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [isFlashOn, setIsFlashOn] = useState(false);
  const device = useCameraDevice('back');
  const { activeAccount } = useAccountManager();
  const { scanMode, setScanMode, clearScanMode } = useScan();
  
  // Use prop if provided, otherwise fall back to checking account type
  const isBusinessAccount = isBusinessProp ?? activeAccount?.type.toLowerCase() === 'business';

  // Debug logging
  console.log('ScanScreen - Account info:', {
    accountId: activeAccount?.id,
    accountType: activeAccount?.type,
    accountName: activeAccount?.name,
    isBusinessAccount,
    scanMode
  });

  useEffect(() => {
    checkPermission();
    
    // Clear scan mode when component unmounts
    return () => {
      clearScanMode();
    };
  }, [clearScanMode]);

  // Show mode selection for business accounts when they first enter the screen
  useEffect(() => {
    if (isBusinessAccount && !scanMode) {
      // For business accounts, show the mode selection immediately
      // This will be handled by the conditional render below
    }
  }, [isBusinessAccount, scanMode]);

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

  const codeScanner = useCodeScanner({
    codeTypes: ['qr'],
    onCodeScanned: (codes: Code[]) => {
      if (codes.length > 0) {
        // Handle scanned QR code data based on mode
        const scannedData = codes[0].value;
        console.log('Scanned:', scannedData);
        
        if (activeAccount?.type.toLowerCase() === 'business') {
          if (scanMode === 'cobrar') {
            // Handle payment collection
            console.log('Processing payment collection:', scannedData);
            // TODO: Implement payment collection logic
          } else if (scanMode === 'pagar') {
            // Handle payment to supplier
            console.log('Processing payment to supplier:', scannedData);
            // TODO: Implement payment to supplier logic
          }
        } else {
          // Handle personal account scanning (existing logic)
          console.log('Processing personal account scan:', scannedData);
        }
      }
    },
  });

  const toggleFlash = useCallback(() => {
    setIsFlashOn((current) => !current);
  }, []);

  // Reset mode when component mounts or when needed
  const resetMode = () => {
    clearScanMode();
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

  // Show mode selection for business accounts if no mode is set
  if (isBusinessAccount && !scanMode) {
    return (
      <View style={styles.container}>
        <View style={styles.modeSelectionContainer}>
          <Text style={styles.modeSelectionTitle}>Selecciona una opción</Text>
          
          <TouchableOpacity 
            style={[styles.modeButton, styles.cobrarButton]}
            onPress={() => setScanMode('cobrar')}
          >
            <Icon name="dollar-sign" size={24} color="#fff" />
            <Text style={styles.modeButtonText}>Cobrar</Text>
            <Text style={styles.modeButtonSubtext}>Recibir pagos de clientes</Text>
          </TouchableOpacity>

          <TouchableOpacity 
            style={[styles.modeButton, styles.pagarButton]}
            onPress={() => setScanMode('pagar')}
          >
            <Icon name="credit-card" size={24} color="#fff" />
            <Text style={styles.modeButtonText}>Pagar</Text>
            <Text style={styles.modeButtonSubtext}>Realizar pagos a proveedores</Text>
          </TouchableOpacity>
        </View>
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
      >
        <View style={styles.overlay}>
          <View style={styles.header}>
            <TouchableOpacity style={styles.closeButton}>
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

          <View style={styles.scanArea}>
            <View style={styles.scanFrame} />
          </View>

          <View style={styles.footer}>
            <TouchableOpacity style={styles.flashButton} onPress={toggleFlash}>
              <Icon name={isFlashOn ? "zap-off" : "zap"} size={24} color="#FFFFFF" />
            </TouchableOpacity>
            <Text style={styles.instructions}>
              {isBusinessAccount 
                ? scanMode === 'cobrar' 
                  ? 'Escanea el código QR del cliente para cobrar'
                  : 'Escanea el código QR del proveedor para pagar'
                : 'Escanea un código QR para enviar o recibir'
              }
            </Text>
          </View>
        </View>
      </Camera>
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
    backgroundColor: 'rgba(0,0,0,0.5)',
    width: '100%',
  },
  header: {
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
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
  scanArea: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scanFrame: {
    width: scanFrameSize,
    height: scanFrameSize,
    borderWidth: 2,
    borderColor: '#FFFFFF',
    borderRadius: 16,
  },
  footer: {
    padding: 24,
    alignItems: 'center',
  },
  flashButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  instructions: {
    color: '#FFFFFF',
    fontSize: 16,
    textAlign: 'center',
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
  modeSelectionContainer: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 24,
    margin: 20,
    width: '90%',
    maxWidth: 400,
  },
  modeSelectionTitle: {
    fontSize: 20,
    fontWeight: '600',
    textAlign: 'center',
    marginBottom: 24,
    color: '#1f2937',
  },
  modeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
  },
  cobrarButton: {
    backgroundColor: '#10b981', // Green
  },
  pagarButton: {
    backgroundColor: '#3b82f6', // Blue
  },
  modeButtonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
    marginLeft: 12,
    flex: 1,
  },
  modeButtonSubtext: {
    color: 'rgba(255, 255, 255, 0.8)',
    fontSize: 14,
    marginLeft: 12,
  },
}); 