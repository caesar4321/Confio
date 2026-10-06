import React from 'react';
import { Modal, Pressable, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';

export const REPORT_REASONS: Array<{ code: string; label: string }> = [
  { code: 'SCAM', label: 'Estafa o fraude' },
  { code: 'SPAM', label: 'Spam o publicidad' },
  { code: 'OFFENSIVE', label: 'Ofensivo o acoso' },
  { code: 'PERSONAL_DATA', label: 'Expone datos personales' },
  { code: 'OTHER', label: 'Otro motivo' },
];

type Props = {
  visible: boolean;
  title: string;
  onPick: (reason: string) => void;
  onClose: () => void;
};

/** Bottom sheet to pick why a Comunidad post or comment is being reported. */
export function ReportReasonSheet({ visible, title, onPick, onClose }: Props) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={() => {}}>
          <Text style={styles.sheetTitle}>{title}</Text>
          {REPORT_REASONS.map(({ code, label }) => (
            <Pressable
              key={code}
              style={({ pressed }) => [styles.reason, pressed && styles.reasonPressed]}
              onPress={() => onPick(code)}
              accessibilityRole="button"
            >
              <Text style={styles.reasonText}>{label}</Text>
              <Icon name="chevron-right" size={16} color={colors.textTertiary} />
            </Pressable>
          ))}
          <Pressable style={styles.cancel} onPress={onClose} accessibilityRole="button">
            <Text style={styles.cancelText}>Cancelar</Text>
          </Pressable>
        </Pressable>
      </Pressable>
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
    backgroundColor: colors.white,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 16,
    paddingTop: 20,
    paddingBottom: 32,
  },
  sheetTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.textFlat,
    marginBottom: 8,
  },
  reason: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  reasonPressed: {
    opacity: 0.6,
  },
  reasonText: {
    fontSize: 15,
    color: colors.textFlat,
  },
  cancel: {
    marginTop: 12,
    alignItems: 'center',
    paddingVertical: 12,
  },
  cancelText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.textSecondary,
  },
});
