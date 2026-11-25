// Hands-off Comprar purchases from the chat: the cards under the reply to the person's "sí".
//
//   relay_purchase   the Cuenta inteligente is paying it: its state, until the result is posted in the chat
//   purchase_cap     the weekly Comprar cap (small: US$50 / 150 / 300 or another), signed once with Face; then it runs
//   purchase_move    dollars moved in from the personal wallet, with Face; then it runs
//   purchase_offer   "Activa Cuenta inteligente" and/or "Hazlo tú" (the product's own screen, paid from the wallet)
//
// Every figure is the server's (assistantRelayPurchase); the only number sent from here is the cap the person picks.
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';

import { Text, TextInput } from '../components/common/AppText';
import { Button } from '../components/common/Button';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import type { AssistantAction } from './api';
import {
  GET_RELAY_PURCHASE, PURCHASE_CAP_CHOICES, preparePurchaseCap, preparePurchaseMove, purchaseCapAmount,
  RelayPurchase, RESUME_RELAY_PURCHASE,
} from './comprarHandsOff';
import { capText, useSettledRefresh } from './handsOff';

type Open = (screen: string, params?: Record<string, unknown>) => void;

const INK = '#111827';
const MUTED = '#6B7280';
const STATUS_WORDS: Record<string, string> = {
  pending: 'Pagando desde tu Cuenta inteligente…',
  done: 'Pagado. Tu pago queda protegido hasta que lo recibas.',
  failed: 'No se compró. No se movió nada.',
  cancelled: 'No lo compré: escribiste algo después.',
  waiting_rule: 'Esperando tu límite de compras.',
  waiting_move: 'Esperando que muevas los dólares.',
};

function useRelayPurchase(purchase: string | null | undefined) {
  const client = useApolloClient();
  const [row, setRow] = useState<RelayPurchase | null>(null);
  const load = useCallback(async () => {
    if (!purchase) {
      return null;
    }
    try {
      const result = await client.query({ query: GET_RELAY_PURCHASE, variables: { purchase },
        fetchPolicy: 'no-cache', context: { queryDeduplication: false } });
      const found = (result.data?.assistantRelayPurchase ?? null) as RelayPurchase | null;
      setRow(found);
      return found;
    } catch {
      return null;   // a server without it: the card keeps its label
    }
  }, [client, purchase]);
  return { row, load };
}

function useResume(purchase: string | null | undefined) {
  const client = useApolloClient();
  const [resumed, setResumed] = useState(false);
  const flow = useSignFlow({
    onExecuted: async () => {
      try {
        await client.mutate({ mutation: RESUME_RELAY_PURCHASE, variables: { purchase }, fetchPolicy: 'no-cache' });
      } catch {
        // The purchase waits; asking again in the chat works too.
      }
      setResumed(true);
    },
  });
  return { flow, resumed };
}

