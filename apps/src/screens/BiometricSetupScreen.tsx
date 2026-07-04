import React, { useCallback, useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking, Platform, Alert, AppState, AppStateStatus, ScrollView, StatusBar } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import MCIcon from 'react-native-vector-icons/MaterialCommunityIcons';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { RouteProp, useFocusEffect, useNavigation, useRoute } from '@react-navigation/native';
import { AuthStackParamList } from '../types/navigation';
import { useAuth } from '../contexts/AuthContext';
import { biometricAuthService } from '../services/biometricAuthService';
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { colors } from '../config/theme';

type BiometricRouteProp = RouteProp<AuthStackParamList, 'BiometricSetup'>;

export const BiometricSetupScreen = () => {
  const navigation = useNavigation();
  const insets = useSafeAreaInsets();
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
      biometricAuthService.invalidateCache();
      const supported = await biometricAuthService.isSupported();
      setSupportedHint(supported ? null : 'Tu dispositivo no tiene biometría; continuaremos automáticamente.');
      if (supported) {
        setError(null);
        setShowSettingsButton(false);
      }
      return supported;
    } catch (e) {
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

      // App has come to the foreground
      if (appState.current.match(/inactive|background/) && nextAppState === 'active') {
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
    const ok = await completeBiometricAndEnter();
    if (!ok) {
      setError(Platform.OS === 'ios'
        ? 'Activa tu biometría o código en los ajustes del dispositivo y vuelve a intentar.'
        : 'Activa tu biometría o código de acceso en los ajustes del dispositivo y vuelve a intentar.');
      setShowSettingsButton(true);
      setIsProcessing(false);
    }
  }, [completeBiometricAndEnter, isProcessing]);

  const handleBack = useCallback(() => {
    if (!isProcessing) {
      navigation.goBack();
    }
  }, [navigation, isProcessing]);

  const handleOpenSettings = useCallback(async () => {
                if (Platform.OS === 'android') {
                  // Show instructions first for Android
                  Alert.alert(
                    'Configurar Seguridad (Biometría o PIN)',
                    'Para activar la seguridad en tu dispositivo:\n\n1. Ve a Ajustes del dispositivo\n2. Busca "Seguridad" o "Bloqueo de pantalla"\n3. Configura tu "Huella digital", "Face Unlock" o "PIN / Patrón"\n4. Vuelve a Confío\n\nLa app detectará automáticamente que activaste la seguridad.',
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
                                return;
                              } catch (e) {

                                try {
                                  // Fallback to security settings
                                  await Linking.sendIntent('android.settings.SECURITY_SETTINGS');
                                  return;
                                } catch (e2) {

                                  try {
                                    // Fallback to general settings
                                    await Linking.sendIntent('android.settings.SETTINGS');
                                    return;
                                  } catch (e3) {
                                  }
                                }
                              }
                            }

                            // Final fallback: open app settings
                            await Linking.openSettings();
                          } catch (e) {
                            Alert.alert(
                              'No se pudo abrir ajustes',
                              'Por favor abre manualmente los Ajustes del dispositivo > Seguridad > Biometría',
                              [{ text: 'Entendido' }]
                            );
                          }
                        }
                      }
                    ]
                  );
                } else {
                  // iOS - show instructions then open settings
                  Alert.alert(
                    'Configurar Face ID / Touch ID / Código',
                    'Para activar la seguridad en tu iPhone:\n\n1. Ve a Ajustes\n2. Busca "Face ID y código" o "Touch ID y código"\n3. Configura tu biometría o código\n4. Vuelve a Confío\n\nLa app detectará automáticamente tu configuración.',
                    [
                      { text: 'Cancelar', style: 'cancel' },
                      {
                        text: 'Abrir ajustes',
                        onPress: async () => {
                          try {
                            // iOS can only open app settings, not specific system settings
                            await Linking.openSettings();
                          } catch (e) {
                          }
                        }
                      }
                    ]
                  );
                }
  }, []);

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primaryDark} />

      {/* Brand field: same grammar as the Auth screen — emerald gradient,
          one cropped coin ring, hero mark. */}
      <View style={[styles.brandField, { paddingTop: insets.top }]}>
        {/* absoluteFill only — width/height="100%" would resolve against the
            content box and stop 48px short of the padded bottom, exposing the
            flat container color as a hard seam. */}
        <Svg style={StyleSheet.absoluteFill}>
          <Defs>
            <SvgLinearGradient id="bioField" x1="0" y1="0" x2="1" y2="1">
              <Stop offset="0" stopColor={colors.primary} />
              <Stop offset="1" stopColor={colors.primaryDark} />
            </SvgLinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#bioField)" />
          <Circle cx="94%" cy="8%" r="120" stroke={colors.white} strokeWidth="28" strokeOpacity="0.10" fill="none" />
        </Svg>
        <TouchableOpacity
          onPress={handleBack}
          disabled={isProcessing}
          style={styles.backButton}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
          accessibilityRole="button"
          accessibilityLabel="Volver"
        >
          <Icon name="arrow-left" size={22} color={colors.white} />
        </TouchableOpacity>
        <View style={styles.fieldContent}>
          <View style={styles.heroBadge}>
            <MCIcon name="fingerprint" size={44} color={colors.white} />
          </View>
          <Text style={styles.fieldTitle} accessibilityRole="header">Activa la seguridad</Text>
          <Text style={styles.fieldSubtitle}>Tu huella o tu rostro es la llave</Text>
        </View>
      </View>

      {/* White sheet with the pitch and the action */}
      <ScrollView style={styles.sheet} contentContainerStyle={styles.sheetContent} showsVerticalScrollIndicator={false}>
        <Text style={styles.heading}>Protege tus operaciones sensibles</Text>
        <Text style={styles.body}>
          {Platform.OS === 'ios'
            ? 'Usaremos tu biometría (o tu código) para desbloquear Confío y confirmar envíos, pagos y otros movimientos críticos. Tus datos de seguridad nunca salen del dispositivo.'
            : 'Usaremos tu huella digital (o tu PIN/Patrón) para desbloquear Confío y confirmar envíos, pagos y otros movimientos críticos. Tus datos de seguridad nunca salen del dispositivo.'
          }
        </Text>

        <View style={styles.list}>
          <View style={styles.listItem}>
            <View style={styles.listIcon}>
              <Icon name="lock" size={16} color={colors.primaryDark} />
            </View>
            <Text style={styles.listText}>Evita accesos no autorizados si el teléfono cae en otras manos.</Text>
          </View>
          <View style={styles.listItem}>
            <View style={styles.listIcon}>
              <Icon name="send" size={16} color={colors.primaryDark} />
            </View>
            <Text style={styles.listText}>Confirma cada envío o pago con tu rostro o huella.</Text>
          </View>
          <View style={styles.listItem}>
            <View style={styles.listIcon}>
              <Icon name="check-circle" size={16} color={colors.primaryDark} />
            </View>
            <Text style={styles.listText}>Configuras solo una vez; seguimos usando el sistema seguro del dispositivo.</Text>
          </View>
        </View>

        <Text style={styles.hint}>
          {supportedHint ?? 'Si aún no tienes seguridad configurada, actívala en los ajustes del dispositivo y vuelve a intentar.'}
        </Text>

        {error && (
          <InlineBanner
            message={error}
            variant="error"
            onDismiss={() => setError(null)}
            style={styles.banner}
          />
        )}

        <Button
          title="Activar ahora"
          onPress={handleActivate}
          loading={isProcessing}
          disabled={isProcessing}
        />
        <Text style={styles.caption}>Necesario para mantener segura tu cuenta y tus transacciones.</Text>
        {showSettingsButton && (
          <Button
            title="Abrir ajustes de seguridad"
            variant="secondary"
            onPress={handleOpenSettings}
            style={styles.settingsButton}
          />
        )}
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.primaryDark,
  },
  brandField: {
    paddingBottom: 48,
    overflow: 'hidden',
  },
  backButton: {
    padding: 10,
    alignSelf: 'flex-start',
    marginLeft: 6,
    marginTop: 4,
  },
  fieldContent: {
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingBottom: 8,
  },
  heroBadge: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: 'rgba(255, 255, 255, 0.16)',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.35)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 14,
  },
  fieldTitle: {
    fontSize: 24,
    fontWeight: '800',
    color: colors.white,
    textAlign: 'center',
  },
  fieldSubtitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.primaryLight,
    marginTop: 6,
    textAlign: 'center',
  },
  sheet: {
    flex: 1,
    backgroundColor: colors.background,
    borderTopLeftRadius: 28,
    borderTopRightRadius: 28,
    marginTop: -28,
  },
  sheetContent: {
    padding: 24,
    paddingBottom: 40,
  },
  heading: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 8,
  },
  body: {
    fontSize: 15,
    color: colors.gray700,
    lineHeight: 22,
    marginBottom: 20,
  },
  list: {
    gap: 14,
    marginBottom: 20,
  },
  listItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  listIcon: {
    width: 32,
    height: 32,
    borderRadius: 10,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  listText: {
    flex: 1,
    fontSize: 14,
    color: colors.gray700,
    lineHeight: 20,
    paddingTop: 6,
  },
  hint: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
    marginBottom: 16,
  },
  banner: {
    marginBottom: 16,
  },
  caption: {
    textAlign: 'center',
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 10,
  },
  settingsButton: {
    marginTop: 16,
  },
});

export default BiometricSetupScreen;
