import React, { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { useMutation, useQuery } from '@apollo/client';
import { useIsFocused, useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { ACCEPT_COMMUNITY_RULES } from '../apollo/mutations';
import { GET_COMMUNITY_RULES } from '../apollo/queries';

type Props = {
  visible: boolean;
  onAccepted: () => void;
  onClose: () => void;
};

/**
 * The Comunidad rules (Terms §11), accepted once per rules version before a
 * first post, comment or profile photo. The text comes from the server, so
 * what people agree to is exactly what the server enforces.
 */
export function CommunityRulesSheet({ visible, onAccepted, onClose }: Props) {
  const navigation = useNavigation<any>();
  const focused = useIsFocused();
  const { data, loading, refetch } = useQuery(GET_COMMUNITY_RULES, {
    skip: !visible,
    fetchPolicy: 'network-only',
  });
  const [acceptRules, { loading: accepting }] = useMutation(ACCEPT_COMMUNITY_RULES);
  const [error, setError] = useState<string | null>(null);
  const rules = data?.communityRules;

  const accept = async () => {
    if (!rules) return;
    setError(null);
    try {
      const { data: result } = await acceptRules({ variables: { version: rules.version } });
      if (!result?.acceptCommunityRules?.success) {
        // e.g. the rules changed meanwhile: show the current text again.
        setError(result?.acceptCommunityRules?.error || 'No pudimos guardar tu aceptación.');
        await refetch();
        return;
      }
      onAccepted();
    } catch {
      setError('No pudimos guardar tu aceptación. Revisa tu conexión.');
    }
  };

  return (
    // Hidden while the Terms screen is on top (it is not focused then), and
    // back when the person returns: reading the Terms never cancels the flow.
    <Modal visible={visible && focused} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <Text style={styles.title}>Normas de la comunidad</Text>
          <Text style={styles.subtitle}>Para cuidar a todos en Comunidad:</Text>
          {loading && !rules ? (
            <ActivityIndicator style={styles.loading} color={colors.primary} />
          ) : (
            <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
              {(rules?.rules || []).map((rule: string) => (
                <View key={rule} style={styles.ruleRow}>
                  <Icon name="check" size={14} color={colors.primaryDark} />
                  <Text style={styles.ruleText}>{rule}</Text>
                </View>
              ))}
              <Pressable
                onPress={() => navigation.navigate('LegalDocument', { docType: 'terms' })}
                accessibilityRole="link"
              >
                <Text style={styles.link}>Leer los Términos de Servicio completos</Text>
              </Pressable>
            </ScrollView>
          )}
          {error ? <Text style={styles.error}>{error}</Text> : null}
          <Pressable
            style={[styles.accept, (!rules || accepting) && styles.acceptDisabled]}
            onPress={() => { void accept(); }}
            disabled={!rules || accepting}
            accessibilityRole="button"
          >
            {accepting ? (
              <ActivityIndicator color={colors.white} />
            ) : (
              <Text style={styles.acceptText}>Acepto las normas</Text>
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
  title: {
    fontSize: 19,
    fontWeight: '700',
    color: colors.textFlat,
  },
  subtitle: {
    marginTop: 4,
    fontSize: 14,
    color: colors.textSecondary,
  },
  loading: {
    marginVertical: 24,
  },
  list: {
    marginTop: 12,
  },
  listContent: {
    gap: 10,
    paddingBottom: 4,
  },
  ruleRow: {
    flexDirection: 'row',
    gap: 8,
    alignItems: 'flex-start',
  },
  ruleText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 20,
    color: colors.text.primary,
  },
  link: {
    marginTop: 4,
    fontSize: 13,
    fontWeight: '600',
    color: colors.primaryDark,
  },
  error: {
    marginTop: 10,
    fontSize: 13,
    color: colors.error.text,
  },
  accept: {
    marginTop: 16,
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
