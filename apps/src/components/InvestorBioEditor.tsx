import React, { useEffect, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { useMutation } from '@apollo/client';
import { useIsFocused } from '@react-navigation/native';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { UPDATE_INVESTOR_BIO } from '../apollo/mutations';
import { CommunityRulesSheet } from './CommunityRulesSheet';

const MAX = 140;

type Props = {
  visible: boolean;
  initial: string;
  onClose: () => void;
  onSaved: (bio: string) => void;
};

/** One line about you as an investor. Reviewed by AI before it is saved. */
export function InvestorBioEditor({ visible, initial, onClose, onSaved }: Props) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [rulesOpen, setRulesOpen] = useState(false);
  // Hidden (draft kept) while another screen is on top, e.g. the full Terms.
  const focused = useIsFocused();
  const [save, { loading }] = useMutation(UPDATE_INVESTOR_BIO);

  useEffect(() => {
    if (visible) {
      setValue(initial);
      setError(null);
    }
  }, [visible, initial]);

  const submit = async () => {
    setError(null);
    try {
      const { data } = await save({ variables: { bio: value } });
      const result = data?.updateInvestorBio;
      if (result?.rulesRequired) {
        // Shown to other members: accept the community rules, then it saves.
        setRulesOpen(true);
        return;
      }
      if (!result?.success) {
        setError(result?.error || 'No pudimos guardar tu descripción.');
        return;
      }
      onSaved(result.bio ?? '');
    } catch {
      setError('No pudimos guardar tu descripción. Revisa tu conexión.');
    }
  };

  return (
    <Modal visible={visible && focused} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.backdrop}>
        <View style={styles.sheet}>
          <Text style={styles.title}>Tu descripción</Text>
          <Text style={styles.hint}>Cuenta en una línea cómo inviertes. No incluyas contactos ni enlaces.</Text>
          <TextInput
            value={value}
            onChangeText={(text) => setValue(text.slice(0, MAX))}
            placeholder="Ej.: Invierto a largo plazo en tecnología"
            placeholderTextColor={colors.muted}
            style={styles.input}
            multiline
            maxLength={MAX}
            autoFocus
            editable={!loading}
            accessibilityLabel="Descripción"
          />
          <Text style={styles.counter}>{`${value.length}/${MAX}`}</Text>
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <View style={styles.actions}>
            <Pressable onPress={onClose} disabled={loading} style={[styles.button, styles.secondary]} accessibilityRole="button">
              <Text style={styles.secondaryText}>Cancelar</Text>
            </Pressable>
            <Pressable
              onPress={() => { void submit(); }}
              disabled={loading}
              style={[styles.button, styles.primary, loading && styles.busy]}
              accessibilityRole="button"
            >
              {loading ? <ActivityIndicator color={colors.white} /> : <Text style={styles.primaryText}>Guardar</Text>}
            </Pressable>
          </View>
          {loading ? <Text style={styles.reviewing}>Revisando tu descripción…</Text> : null}
        </View>
      </KeyboardAvoidingView>
      <CommunityRulesSheet
        visible={rulesOpen}
        onAccepted={() => {
          setRulesOpen(false);
          void submit();
        }}
        onClose={() => setRulesOpen(false)}
      />
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(17,24,39,0.4)' },
  sheet: { backgroundColor: colors.background, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20, paddingBottom: 32 },
  title: { fontSize: 18, fontWeight: '700', color: colors.dark },
  hint: { marginTop: 4, fontSize: 13, color: colors.textSecondary },
  input: {
    marginTop: 14,
    minHeight: 72,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    fontSize: 16,
    color: colors.dark,
    textAlignVertical: 'top',
  },
  counter: { marginTop: 6, alignSelf: 'flex-end', fontSize: 12, color: colors.textSecondary },
  error: { marginTop: 8, fontSize: 13, color: colors.error.text },
  actions: { marginTop: 16, flexDirection: 'row', gap: 10 },
  button: { flex: 1, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  primary: { backgroundColor: colors.dark },
  primaryText: { fontSize: 15, fontWeight: '600', color: colors.white },
  secondary: { backgroundColor: colors.neutralDark },
  secondaryText: { fontSize: 15, fontWeight: '600', color: colors.dark },
  busy: { opacity: 0.7 },
  reviewing: { marginTop: 10, textAlign: 'center', fontSize: 12, color: colors.textSecondary },
});
