import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, Modal, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { AppUpdatePolicy, fetchAppUpdatePolicy, openAppStore } from '../services/appUpdate';

// Re-ask on foreground at most this often, so a minimum raised while the
// app sits in the background still reaches users without a cold start.
const RECHECK_AFTER_MS = 30 * 60 * 1000;

/**
 * Below the server's minimum version the app is covered by a screen with
 * only "Actualizar"; below its latest version the update is offered once
 * per launch and can be put off. The policy is set per platform in the
 * admin (AppVersionPolicy).
 */
export const AppUpdateGate: React.FC = () => {
  const [policy, setPolicy] = useState<AppUpdatePolicy | null>(null);
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null);
  const lastCheckRef = useRef(0);

  const check = useCallback(async () => {
    lastCheckRef.current = Date.now();
    const next = await fetchAppUpdatePolicy();
    // A failed check keeps what we knew: an outage must not lift a
    // requirement the server already stated, nor invent one.
    if (next) setPolicy(next);
  }, []);

  useEffect(() => {
    check();
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'active' && Date.now() - lastCheckRef.current > RECHECK_AFTER_MS) check();
    });
    return () => subscription.remove();
  }, [check]);

  const required = policy?.status === 'update_required';
  const available = policy?.status === 'update_available' && dismissedVersion !== policy.latestVersion;
  if (!policy || (!required && !available)) return null;

  return (
    <Modal animationType="fade" transparent visible statusBarTranslucent onRequestClose={() => {
      // Android back: a required update cannot be skipped.
      if (!required) setDismissedVersion(policy.latestVersion);
    }}>
      <View style={[styles.backdrop, required && styles.backdropSolid]}>
        <View style={styles.card}>
          <View style={styles.iconWrap}>
            <Icon name="download" size={24} color={colors.primaryDark} />
          </View>
          <Text style={styles.title}>{required ? 'Actualiza Confío' : 'Nueva versión disponible'}</Text>
          <Text style={styles.body}>
            {policy.message || (required
              ? 'Esta versión ya no es compatible. Actualiza la app para seguir usando Confío.'
              : `Confío ${policy.latestVersion} ya está disponible con mejoras y correcciones.`)}
          </Text>
          <TouchableOpacity style={styles.primaryButton} onPress={openAppStore} accessibilityRole="button">
            <Text style={styles.primaryText}>Actualizar</Text>
          </TouchableOpacity>
          {!required && (
            <TouchableOpacity style={styles.secondaryButton} onPress={() => setDismissedVersion(policy.latestVersion)}
              accessibilityRole="button">
              <Text style={styles.secondaryText}>Ahora no</Text>
            </TouchableOpacity>
          )}
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
  backdropSolid: { backgroundColor: colors.white },
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
