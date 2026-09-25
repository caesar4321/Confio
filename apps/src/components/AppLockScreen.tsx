import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { colors } from '../config/theme';

interface AppLockScreenProps {
  visible: boolean;
  onUnlock: () => Promise<boolean>;
  onSignOut: () => Promise<void>;
}

/**
 * Shown when the biometric / device-passcode unlock fails or is cancelled.
 * The session stays in the Keychain, so the user can simply retry instead of
 * being sent back through Google/Apple sign-in.
 *
 * A plain overlay, not a <Modal>: locking unmounts Main (dismissing every
 * screen modal), and on iOS a <Modal> silently fails to present while another
 * one is still up.
 */
export function AppLockScreen({ visible, onUnlock, onSignOut }: AppLockScreenProps) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // Stays mounted across lock sessions; don't carry a previous failure over.
  useEffect(() => {
    if (!visible) setFailed(false);
  }, [visible]);

  const handleUnlock = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const ok = await onUnlock();
      setFailed(!ok);
    } finally {
      setBusy(false);
    }
  };

  const handleSignOut = () => {
    Alert.alert(
      '¿Usar otra cuenta?',
      'Tendrás que iniciar sesión de nuevo con Google o Apple.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Continuar',
          style: 'destructive',
          onPress: () => { void onSignOut(); },
        },
      ],
    );
  };

  const methodLabel = Platform.OS === 'ios'
    ? 'Face ID, Touch ID o tu código'
    : 'tu huella, PIN o patrón';

  if (!visible) return null;

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Image
          source={require('../assets/png/CONFIO.png')}
          style={styles.logo}
          resizeMode="contain"
        />
        <View style={styles.iconCircle}>
          <Icon name="lock" size={28} color={colors.primaryDark} />
        </View>
        <Text style={styles.title}>Confío está bloqueado</Text>
        <Text style={styles.subtitle}>
          Usa {methodLabel} para continuar. Tu sesión sigue activa.
        </Text>
        {failed && (
          <Text style={styles.error}>
            No pudimos verificar tu identidad. Inténtalo de nuevo.
          </Text>
        )}
      </View>

      <View style={styles.actions}>
        <TouchableOpacity
          style={[styles.primaryButton, busy && styles.buttonDisabled]}
          onPress={handleUnlock}
          disabled={busy}
          accessibilityRole="button"
        >
          {busy ? (
            <ActivityIndicator color={colors.white} />
          ) : (
            <Text style={styles.primaryButtonText}>Desbloquear</Text>
          )}
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.secondaryButton}
          onPress={handleSignOut}
          disabled={busy}
          accessibilityRole="button"
        >
          <Text style={styles.secondaryButtonText}>Usar otra cuenta</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 20,
    backgroundColor: colors.background,
    paddingHorizontal: 24,
    paddingTop: 96,
    paddingBottom: 48,
    justifyContent: 'space-between',
  },
  content: {
    alignItems: 'center',
  },
  logo: {
    width: 72,
    height: 72,
    marginBottom: 40,
  },
  iconCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 20,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.textFlat,
    marginBottom: 8,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 15,
    lineHeight: 22,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  error: {
    marginTop: 16,
    fontSize: 14,
    color: colors.error.text,
    textAlign: 'center',
  },
  actions: {
    gap: 12,
  },
  primaryButton: {
    backgroundColor: colors.primaryDark,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.7,
  },
  primaryButtonText: {
    color: colors.white,
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    paddingVertical: 12,
    alignItems: 'center',
  },
  secondaryButtonText: {
    color: colors.textSecondary,
    fontSize: 15,
    fontWeight: '500',
  },
});
