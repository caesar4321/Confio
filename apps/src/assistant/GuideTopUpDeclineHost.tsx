import React, { useEffect, useRef, useState } from 'react';
import { Modal, StyleSheet, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useApolloClient } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { colors } from '../config/theme';
import { useAccount } from '../contexts/AccountContext';
import { RECORD_ASSISTANT_GUIDE_EVENT } from './api';
import {
  GUIDE_TOP_UP_STEP,
  TOP_UP_DECLINE_SKIPPED,
  TopUpDeclineReason,
  shuffledDeclineReasons,
  subscribeTopUpDecline,
} from './guideTopUpDecline';

/**
 * The one "why not top up yet?" sheet (guideTopUpDecline), mounted once in the
 * assistant overlay so it outlives the guide bubble that just closed. One tap
 * or close; never blocks anything.
 */
export default function GuideTopUpDeclineHost() {
  const client = useApolloClient();
  const { activeAccount } = useAccount();
  const [reasons, setReasons] = useState<TopUpDeclineReason[] | null>(null);
  const answered = useRef(false);

  useEffect(() => subscribeTopUpDecline(() => {
    answered.current = false;
    setReasons(shuffledDeclineReasons());
  }), []);
  // Asked of one personal account: never left open across a switch.
  useEffect(() => setReasons(null), [activeAccount?.id]);

  const answer = (reason: string) => {
    if (answered.current) return;  // a quick second tap during the slide-out
    answered.current = true;
    setReasons(null);
    client.mutate({
      mutation: RECORD_ASSISTANT_GUIDE_EVENT,
      variables: { step: GUIDE_TOP_UP_STEP, event: 'reason', detail: reason },
      fetchPolicy: 'no-cache',
    }).catch(() => {});
  };

  return (
    <Modal visible={!!reasons} transparent animationType="slide" onRequestClose={() => answer(TOP_UP_DECLINE_SKIPPED)}>
      <View style={local.backdrop}>
        <View style={local.sheet}>
          <View style={local.header}>
            <Text style={local.title}>¿Qué te frena para recargar?</Text>
            <TouchableOpacity accessibilityRole="button" accessibilityLabel="Cerrar"
              onPress={() => answer(TOP_UP_DECLINE_SKIPPED)} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
              <Icon name="x" size={22} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>
          <Text style={local.subtitle}>Un toque. Nos ayuda a mejorar Confío.</Text>
          {(reasons || []).map(([id, label]) => (
            <TouchableOpacity key={id} accessibilityRole="button" onPress={() => answer(id)} style={local.option}>
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
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 },
  title: { flex: 1, fontSize: 18, fontWeight: '700', color: colors.dark },
  subtitle: { marginTop: 4, marginBottom: 14, fontSize: 14, color: colors.textSecondary },
  option: {
    borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
    paddingHorizontal: 16, paddingVertical: 13, marginTop: 8,
  },
  optionText: { fontSize: 15, fontWeight: '600', color: colors.dark },
});
