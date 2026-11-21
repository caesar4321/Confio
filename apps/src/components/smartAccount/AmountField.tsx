import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Text, TextInput } from '../common/AppText';
import { sanitizeAmountInput } from '../../utils/numberLocale';
import { SA } from './tokens';

/** A dollar amount field: always "US$", the user's own decimal mark, two decimals. */
export function AmountField({ label, value, onChange, hint, error, testID }: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  hint?: string;
  error?: string;
  testID?: string;
}) {
  return (
    <View>
      <Text style={styles.label}>{label}</Text>
      <View style={[styles.box, error ? styles.boxError : null]}>
        <Text style={styles.prefix}>US$</Text>
        <TextInput
          value={value}
          onChangeText={(t) => onChange(sanitizeAmountInput(t, 2))}
          keyboardType="decimal-pad"
          placeholder="0"
          placeholderTextColor={SA.faint}
          style={styles.input}
          accessibilityLabel={`${label}, en dólares`}
          testID={testID}
        />
      </View>
      {error ? (
        <Text style={styles.error} accessibilityLiveRegion="polite">{error}</Text>
      ) : hint ? (
        <Text style={styles.hint}>{hint}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  label: { fontSize: 14, fontWeight: '600', color: SA.muted, marginBottom: 8 },
  box: {
    flexDirection: 'row', alignItems: 'center', minHeight: 64, borderRadius: 16, borderWidth: 1.5,
    borderColor: SA.line, backgroundColor: SA.card, paddingHorizontal: 16,
  },
  boxError: { borderColor: SA.noticeText },
  prefix: { fontSize: 24, fontWeight: '700', color: SA.muted, marginRight: 8 },
  input: { flex: 1, fontSize: 28, fontWeight: '700', color: SA.text, paddingVertical: 10 },
  hint: { fontSize: 13, lineHeight: 19, color: SA.muted, marginTop: 8 },
  error: { fontSize: 13, lineHeight: 19, color: SA.noticeText, marginTop: 8 },
});