export function RelayPurchaseCard({ action, onOpen }: { action: AssistantAction; onOpen?: Open }) {
  const { row, load } = useRelayPurchase(action.target);
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      const found = await load();
      if (!stop && (!found || found.status === 'pending')) {
        timer = setTimeout(tick, 4000);
      }
    };
    tick();
    return () => { stop = true; if (timer) clearTimeout(timer); };
  }, [load]);
  useSettledRefresh(row?.status);
  const status = row?.status ?? 'pending';
  return (
    <View style={styles.card} testID="relay-purchase-card">
      <Text style={styles.title}>{row?.label || action.label}</Text>
      <View style={styles.statusRow}>
        {status === 'pending' ? <ActivityIndicator size="small" /> : null}
        <Text style={styles.hint}>{STATUS_WORDS[status] ?? STATUS_WORDS.pending}</Text>
      </View>
      {status === 'done' && row?.order && onOpen ? (
        <Pressable accessibilityRole="button" testID="relay-purchase-order" style={styles.link}
          onPress={() => onOpen('MarketOrder', { orderId: row.order })}>
          <Text style={styles.linkText}>Ver mi compra</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function PurchaseCapCard({ action, onOpen }: { action: AssistantAction; onOpen?: Open }) {
  const client = useApolloClient();
  const { row, load } = useRelayPurchase(action.target);
  const { flow, resumed } = useResume(action.target);
  const [picked, setPicked] = useState<string | null>(null);
  const [other, setOther] = useState('');
  const [typing, setTyping] = useState(false);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (row?.preselected && picked === null) {
      setPicked(Number(row.preselected).toFixed(2));
    }
  }, [row, picked]);

  if (resumed || (row && row.status !== 'waiting_rule')) {
    return <RelayPurchaseCard action={action} onOpen={onOpen} />;
  }
  const choices = row?.choices?.length ? row.choices : PURCHASE_CAP_CHOICES;
  const raise = row?.mode === 'raise';
  const amount = typing ? purchaseCapAmount(other) : picked;
  const busy = flow.state.phase === 'preparing' || flow.state.phase === 'signing';
  return (
    <View style={styles.card} testID="purchase-cap-card">
      <Text style={styles.title}>{raise ? 'Sube tu límite de compras' : '¿Cuánto puedo gastar por ti en Comprar?'}</Text>
      {raise && row?.currentCap ? <Text style={styles.hint}>Hoy: {capText(row.currentCap)}</Text> : null}
      <View style={styles.choices}>
        {choices.map((c) => {
          const value = Number(c).toFixed(2);
          const on = !typing && picked === value;
          return (
            <Pressable key={c} accessibilityRole="radio" accessibilityState={{ selected: on }}
              testID={`purchase-cap-${c}`} onPress={() => { setTyping(false); setPicked(value); }}
              style={[styles.choice, on && styles.choiceOn]}>
              <Text style={[styles.choiceText, on && styles.choiceTextOn]}>US${Number(c).toLocaleString('en-US')}</Text>
            </Pressable>
          );
        })}
        <Pressable accessibilityRole="radio" accessibilityState={{ selected: typing }} testID="purchase-cap-other"
          onPress={() => setTyping(true)} style={[styles.choice, typing && styles.choiceOn]}>
          <Text style={[styles.choiceText, typing && styles.choiceTextOn]}>Otro monto</Text>
        </Pressable>
      </View>
      {typing ? (
        <TextInput value={other} onChangeText={setOther} keyboardType="decimal-pad" placeholder="US$ por semana"
          style={styles.input} testID="purchase-cap-input" />
      ) : null}
      {amount ? <Text style={styles.hint}>{capText(amount)}. Solo al pago protegido de Comprar.</Text> : null}
      <Button title="Firmar con Confío Face" disabled={!amount || busy} loading={flow.state.phase === 'preparing'}
        onPress={() => amount && flow.start({ prepare: () => preparePurchaseCap(client, action.target!, amount),
          faceStepUp: true })} />
      <SignFlowSheet flow={flow} copy={{
        confirmLabel: 'Firmar con Confío Face',
        successBody: 'Listo. Ahora hago la compra y te aviso en el chat.',
      }} onDone={() => load()} onUnknownDone={() => load()} />
    </View>
  );
}

export function PurchaseMoveCard({ action, onOpen }: { action: AssistantAction; onOpen?: Open }) {
  const client = useApolloClient();
  const { row, load } = useRelayPurchase(action.target);
  const { flow, resumed } = useResume(action.target);
  useEffect(() => { load(); }, [load]);
  if (resumed || (row && row.status !== 'waiting_move')) {
    return <RelayPurchaseCard action={action} onOpen={onOpen} />;
  }
  const amount = row?.moveAmount ? `US$${Number(row.moveAmount).toFixed(2)}` : '';
  return (
    <View style={styles.card} testID="purchase-move-card">
      <Text style={styles.title}>{amount ? `Mover ${amount} a tu Cuenta inteligente` : action.label}</Text>
      <Text style={styles.hint}>Desde tu billetera, con Confío Face. Después hago la compra.</Text>
      <Button title="Mover con Confío Face" disabled={flow.state.phase === 'signing'}
        loading={flow.state.phase === 'preparing'}
        onPress={() => flow.start({ prepare: () => preparePurchaseMove(client, action.target!), faceStepUp: true })} />
      <SignFlowSheet flow={flow} copy={{
        confirmLabel: 'Firmar con Confío Face',
        successBody: 'Listo. Ahora hago la compra y te aviso en el chat.',
      }} onDone={() => load()} onUnknownDone={() => load()} />
    </View>
  );
}

export function PurchaseOfferCard({ action, onOpen }: { action: AssistantAction; onOpen: Open }) {
  // `destination` is the product's screen and `ticker` its id (the fields every build's action carries).
  const product = action.destination === 'MarketProduct' && action.ticker ? action.ticker : null;
  return (
    <View style={styles.card} testID="purchase-offer-card">
      {action.target ? (
        <>
          <Text style={styles.title}>Con Cuenta inteligente lo compro por ti</Text>
          <Text style={styles.hint}>Sin firmar cada compra: me lo pides aquí y lo pago con pago protegido.</Text>
          <Button title="Activa Cuenta inteligente"
            onPress={() => onOpen('SmartAccountOffer', { door: 'chip', trigger: action.target })} />
        </>
      ) : null}
      {product ? (
        <Pressable accessibilityRole="button" testID="purchase-offer-diy" style={styles.link}
          onPress={() => onOpen('MarketProduct', { productId: product })}>
          <Text style={styles.linkText}>Hazlo tú</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** One Comprar hands-off card (HandsOffCards renders one of each kind per message). */
export function ComprarCard({ action, onOpen }: { action: AssistantAction; onOpen: Open }) {
  if (action.type === 'relay_purchase' && action.target) return <RelayPurchaseCard action={action} onOpen={onOpen} />;
  if (action.type === 'purchase_cap' && action.target) return <PurchaseCapCard action={action} onOpen={onOpen} />;
  if (action.type === 'purchase_move' && action.target) return <PurchaseMoveCard action={action} onOpen={onOpen} />;
  if (action.type === 'purchase_offer') return <PurchaseOfferCard action={action} onOpen={onOpen} />;
  return null;
}

const styles = StyleSheet.create({
  card: {
    marginTop: 4, marginBottom: 4, maxWidth: 340, padding: 14, borderRadius: 16, gap: 8,
    borderWidth: 1, borderColor: '#A7F3D0', backgroundColor: '#FFFFFF',
  },
  title: { fontSize: 16, fontWeight: '700', color: INK },
  hint: { fontSize: 13, lineHeight: 18, color: MUTED },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  choice: { paddingVertical: 8, paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: '#D1D5DB' },
  choiceOn: { borderColor: '#059669', backgroundColor: '#ECFDF5' },
  choiceText: { fontSize: 14, color: INK },
  choiceTextOn: { fontWeight: '700', color: '#047857' },
  input: { borderWidth: 1, borderColor: '#D1D5DB', borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8,
    fontSize: 15, color: INK },
  link: { alignSelf: 'center', minHeight: 36, justifyContent: 'center', paddingHorizontal: 12 },
  linkText: { fontSize: 14, color: MUTED, textDecorationLine: 'underline' },
});
