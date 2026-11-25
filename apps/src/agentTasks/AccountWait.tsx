// A purchase the person's Cuenta inteligente pays, waiting for it (spec decisions 38 to 40). It is never paid
// from the personal wallet: the card offers the one thing that lets the account pay it, signed with Confío
// Face in the ordinary Cuenta inteligente signing flow, and then asks the account again.
//
//   no_rule  "Activar compras"      the "Compras con Confío IA" rule (US$200 per 28 days)
//   cap      "Subir el límite"      the same rule with a higher cap
//   move     "Mover US$X"           personal wallet -> Cuenta inteligente
//   topup    "Recargar"             the existing top-up; then the card offers the move
//   renew    "Ir a mi Cuenta inteligente"   a lapsed or inactive account: put it up to date there
//
// Every amount is the server's (agentAccountWait, prepareAgentAccountWait): nothing here is sent as a figure.
import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';

import { Text } from '../components/common/AppText';
import { Button } from '../components/common/Button';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { colors } from '../config/theme';
import { AgentAccountWait, GET_AGENT_ACCOUNT_WAIT, prepareAgentAccountWait } from './api';

const SIGNED = new Set(['no_rule', 'cap', 'move']);

export function actionLabel(wait: AgentAccountWait | null): string | null {
  if (!wait) {
    return null;
  }
  if (wait.code === 'no_rule') {
    return 'Activar compras';
  }
  if (wait.code === 'cap') {
    return 'Subir el límite';
  }
  if (wait.code === 'move') {
    return wait.amountUsd ? `Mover US$${wait.amountUsd}` : null;
  }
  if (wait.code === 'topup') {
    return 'Recargar';
  }
  if (wait.code === 'renew') {
    return 'Ir a mi Cuenta inteligente';
  }
  return null;
}

export function AccountWait({ taskId, resuming, onResume, onOpen }: {
  taskId: string;
  resuming: boolean;
  /** resumeAgentPayment: the account is asked again. */
  onResume: () => Promise<boolean> | void;
  onOpen?: (screen: string, params?: Record<string, unknown>) => void;
}) {
  const client = useApolloClient();
  const [wait, setWait] = useState<AgentAccountWait | null>(null);
  const flow = useSignFlow({ onExecuted: () => { onResume(); } });

  const load = useCallback(async () => {
    try {
      const result = await client.query({
        query: GET_AGENT_ACCOUNT_WAIT, variables: { id: taskId }, fetchPolicy: 'no-cache',
        context: { queryDeduplication: false },
      });
      setWait(result.data?.agentAccountWait ?? null);
    } catch {
      setWait(null);   // a server without it: the card's own words and "Ya lo hice: pagar" remain
    }
  }, [client, taskId]);
  useEffect(() => { load(); }, [load]);

  const label = actionLabel(wait);
  const act = () => {
    if (!wait) {
      return;
    }
    if (SIGNED.has(wait.code)) {
      flow.start({ prepare: () => prepareAgentAccountWait(client, taskId), faceStepUp: true });
    } else if (wait.code === 'topup' && onOpen) {
      onOpen('TopUp');
    } else if (wait.code === 'renew' && onOpen) {
      onOpen('SmartAccountHome');
    }
  };
  const busy = resuming || flow.state.phase === 'preparing' || flow.state.phase === 'signing';
  return (
    <View style={styles.box}>
      {label && (SIGNED.has(wait!.code) || onOpen) ? (
        <Button title={label} onPress={act} disabled={busy} loading={flow.state.phase === 'preparing'} />
      ) : null}
      <Pressable accessibilityRole="button" accessibilityLabel="Ya lo hice: pagar" style={styles.link}
        disabled={busy} onPress={() => { onResume(); }}>
        <Text style={styles.linkText}>Ya lo hice: pagar</Text>
      </Pressable>
      <SignFlowSheet flow={flow} copy={{
        confirmLabel: 'Firmar con Confío Face',
        successBody: 'Ahora lo pago desde tu Cuenta inteligente.',
      }} onDone={() => load()} onUnknownDone={() => load()} />
    </View>
  );
}

const styles = StyleSheet.create({
  box: { marginTop: 12, gap: 4 },
  link: { alignSelf: 'center', minHeight: 36, justifyContent: 'center', paddingHorizontal: 12 },
  linkText: { fontSize: 14, color: colors.text.secondary, textDecorationLine: 'underline' },
});
