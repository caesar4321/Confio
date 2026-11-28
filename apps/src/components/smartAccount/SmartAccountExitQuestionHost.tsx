import React, { useEffect, useState } from 'react';
import { Modal, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useApolloClient } from '@apollo/client';

import { Text } from '../common/AppText';
import { colors } from '../../config/theme';
import {
  RECORD_SMART_ACCOUNT_EXIT_REASON,
  SMART_ACCOUNT_EXIT_SKIPPED,
  SmartAccountExitAsk,
  subscribeSmartAccountExitQuestion,
} from '../../services/smartAccountExit';

/**
 * The one "what made you wait?" sheet after the Cuenta inteligente subscribe
 * screen closes without opening the account (services/smartAccountExit). One
 * tap or close; never blocks anything.
 */
export function SmartAccountExitQuestionHost() {
  const client = useApolloClient();
  const [ask, setAsk] = useState<SmartAccountExitAsk | null>(null);

  useEffect(() => subscribeSmartAccountExitQuestion(setAsk), []);

  const answer = (reason: string) => {
    const plan = ask?.plan ?? null;
    setAsk(null);
    client.mutate({ mutation: RECORD_SMART_ACCOUNT_EXIT_REASON, variables: { reason, plan }, fetchPolicy: 'no-cache' })
      .catch(() => {});
  };

  return (
    <Modal visible={!!ask} transparent animationType="slide" onRequestClose={() => answer(SMART_ACCOUNT_EXIT_SKIPPED)}>
      <View style={local.backdrop}>
        <View style={local.sheet}>
          <View style={local.header}>
            <Text style={local.title}>{ask?.title}</Text>
            <TouchableOpacity accessibilityRole="button" accessibilityLabel="Cerrar" testID="smart-exit-close"
              onPress={() => answer(SMART_ACCOUNT_EXIT_SKIPPED)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Icon name="x" size={22} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>
          {(ask?.reasons || []).map(([id, label]) => (
            <TouchableOpacity key={id} accessibilityRole="button" onPress={() => answer(id)} style={local.option}
              testID={`smart-exit-${id}`}>
              <Text style={local.optionText}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>
    </Modal>
  );
}

const local = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(17, 24, 39, 0.4)' },
  sheet: {
    backgroundColor: colors.background, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingHorizontal: 20, paddingTop: 20, paddingBottom: 32,
  },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 12, marginBottom: 6 },
  title: { flex: 1, fontSize: 18, fontWeight: '700', color: colors.dark },
  option: {
    borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
    paddingHorizontal: 16, paddingVertical: 13, marginTop: 8,
  },
  optionText: { fontSize: 15, fontWeight: '600', color: colors.dark },
});
