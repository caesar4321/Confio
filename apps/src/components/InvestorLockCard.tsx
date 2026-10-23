import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';

/** Why the viewer can't see this member's investments (server's `access`). */
export type InvestorAccess = 'self' | 'open' | 'target_hidden' | 'viewer_hidden' | 'viewer_unverified';

type Props = {
  access: InvestorAccess;
  busy?: boolean;
  onPublish?: () => void;
  onVerify?: () => void;
};

export const isLocked = (access: InvestorAccess | null | undefined) =>
  access === 'target_hidden' || access === 'viewer_hidden' || access === 'viewer_unverified';

/**
 * Portfolios are reciprocal: you see other investors' returns and positions
 * only while yours is public. The server enforces it; this explains it.
 */
export function InvestorLockCard({ access, busy, onPublish, onVerify }: Props) {
  if (access === 'target_hidden') {
    return (
      <View style={styles.card}>
        <Icon name="eye-off" size={20} color={colors.textSecondary} />
        <Text style={styles.title}>Portafolio privado</Text>
        <Text style={styles.body}>Este inversor eligió no mostrar sus inversiones.</Text>
      </View>
    );
  }
  const unverified = access === 'viewer_unverified';
  return (
    <View style={styles.card}>
      <Icon name="lock" size={20} color={colors.primaryDeep} />
      <Text style={styles.title}>Los portafolios son recíprocos</Text>
      <Text style={styles.body}>
        {unverified
          ? 'Verifica tu identidad y muestra tu portafolio para ver la rentabilidad y las posiciones de otros inversores.'
          : 'Haz público tu portafolio para ver la rentabilidad y las posiciones de otros inversores.'}
      </Text>
      <Pressable
        onPress={unverified ? onVerify : onPublish}
        disabled={busy}
        style={({ pressed }) => [styles.button, (pressed || busy) && styles.pressed]}
        accessibilityRole="button"
      >
        {busy ? (
          <ActivityIndicator color={colors.white} />
        ) : (
          <Text style={styles.buttonText}>{unverified ? 'Verificar identidad' : 'Hacer público'}</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 16,
    padding: 20,
    borderRadius: 16,
    alignItems: 'center',
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  title: { marginTop: 8, fontSize: 16, fontWeight: '700', color: colors.dark, textAlign: 'center' },
  body: { marginTop: 4, fontSize: 14, color: colors.textSecondary, textAlign: 'center' },
  button: {
    marginTop: 14,
    minWidth: 180,
    height: 42,
    paddingHorizontal: 20,
    borderRadius: 21,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dark,
  },
  buttonText: { fontSize: 15, fontWeight: '600', color: colors.white },
  pressed: { opacity: 0.7 },
});
