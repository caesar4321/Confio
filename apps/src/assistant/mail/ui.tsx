import React from 'react';
import { Pressable, StyleSheet } from 'react-native';

import { Text } from '../../components/common/AppText';
import { colors } from '../../config/theme';

type Press = { label: string; onPress: () => void; disabled?: boolean };

export const Action = ({ label, onPress, disabled }: Press) => (
  <Pressable
    style={[styles.button, disabled && styles.disabled]}
    onPress={onPress}
    disabled={disabled}
    accessibilityRole="button"
    accessibilityState={{ disabled: !!disabled }}
  >
    <Text style={styles.buttonText}>{label}</Text>
  </Pressable>
);

export const Link = ({ label, onPress, disabled }: Press) => (
  <Pressable style={styles.linkButton} onPress={onPress} disabled={disabled} accessibilityRole="button">
    <Text style={styles.link}>{label}</Text>
  </Pressable>
);

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 20 },
  title: { fontSize: 20, fontWeight: '700', color: colors.textFlat },
  close: { width: 52, height: 52, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  heading: { fontSize: 17, fontWeight: '700', color: colors.textFlat, marginTop: 24, marginBottom: 4 },
  paragraph: { fontSize: 15, color: colors.gray600, marginTop: 10 },
  label: { fontSize: 13, fontWeight: '600', color: colors.textSecondary, marginTop: 14, marginBottom: 4 },
  detail: { fontSize: 13, color: colors.textSecondary },
  value: { fontSize: 15, color: colors.textFlat },
  recipient: { fontSize: 16, fontWeight: '700', color: colors.textFlat },
  warning: { fontSize: 14, color: colors.warning.text, backgroundColor: colors.warning.background, borderRadius: 10, padding: 10, marginTop: 8 },
  message: { fontSize: 14, color: colors.textFlat, marginTop: 14 },
  input: {
    minHeight: 44,
    borderRadius: 12,
    backgroundColor: colors.neutralDark,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    color: colors.textFlat,
    marginTop: 6,
  },
  multiline: { minHeight: 96, textAlignVertical: 'top' },
  row: { borderBottomWidth: 1, borderBottomColor: colors.borderLight, paddingVertical: 12 },
  rowTitle: { fontSize: 15, fontWeight: '600', color: colors.textFlat },
  links: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 18 },
  button: {
    minHeight: 48,
    borderRadius: 14,
    backgroundColor: colors.successText,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 12,
    marginTop: 14,
  },
  buttonText: { color: colors.white, fontSize: 15, fontWeight: '700' },
  disabled: { opacity: 0.45 },
  linkButton: { minHeight: 44, justifyContent: 'center' },
  link: { color: colors.successText, fontSize: 14, fontWeight: '600' },
  entry: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 8 },
  entryLabel: { flex: 1, fontSize: 15, color: colors.textFlat },
});
