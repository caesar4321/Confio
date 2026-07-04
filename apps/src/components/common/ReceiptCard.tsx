import React from 'react';
import { StyleSheet, Text, View, ViewStyle } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../../config/theme';

export interface ReceiptItem {
  label: string;
  value: string;
  /** Tints the value (and icon) and bolds it — e.g. colors.success for Estado */
  color?: string;
  /** Feather icon rendered before the value */
  icon?: string;
}

/**
 * The compact bordered detail card that accompanies SuccessHero — the same
 * row grammar as the dedicated success screens (Payment/Transaction/
 * BusinessPayment), packaged for the in-flow successes (Convert/Retirar/
 * Buy/Sell) where rows are simple label/value pairs.
 */
export const ReceiptCard: React.FC<{ items: ReceiptItem[]; style?: ViewStyle }> = ({ items, style }) => (
  <View style={[styles.card, style]}>
    {items.map((item, index) => (
      <View key={item.label} style={[styles.row, index === items.length - 1 && styles.rowLast]}>
        <Text style={styles.label}>{item.label}</Text>
        <View style={styles.inline}>
          {item.icon ? <Icon name={item.icon} size={15} color={item.color || colors.text.primary} /> : null}
          <Text
            style={[styles.value, item.color ? { color: item.color, fontWeight: '600' } : null]}
            numberOfLines={1}
          >
            {item.value}
          </Text>
        </View>
      </View>
    ))}
  </View>
);

const styles = StyleSheet.create({
  card: {
    alignSelf: 'stretch',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 16,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 13,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    gap: 12,
  },
  rowLast: {
    borderBottomWidth: 0,
  },
  label: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  inline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexShrink: 1,
  },
  value: {
    fontSize: 14,
    color: colors.text.primary,
    fontWeight: '500',
    flexShrink: 1,
    textAlign: 'right',
  },
});
