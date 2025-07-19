import React, { useState, useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Dimensions, Alert, Platform, Linking } from 'react-native';
import { Camera, useCameraDevice, useCodeScanner, CameraPermissionStatus } from 'react-native-vision-camera';
import type { Code } from 'react-native-vision-camera';
import Icon from 'react-native-vector-icons/Feather';
import { useAccount } from '../contexts/AccountContext';
import { useRoute, RouteProp } from '@react-navigation/native';
import { BottomTabParamList } from '../types/navigation';

type ScanScreenRouteProp = RouteProp<BottomTabParamList, 'Scan'>;

export const ScanScreen = () => {
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [isFlashOn, setIsFlashOn] = useState(false);
  const device = useCameraDevice('back');
  const { activeAccount } = useAccount();
  const route = useRoute<ScanScreenRouteProp>();
  const scanMode = route.params?.mode;
  
  const isBusinessAccount = activeAccount?.type?.toLowerCase() === 'business';

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

}); 