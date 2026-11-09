import React from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { formatSmallAmount } from '../utils/savingsFormat';
import { FeeReferralSummary } from '../hooks/useFeeReferralSummary';

/** The permanent way into "Mis comisiones": always shown (it does not wait
 *  for the summary), with this month's total once it is known. */
export const CommissionsEntryRow: React.FC<{
  summary: FeeReferralSummary | null;
  onPress: () => void;
}> = ({ summary, onPress }) => {
  const waiting = summary?.waitingCount ?? 0;
  const subtitle = !summary
    ? 'Cuánto ganas y quién falta por verificar'
    : waiting > 0
      ? `${waiting} ${waiting === 1 ? 'invitado falta' : 'invitados faltan'} por verificar`
      : `${summary.friendCount} ${summary.friendCount === 1 ? 'invitado' : 'invitados'}`;
  return (
    <TouchableOpacity
      style={styles.row}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel="Mis comisiones"
    >
      <View style={styles.icon}>
        <Icon name="dollar-sign" size={18} color={colors.primaryDark} />
      </View>
      <View style={styles.text}>
        <Text style={styles.title}>Mis comisiones</Text>
        <Text style={styles.subtitle} numberOfLines={1}>{subtitle}</Text>
      </View>
      {summary && (
        <View style={styles.amountBlock}>
          <Text style={styles.amount}>US${formatSmallAmount(Number(summary.monthTotalUsd) || 0)}</Text>
          <Text style={styles.subtitle}>este mes</Text>
        </View>
      )}
      <Icon name="chevron-right" size={18} color={colors.primaryDark} />
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: 12,
    paddingHorizontal: 14,
    gap: 10,
  },
  icon: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.primarySoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: { flex: 1 },
  title: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  subtitle: { fontSize: 12, color: colors.text.secondary, marginTop: 1 },
  amountBlock: { alignItems: 'flex-end' },
  amount: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
});
