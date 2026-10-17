import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Modal, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { AppUpdatePolicy, fetchAppUpdatePolicy, openAppStore } from '../services/appUpdate';

// Re-ask on foreground at most this often, so a release published while the
// app sits in the background still reaches users without a cold start.
const RECHECK_AFTER_MS = 30 * 60 * 1000;

/**
 * Suggests the update when the store has a newer version than this one
 * (AppVersionPolicy, set per platform in the admin). Always a pop-up the
 * user can put off — never a screen that blocks the app — and put off
 * once per launch per version.
 */
export const AppUpdatePrompt: React.FC = () => {
  const [policy, setPolicy] = useState<AppUpdatePolicy | null>(null);
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);
  const lastCheckRef = useRef(0);

  const check = useCallback(async () => {
    lastCheckRef.current = Date.now();
    const next = await fetchAppUpdatePolicy();
    if (next) setPolicy(next);
  }, []);

  useEffect(() => {
    check();
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'active' && Date.now() - lastCheckRef.current > RECHECK_AFTER_MS) check();
    });
    return () => subscription.remove();
  }, [check]);

  if (policy?.status !== 'update_available' || dismissedVersion === policy.latestVersion) return null;
  const dismiss = () => setDismissedVersion(policy.latestVersion);

  return (
    <Modal animationType="fade" transparent visible statusBarTranslucent onRequestClose={dismiss}>
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <View style={styles.iconWrap}>
            <Icon name="download" size={24} color={colors.primaryDark} />
          </View>
          <Text style={styles.title}>Nueva versión disponible</Text>
          <Text style={styles.body}>
            {policy.message || (policy.latestVersion
              ? `Confío ${policy.latestVersion} ya está disponible con mejoras y correcciones.`
              : 'Hay una nueva versión de Confío disponible con mejoras y correcciones.')}
          </Text>
          <TouchableOpacity style={styles.primaryButton} onPress={() => { dismiss(); openAppStore(); }}
            accessibilityRole="button">
            <Text style={styles.primaryText}>Actualizar</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryButton} onPress={dismiss} accessibilityRole="button">
            <Text style={styles.secondaryText}>Ahora no</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.55)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 16,
  },
  card: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
  },
  iconWrap: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.primaryLight,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: { fontSize: 20, fontWeight: '700', color: colors.dark, textAlign: 'center', marginBottom: 8 },
  body: { fontSize: 15, lineHeight: 22, color: colors.textSecondary, textAlign: 'center', marginBottom: 24 },
  primaryButton: {
    alignSelf: 'stretch',
    backgroundColor: colors.primaryDark,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  primaryText: { color: colors.white, fontSize: 16, fontWeight: '700' },
  secondaryButton: { alignSelf: 'stretch', paddingVertical: 14, alignItems: 'center', marginTop: 4 },
  secondaryText: { color: colors.textSecondary, fontSize: 15, fontWeight: '600' },
});
