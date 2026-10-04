// "¿Qué fue este pago?" — optional category chips (design D11–D13, 2D/2E, R20).
//
// Prompt mode (success screens): asks only when the server says so
// (categoryPrompt: spending, not failed, not yet labeled, under the skip /
// dismiss limits). One tap saves a rule for the counterparty (past + future
// payments) and collapses to a confirmation with "Cambiar". "Ahora no" =
// skipped; leaving without answering = dismissed. A failed save reverts
// quietly and never blocks the screen's own "Listo".
//
// Inline mode (Sin categoría list): same chips for a known movement id,
// without the prompt bookkeeping.
import React, { useEffect, useRef, useState } from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import {
  CATEGORIZE_MOVEMENT, GET_CATEGORY_PROMPT, RECORD_CATEGORY_PROMPT, type CategoryKey,
} from '../apollo/monthSummary';
import { CATEGORY_META, CATEGORY_ORDER } from '../utils/monthSummary';
import { AnalyticsService } from '../services/analyticsService';

type Ref = {
  movementId?: string | null;
  internalId?: string | null;
  /** Live settlement status: a payment that fails after the prompt appeared
   *  hides it (not a user dismissal, nothing recorded). */
  status?: string | null;
};

const FAILED_STATUSES = new Set(['FAILED', 'REVERTED', 'CANCELLED']);

type ChipGridProps = {
  selected: CategoryKey | null;
  onPick: (category: CategoryKey) => void;
  disabled?: boolean;
};

export function ChipGrid({ selected, onPick, disabled = false }: ChipGridProps) {
  return (
    <View style={styles.chips}>
      {CATEGORY_ORDER.map((key) => {
        const isSelected = selected === key;
        return (
          <TouchableOpacity
            key={key}
            style={[styles.chip, isSelected && styles.chipSelected]}
            onPress={() => onPick(key)}
            disabled={disabled}
            accessibilityRole="button"
            accessibilityLabel={CATEGORY_META[key].label}
            accessibilityState={{ selected: isSelected, disabled }}
            testID={`category-chip-${key}`}
          >
            <Icon name={CATEGORY_META[key].icon} size={15} color={isSelected ? colors.white : colors.text.secondary} />
            <Text style={[styles.chipText, isSelected && styles.chipTextSelected]}>{CATEGORY_META[key].label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

/** Success-screen prompt. Renders nothing unless the server says to ask. */
export function CategoryPrompt({ movementId, internalId, status }: Ref) {
  const variables = { movementId: movementId ?? null, internalId: internalId ?? null };
  const enabled = Boolean(movementId || internalId);
  const { data } = useQuery<{ categoryPrompt: { shouldAsk: boolean; counterpartyName: string | null } }>(
    GET_CATEGORY_PROMPT, { variables, skip: !enabled, fetchPolicy: 'network-only' });
  const [categorize] = useMutation(CATEGORIZE_MOVEMENT);
  const [record] = useMutation(RECORD_CATEGORY_PROMPT);

  const [chosen, setChosen] = useState<CategoryKey | null>(null);
  const [editing, setEditing] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [failed, setFailed] = useState(false);
  // One save at a time: a slow earlier answer must never overwrite a later
  // choice, so picks and "Cambiar" wait until the pending save settles.
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const answered = useRef(false);
  const shown = useRef(false);
  const failedPayment = FAILED_STATUSES.has(String(status ?? '').toUpperCase());
  const shouldAsk = Boolean(data?.categoryPrompt?.shouldAsk) && !failedPayment;
  const name = data?.categoryPrompt?.counterpartyName || 'este destinatario';

  useEffect(() => {
    if (shouldAsk && !shown.current) {
      shown.current = true;
      AnalyticsService.logFunnelEvent('category_chip_shown');
    }
  }, [shouldAsk]);

  // Leaving the screen without answering or skipping = dismissed (D11).
  const latest = useRef({ shouldAsk, skipped, variables });
  latest.current = { shouldAsk, skipped, variables };
  useEffect(() => () => {
    const { shouldAsk: asked, skipped: wasSkipped, variables: vars } = latest.current;
    if (asked && !answered.current && !wasSkipped) {
      record({ variables: { ...vars, outcome: 'dismissed' } }).catch(() => undefined);
      AnalyticsService.logFunnelEvent('category_chip_dismissed');
    }
  }, [record]);

  if (!shouldAsk || skipped) return null;

  const pick = async (category: CategoryKey) => {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    const previous = chosen;
    setChosen(category);
    setEditing(false);
    setFailed(false);
    answered.current = true;
    try {
      const res = await categorize({ variables: { ...variables, category, applyTo: 'counterparty' } });
      if (!res.data?.categorizeMovement?.success) throw new Error(res.data?.categorizeMovement?.error || 'failed');
      AnalyticsService.logFunnelEvent('category_chip_answered', { category });
    } catch {
      setChosen(previous);
      answered.current = previous !== null;
      setFailed(true);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const skip = () => {
    setSkipped(true);
    record({ variables: { ...variables, outcome: 'skipped' } }).catch(() => undefined);
    AnalyticsService.logFunnelEvent('category_chip_skipped');
  };

  if (chosen && !editing) {
    return (
      <View style={styles.card} testID="category-confirmation">
        <Text style={styles.confirm}>
          <Text style={styles.confirmStrong}>{CATEGORY_META[chosen].label}</Text> · pagos a {name}
        </Text>
        <TouchableOpacity onPress={() => setEditing(true)} disabled={saving} hitSlop={10} accessibilityRole="button"
          accessibilityState={{ disabled: saving }} testID="category-change">
          <Text style={styles.change}>Cambiar</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.card} testID="category-prompt">
      <Text style={styles.question}>¿Qué fue este pago?</Text>
      <Text style={styles.hint}>Lo recordamos para los pagos a {name}.</Text>
      <ChipGrid selected={chosen} onPick={pick} disabled={saving} />
      {failed && <Text style={styles.failed}>No se guardó</Text>}
      {!chosen && (
        <TouchableOpacity onPress={skip} style={styles.skip} accessibilityRole="button" testID="category-skip">
          <Text style={styles.skipText}>Ahora no</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: 16, padding: 14, marginTop: 16 },
  question: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  hint: { fontSize: 12, color: colors.text.secondary, marginTop: 2, marginBottom: 10 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 44, paddingHorizontal: 14,
    borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.white,
  },
  chipSelected: { backgroundColor: colors.primaryDark, borderColor: colors.primaryDark },
  chipText: { fontSize: 14, fontWeight: '600', color: colors.text.primary },
  chipTextSelected: { color: colors.white },
  skip: { alignSelf: 'center', minHeight: 44, justifyContent: 'center', paddingHorizontal: 16 },
  skipText: { fontSize: 13, color: colors.text.secondary },
  failed: { fontSize: 12, color: colors.text.secondary, marginTop: 8 },
  confirm: { fontSize: 14, color: colors.text.primary, flexShrink: 1 },
  confirmStrong: { fontWeight: '700' },
  change: { fontSize: 14, fontWeight: '700', color: colors.primaryDark, marginTop: 6 },
});
