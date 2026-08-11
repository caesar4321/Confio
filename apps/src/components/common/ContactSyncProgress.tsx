import React from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { colors } from '../../config/theme';
import type { ContactSyncProgress as ContactSyncProgressState } from '../../services/contactService';

interface ContactSyncProgressProps {
  /** Null while the sync has not reported a step yet (or for a plain cache load). */
  progress: ContactSyncProgressState | null;
  /** Shown until the first progress report arrives. */
  fallbackLabel: string;
}

const PHASE_LABELS: Record<ContactSyncProgressState['phase'], string> = {
  reading: 'Leyendo tu agenda...',
  normalizing: 'Revisando tus contactos',
  matching: 'Buscando a tus amigos en Confío',
  saving: 'Guardando tus contactos...',
};

// LATAM Spanish groups thousands with a dot: 3.500 contactos.
export const formatContactCount = (value: number): string =>
  String(Math.max(0, Math.trunc(value))).replace(/\B(?=(\d{3})+(?!\d))/g, '.');

export const getContactSyncDetail = (progress: ContactSyncProgressState): string | null => {
  if (progress.total <= 0) return null;
  const processed = Math.min(progress.processed, progress.total);
  const noun = progress.phase === 'matching' ? 'números' : 'contactos';
  return `${formatContactCount(processed)} de ${formatContactCount(progress.total)} ${noun}`;
};

export const getContactSyncRatio = (progress: ContactSyncProgressState): number | null => {
  if (progress.total <= 0) return null;
  const ratio = progress.processed / progress.total;
  if (!Number.isFinite(ratio)) return null;
  return Math.min(1, Math.max(0, ratio));
};

/**
 * Determinate progress for a contact sync. Users with thousands of contacts
 * otherwise stare at a spinner with no way to tell running from stuck, so the
 * measurable steps report a count and the unmeasurable ones say what they are.
 */
export const ContactSyncProgress: React.FC<ContactSyncProgressProps> = ({ progress, fallbackLabel }) => {
  const label = progress ? PHASE_LABELS[progress.phase] : fallbackLabel;
  const detail = progress ? getContactSyncDetail(progress) : null;
  const ratio = progress ? getContactSyncRatio(progress) : null;

  return (
    <View
      style={styles.container}
      accessible
      accessibilityRole="progressbar"
      accessibilityLabel={detail ? `${label}. ${detail}` : label}
      accessibilityValue={
        ratio === null ? undefined : { min: 0, max: 100, now: Math.round(ratio * 100) }
      }
    >
      <ActivityIndicator size="large" color={colors.primary} />
      <Text style={styles.label}>{label}</Text>
      {detail && <Text style={styles.detail}>{detail}</Text>}
      {ratio !== null && (
        <View style={styles.track}>
          <View
            testID="contact-sync-progress-fill"
            style={[styles.fill, { width: `${Math.round(ratio * 100)}%` }]}
          />
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  label: {
    marginTop: 12,
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
  },
  detail: {
    marginTop: 4,
    fontSize: 13,
    color: colors.text.light,
    textAlign: 'center',
  },
  track: {
    marginTop: 12,
    width: 200,
    height: 6,
    borderRadius: 999,
    backgroundColor: colors.neutralDark,
    overflow: 'hidden',
  },
  fill: {
    height: '100%',
    borderRadius: 999,
    backgroundColor: colors.primary,
  },
});
