import React, { useCallback, useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Linking, Platform, Alert, AppState, AppStateStatus } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { AuthStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { biometricAuthService } from '../services/biometricAuthService';

type BiometricRouteProp = RouteProp<AuthStackParamList, 'BiometricSetup'>;

export const BiometricSetupScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<BiometricRouteProp>();
  const origin = route.params?.origin || 'login';
  const { completeBiometricAndEnter } = useAuth();
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [supportedHint, setSupportedHint] = useState<string | null>(null);
  const [showSettingsButton, setShowSettingsButton] = useState(false);
  const appState = useRef(AppState.currentState);

  // Helper function to check biometric support
  const checkBiometricSupport = useCallback(async () => {
    try {
      console.log('[BiometricSetup] Checking biometric support...');
      biometricAuthService.invalidateCache();
      const supported = await biometricAuthService.isSupported();
      console.log('[BiometricSetup] Biometric supported:', supported);
      setSupportedHint(supported ? null : 'Tu dispositivo no tiene biometría; continuaremos automáticamente.');
      if (supported) {
        setError(null);
        setShowSettingsButton(false);
      }
      return supported;
    } catch (e) {
      console.error('[BiometricSetup] Error checking biometric support:', e);
      return false;
    }
  }, []);

  // Initial check on mount
  useEffect(() => {
    let alive = true;
    (async () => {
      if (alive) {
        await checkBiometricSupport();
      }
    })();
    return () => { alive = false; };
  }, [checkBiometricSupport]);

  // Listen for app state changes (e.g., returning from Settings)
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextAppState: AppStateStatus) => {
      console.log('[BiometricSetup] AppState changed:', appState.current, '->', nextAppState);

      // App has come to the foreground
      if (appState.current.match(/inactive|background/) && nextAppState === 'active') {
        console.log('[BiometricSetup] App returned to foreground, re-checking biometrics');
        checkBiometricSupport();
      }

      appState.current = nextAppState;
    });

    return () => {
      subscription.remove();
    };
  }, [checkBiometricSupport]);

  // Re-check support when screen regains navigation focus
  useFocusEffect(
    useCallback(() => {
      console.log('[BiometricSetup] Screen focused, re-checking biometrics');
      let alive = true;
      (async () => {
        if (alive) {
          await checkBiometricSupport();
        }
      })();
      return () => { alive = false; };
    }, [checkBiometricSupport])
  );

  const handleActivate = useCallback(async () => {
    if (isProcessing) return;
    setError(null);
    setShowSettingsButton(false);
    setIsProcessing(true);
    const ok = await completeBiometricAndEnter(origin);
    if (!ok) {
      setError('Activa Face ID / Touch ID o huella en los ajustes del dispositivo y vuelve a intentar.');
      setShowSettingsButton(true);
      setIsProcessing(false);
    }
  }, [completeBiometricAndEnter, origin, isProcessing]);

  const handleBack = useCallback(() => {
    if (!isProcessing) {
      navigation.goBack();
    }
  }, [navigation, isProcessing]);

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={handleBack} disabled={isProcessing} style={styles.backButton}>
          <Icon name="arrow-left" size={22} color="#111827" />
        </TouchableOpacity>
        <Text style={styles.title}>Activa tu biometría</Text>
        <View style={{ width: 22 }} />
      </View>

      <View style={styles.card}>
        <View style={styles.iconBadge}>
          <Icon name="shield" size={28} color="#10B981" />
        </View>
        <Text style={styles.heading}>Protege tus operaciones sensibles</Text>
        <Text style={styles.body}>
          Usaremos Face ID / Touch ID o huella para desbloquear Confío y confirmar envíos, pagos y otros movimientos críticos.
          Tus datos biométricos nunca salen del dispositivo: iOS/Android solo nos indica si la coincidencia fue exitosa.
        </Text>

        <View style={styles.list}>
          <View style={styles.listItem}>
            <Icon name="check" size={16} color="#10B981" />
            <Text style={styles.listText}>Evita accesos no autorizados si el teléfono cae en otras manos.</Text>
          </View>
          <View style={styles.listItem}>
            <Icon name="check" size={16} color="#10B981" />
            <Text style={styles.listText}>Confirma cada envío o pago con tu rostro o huella.</Text>
          </View>
          <View style={styles.listItem}>
            <Icon name="check" size={16} color="#10B981" />
            <Text style={styles.listText}>Configuras solo una vez; seguimos usando el sistema seguro del dispositivo.</Text>
          </View>
        </View>

        {supportedHint && (
          <Text style={styles.hint}>{supportedHint}</Text>
        )}
        {!supportedHint && (
          <Text style={styles.hint}>
            Si aún no tienes Face ID / Touch ID o huella configurada, actívalo en los ajustes del dispositivo y vuelve a intentar.
          </Text>
        )}

        {error && (
          <View style={styles.errorBox}>
            <Icon name="alert-triangle" size={16} color="#EF4444" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        )}

        <TouchableOpacity
          style={[styles.primaryButton, isProcessing && styles.primaryButtonDisabled]}
          onPress={handleActivate}
          disabled={isProcessing}
        >
          {isProcessing ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.primaryButtonText}>Activar ahora</Text>
          )}
        </TouchableOpacity>
        <Text style={styles.caption}>Necesario para mantener segura tu cuenta y tus transacciones.</Text>
        {showSettingsButton && (
          <TouchableOpacity
            style={styles.settingsButton}
            onPress={async () => {
              if (Platform.OS === 'android') {
                // Show instructions first for Android
                Alert.alert(
                  'Configurar biometría',
                  'Para activar la biometría en tu dispositivo:\n\n1. Ve a Ajustes del dispositivo\n2. Busca "Seguridad" o "Bloqueo de pantalla"\n3. Toca "Huella digital" o "Face Unlock"\n4. Configura tu biometría\n5. Vuelve a Confío\n\nLa app detectará automáticamente que activaste la biometría.',
                  [
                    { text: 'Cancelar', style: 'cancel' },
                    {
                      text: 'Abrir ajustes',
                      onPress: async () => {
                        try {
                          // Try using sendIntent for Android to open specific settings
                          if (Linking.sendIntent) {
                            try {
                              // Try biometric enrollment first (Android 10+)
                              await Linking.sendIntent('android.settings.BIOMETRIC_ENROLL');
                              console.log('[BiometricSetup] Opened biometric enrollment settings');
                              return;
                            } catch (e) {
                              console.log('[BiometricSetup] BIOMETRIC_ENROLL not available, trying security settings');

                              try {
                                // Fallback to security settings
                                await Linking.sendIntent('android.settings.SECURITY_SETTINGS');
                                console.log('[BiometricSetup] Opened security settings');
                                return;
                              } catch (e2) {
                                console.log('[BiometricSetup] SECURITY_SETTINGS not available, trying general settings');

                                try {
                                  // Fallback to general settings
                                  await Linking.sendIntent('android.settings.SETTINGS');
                                  console.log('[BiometricSetup] Opened general settings');
                                  return;
                                } catch (e3) {
                                  console.log('[BiometricSetup] All sendIntent attempts failed');
                                }
                              }
                            }
                          }

                          // Final fallback: open app settings
                          console.log('[BiometricSetup] Using Linking.openSettings fallback');
                          await Linking.openSettings();
                        } catch (e) {
                          console.error('[BiometricSetup] Failed to open any settings:', e);
                          Alert.alert(
                            'No se pudo abrir ajustes',
                            'Por favor abre manualmente los Ajustes del dispositivo > Seguridad > Biometría'
                          );
                        }
                      }
                    }
                  ]
                );
              } else {
                // iOS - show instructions then open settings
                Alert.alert(
                  'Configurar Face ID / Touch ID',
                  'Para activar la biometría en tu iPhone:\n\n1. Ve a Ajustes\n2. Busca "Face ID y código" o "Touch ID y código"\n3. Configura tu biometría\n4. Vuelve a Confío\n\nLa app detectará automáticamente que activaste la biometría.',
                  [
                    { text: 'Cancelar', style: 'cancel' },
                    {
                      text: 'Abrir ajustes',
                      onPress: async () => {
                        try {
                          // iOS can only open app settings, not specific system settings
                          await Linking.openSettings();
                        } catch (e) {
                          console.error('[BiometricSetup] Failed to open settings:', e);
                        }
                      }
                    }
                  ]
                );
              }
            }}
          >
            <Text style={styles.settingsButtonText}>Abrir ajustes biometría</Text>
          </TouchableOpacity>
        )}
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  backButton: {
    padding: 6,
  },
  title: {
    flex: 1,
    textAlign: 'center',
    fontSize: 17,
    fontWeight: '700',
    color: '#111827',
  },
  card: {
    margin: 16,
    padding: 20,
    backgroundColor: '#ffffff',
    borderRadius: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 3,
  },
  iconBadge: {
    width: 56,
    height: 56,
    borderRadius: 16,
    backgroundColor: '#ECFDF3',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  heading: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 8,
  },
  body: {
    fontSize: 15,
    color: '#374151',
    lineHeight: 22,
    marginBottom: 16,
  },
  list: {
    gap: 10,
    marginBottom: 16,
  },
  listItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  listText: {
    flex: 1,
    fontSize: 14,
    color: '#374151',
    lineHeight: 20,
  },
  hint: {
    fontSize: 13,
    color: '#6B7280',
    marginBottom: 12,
  },
  errorBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 10,
    borderRadius: 10,
    backgroundColor: '#FEF2F2',
    marginBottom: 12,
  },
  errorText: {
    flex: 1,
    color: '#B91C1C',
    fontSize: 13,
  },
  primaryButton: {
    backgroundColor: '#10B981',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    marginBottom: 8,
  },
  primaryButtonDisabled: {
    opacity: 0.6,
  },
  primaryButtonText: {
    color: '#ffffff',
    fontWeight: '700',
    fontSize: 15,
  },
  caption: {
    textAlign: 'center',
    fontSize: 12,
    color: '#6B7280',
  },
  settingsButton: {
    marginTop: 12,
    alignSelf: 'center',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#CBD5E1',
  },
  settingsButtonText: {
    color: '#0f172a',
    fontWeight: '600',
    fontSize: 13,
  },
});

export default BiometricSetupScreen;
