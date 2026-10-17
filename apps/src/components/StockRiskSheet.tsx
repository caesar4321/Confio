import React, { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useMutation } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { ACKNOWLEDGE_GM_COMPLEX_PRODUCTS } from '../hooks/useGmMarket';

type Props = {
  visible: boolean;
  /** The disclosure as served (gmComplexProducts): what the person accepts
   * is exactly the text of `version`. */
  title: string;
  points: string[];
  version: number | null;
  /** Called with the token `beginAccept` returned when the person tapped:
   * the host compares it with its current flow, so a confirmation saved
   * after the sheet was dismissed and reopened never counts for the new one. */
  onAccepted: (token: number | undefined) => void;
  beginAccept?: () => number;
  onClose: () => void;
  /** Reload the disclosure, e.g. after the server says the text changed. */
  onRefresh: () => Promise<unknown>;
};

/**
 * Leveraged and inverse funds, confirmed once before the first purchase of
 * any of them. Selling never asks. The server refuses the purchase without
 * this confirmation, so the sheet is the only way through, never a formality.
 */
export function StockRiskSheet({ visible, title, points, version, onAccepted, beginAccept, onClose, onRefresh }: Props) {
  const [acknowledge, { loading: saving }] = useMutation(ACKNOWLEDGE_GM_COMPLEX_PRODUCTS);
  const [error, setError] = useState<string | null>(null);
  const ready = version !== null && points.length > 0;

  const accept = async () => {
    if (!ready) return;
    const token = beginAccept?.();
    setError(null);
    try {
      const { data } = await acknowledge({ variables: { version } });
      const result = data?.acknowledgeGmComplexProducts;
      if (!result?.success) {
        if (result?.error === 'OUTDATED_DISCLOSURE') {
          setError('El texto cambió. Léelo de nuevo antes de confirmar.');
          await onRefresh().catch(() => undefined);
        } else {
          setError('No pudimos guardar tu confirmación. Inténtalo de nuevo.');
        }
        return;
      }
      onAccepted(token);
    } catch {
      setError('No pudimos guardar tu confirmación. Revisa tu conexión.');
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.titleRow}>
            <Icon name="alert-triangle" size={18} color={colors.warning.icon} />
            <Text style={styles.title} accessibilityRole="header">
              {title || 'Antes de tu primer fondo apalancado o inverso'}
            </Text>
          </View>
          {!ready ? (
            <ActivityIndicator style={styles.loading} color={colors.primary} />
          ) : (
            <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
              {points.map((point) => (
                <View key={point} style={styles.pointRow}>
                  <View style={styles.bullet} />
                  <Text style={styles.pointText}>{point}</Text>
                </View>
              ))}
            </ScrollView>
          )}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Pressable
            style={[styles.accept, (!ready || saving) && styles.acceptDisabled]}
            onPress={() => { void accept(); }}
            disabled={!ready || saving}
            accessibilityRole="button"
          >
            {saving ? (
              <ActivityIndicator color={colors.white} />
            ) : (
              <Text style={styles.acceptText}>Entiendo los riesgos</Text>
            )}
          </Pressable>
          <Pressable style={styles.cancel} onPress={onClose} accessibilityRole="button">
            <Text style={styles.cancelText}>Ahora no</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(17, 24, 39, 0.45)',
    justifyContent: 'flex-end',
  },
  sheet: {
    maxHeight: '85%',
    backgroundColor: colors.white,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 28,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  title: {
    flex: 1,
    fontSize: 18,
    fontWeight: '700',
    color: colors.textFlat,
  },
  loading: {
    marginVertical: 24,
  },
  list: {
    marginTop: 14,
  },
  listContent: {
    gap: 12,
    paddingBottom: 4,
  },
  pointRow: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'flex-start',
  },
  bullet: {
    width: 6,
    height: 6,
    borderRadius: 3,
    marginTop: 7,
    backgroundColor: colors.warning.icon,
  },
  pointText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 20,
    color: colors.text.primary,
  },
  error: {
    marginTop: 10,
    fontSize: 13,
    color: colors.error.text,
  },
  accept: {
    marginTop: 18,
    minHeight: 50,
    borderRadius: 14,
    backgroundColor: colors.primaryDark,
    alignItems: 'center',
    justifyContent: 'center',
  },
  acceptDisabled: {
    opacity: 0.5,
  },
  acceptText: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.white,
  },
  cancel: {
    marginTop: 8,
    alignItems: 'center',
    paddingVertical: 10,
  },
  cancelText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.textSecondary,
  },
});
