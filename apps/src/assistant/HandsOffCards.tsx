// Hands-off chat trades by the Cuenta inteligente: the cards under the reply to the person's "sí".
//
//   relay_trade        the account is trading it: its state, until the result is posted in the chat
//   trade_cap          the weekly cap, chosen once and signed with Confío Face (or raised); then the trade runs
//   trade_move         dollars moved in from the personal wallet (after a top-up), with Face; then it runs
//   trade_offer        "Activa Cuenta inteligente" (the offer, door chip) and/or "Hazlo tú" (the menu's screen)
//   account_migration  the one-Face update to the account version that trades for the person
//   relay_purchase, purchase_cap, purchase_move, purchase_offer: the same for a Comprar purchase (ComprarCards.tsx)
//
// Every figure is the server's (assistantRelayTrade); the only number sent from here is the cap the person picks.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { gql, useApolloClient } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';

import { Text, TextInput } from '../components/common/AppText';
import { Button } from '../components/common/Button';
import { SignFlowSheet } from '../components/smartAccount/SignFlowSheet';
import { useSignFlow } from '../components/smartAccount/useSignFlow';
import { DEX_TRADING_UI_ENABLED } from '../config/features';
import { requestActivityShare, type ActivityShareGroup } from '../services/communityShare';
import type { AssistantAction } from './api';
import { ComprarCard } from './ComprarCards';
import { PURCHASE_TYPES } from './comprarHandsOff';
import {
  capAmount, capText, diyScreenAllowed, GET_RELAY_TRADE, handsOffActions, prepareAccountMigration,
  prepareTradeCap, prepareTradeMove, RelayTrade, RESUME_RELAY_TRADE, ThreadRefreshContext, useSettledRefresh,
} from './handsOff';

type Open = (screen: string, params?: Record<string, unknown>) => void;
/** In the floating box: closes it before the share sheet opens. */
type Leave = (() => void) | undefined;

// Its own query: a server without `assetKind` fails only this, never the card's status.
export const GET_RELAY_TRADE_KIND = gql`
  query AssistantRelayTradeKind($trade: UUID!) {
    assistantRelayTrade(trade: $trade) { assetKind }
  }
`;

/** The Comunidad share a done hands-off trade offers: none for bitcoin or gold where the app ships without them. */
export function shareGroupFor(assetKind: string | null | undefined, dexEnabled: boolean): ActivityShareGroup | null {
  if (assetKind === 'stock') return 'stock';
  if (assetKind === 'crypto') return dexEnabled ? 'crypto' : null;
  return null;
}

/**
 * The share of a done trade, as the signed chat trade's card: the sheet opens by itself once, when this card
 * saw the trade turn done (never for a trade already done when the card appeared, an old message scrolled
 * back); not in the floating box (iOS shows one modal at a time), where it is the card's button.
 */
function useDoneShare(trade: string | null | undefined, status: string | undefined, txHash: string, onLeave: Leave) {
  const client = useApolloClient();
  const firstSeen = useRef<string | null>(null);
  const offered = useRef(false);
  const [group, setGroup] = useState<ActivityShareGroup | null>(null);
  if (status && firstSeen.current === null) {
    firstSeen.current = status;
  }
  useEffect(() => {
    if (status !== 'done' || !txHash || !trade) {
      return undefined;
    }
    let stop = false;
    Promise.resolve()
      .then(() => client.query({ query: GET_RELAY_TRADE_KIND, variables: { trade }, fetchPolicy: 'no-cache' }))
      .then((result) => {
        if (stop) return;
        const found = shareGroupFor(result.data?.assistantRelayTrade?.assetKind, DEX_TRADING_UI_ENABLED);
        setGroup(found);
        const live = firstSeen.current !== null && firstSeen.current !== 'done';
        if (found && live && !onLeave && !offered.current) {
          offered.current = true;
          requestActivityShare({ group: found, reference: txHash });
        }
      })
      .catch(() => undefined);   // an older server: no share
    return () => { stop = true; };
  }, [client, status, txHash, trade, onLeave]);
  return group;
}

const INK = '#111827';
const MUTED = '#6B7280';
const STATUS_WORDS: Record<string, string> = {
  pending: 'Haciéndolo desde tu Cuenta inteligente…',
  done: 'Hecho. Te dejé el detalle en el chat.',
  failed: 'No se hizo. No se movió nada.',
  cancelled: 'No lo hice: escribiste algo después.',
  waiting_rule: 'Esperando tu límite semanal.',
  waiting_move: 'Esperando que muevas los dólares.',
};

function useRelayTrade(trade: string | null | undefined) {
  const client = useApolloClient();
  const [row, setRow] = useState<RelayTrade | null>(null);
  const load = useCallback(async () => {
    if (!trade) {
      return null;
    }
    try {
      const result = await client.query({ query: GET_RELAY_TRADE, variables: { trade }, fetchPolicy: 'no-cache',
        context: { queryDeduplication: false } });
      const found = (result.data?.assistantRelayTrade ?? null) as RelayTrade | null;
      setRow(found);
      return found;
    } catch {
      return null;   // a server without it: the card keeps its label
    }
  }, [client, trade]);
  return { row, load };
}

export function RelayTradeCard({ action, onLeave }: { action: AssistantAction; onLeave?: () => void }) {
  const { row, load } = useRelayTrade(action.target);
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
  const status = row?.status ?? 'pending';
  const txHash = row?.txHash || '';
  const group = useDoneShare(action.target, row?.status, txHash, onLeave);
  useSettledRefresh(row?.status);
  const share = () => {
    if (!group) return;
    onLeave?.();
    setTimeout(() => requestActivityShare({ group, reference: txHash, again: true }), onLeave ? 250 : 0);
  };
  return (
    <View style={styles.card} testID="relay-trade-card">
      <Text style={styles.title}>{row?.label || action.label}</Text>
      <View style={styles.statusRow}>
        {status === 'pending' ? <ActivityIndicator size="small" /> : null}
        <Text style={styles.hint}>{STATUS_WORDS[status] ?? STATUS_WORDS.pending}</Text>
      </View>
      {status === 'done' && group && txHash ? (
        <Pressable onPress={share} accessibilityRole="button" accessibilityLabel="Compartir"
          testID="relay-trade-share" style={({ pressed }) => [styles.share, pressed && styles.sharePressed]}>
          <Icon name="share-2" size={16} color="#047857" />
          <Text style={styles.shareText}>Compartir</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function TradeCapCard({ action, onLeave }: { action: AssistantAction; onLeave?: () => void }) {
  const client = useApolloClient();
  const { row, load } = useRelayTrade(action.target);
  const [picked, setPicked] = useState<string | null>(null);
  const [other, setOther] = useState('');
  const [typing, setTyping] = useState(false);
  const [resumed, setResumed] = useState(false);
  const flow = useSignFlow({
    onExecuted: async () => {
      try {
        await client.mutate({ mutation: RESUME_RELAY_TRADE, variables: { trade: action.target },
          fetchPolicy: 'no-cache' });
      } catch {
        // The trade waits for its rule; asking again in the chat works too.
      }
      setResumed(true);
    },
  });
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (row?.preselected && picked === null) {
      setPicked(Number(row.preselected).toFixed(2));
    }
  }, [row, picked]);

  if (resumed || (row && row.status !== 'waiting_rule')) {
    return <RelayTradeCard action={action} onLeave={onLeave} />;
  }
  const choices = row?.choices?.length ? row.choices : ['250', '1000', '2500'];
  const raise = row?.mode === 'raise';
  const amount = typing ? capAmount(other) : picked;
  const busy = flow.state.phase === 'preparing' || flow.state.phase === 'signing';
  return (
    <View style={styles.card} testID="trade-cap-card">
      <Text style={styles.title}>{raise ? 'Sube tu límite semanal' : '¿Cuánto puedo operar por ti?'}</Text>
      {raise && row?.currentCap ? <Text style={styles.hint}>Hoy: {capText(row.currentCap)}</Text> : null}
      <View style={styles.choices}>
        {choices.map((c) => {
          const value = Number(c).toFixed(2);
          const on = !typing && picked === value;
          return (
            <Pressable key={c} accessibilityRole="radio" accessibilityState={{ selected: on }}
              testID={`cap-${c}`} onPress={() => { setTyping(false); setPicked(value); }}
              style={[styles.choice, on && styles.choiceOn]}>
              <Text style={[styles.choiceText, on && styles.choiceTextOn]}>US${Number(c).toLocaleString('en-US')}</Text>
            </Pressable>
          );
        })}
        <Pressable accessibilityRole="radio" accessibilityState={{ selected: typing }} testID="cap-other"
          onPress={() => setTyping(true)} style={[styles.choice, typing && styles.choiceOn]}>
          <Text style={[styles.choiceText, typing && styles.choiceTextOn]}>Otro monto</Text>
        </Pressable>
      </View>
      {typing ? (
        <TextInput value={other} onChangeText={setOther} keyboardType="decimal-pad" placeholder="US$ por semana"
          style={styles.input} testID="cap-input" />
      ) : null}
      {amount ? <Text style={styles.hint}>{capText(amount)}. Compras y ventas cuentan.</Text> : null}
      <Button title="Firmar con Confío Face" disabled={!amount || busy} loading={flow.state.phase === 'preparing'}
        onPress={() => amount && flow.start({ prepare: () => prepareTradeCap(client, action.target!, amount),
          faceStepUp: true })} />
      <SignFlowSheet flow={flow} copy={{
        confirmLabel: 'Firmar con Confío Face',
        successBody: 'Listo. Ahora hago la operación y te aviso en el chat.',
      }} onDone={() => load()} onUnknownDone={() => load()} />
    </View>
  );
}

export function TradeMoveCard({ action, onLeave }: { action: AssistantAction; onLeave?: () => void }) {
  const client = useApolloClient();
  const { row, load } = useRelayTrade(action.target);
  const [resumed, setResumed] = useState(false);
  const flow = useSignFlow({
    onExecuted: async () => {
      try {
        await client.mutate({ mutation: RESUME_RELAY_TRADE, variables: { trade: action.target },
          fetchPolicy: 'no-cache' });
      } catch {
        // The trade waits; asking again in the chat works too.
      }
      setResumed(true);
    },
  });
  useEffect(() => { load(); }, [load]);
  if (resumed || (row && row.status !== 'waiting_move')) {
    return <RelayTradeCard action={action} onLeave={onLeave} />;
  }
  const amount = row?.moveAmount ? `US$${Number(row.moveAmount).toFixed(2)}` : '';
  return (
    <View style={styles.card} testID="trade-move-card">
      <Text style={styles.title}>{amount ? `Mover ${amount} a tu Cuenta inteligente` : action.label}</Text>
      <Text style={styles.hint}>Desde tu billetera, con Confío Face. Después hago la operación.</Text>
      <Button title="Mover con Confío Face" disabled={flow.state.phase === 'signing'}
        loading={flow.state.phase === 'preparing'}
        onPress={() => flow.start({ prepare: () => prepareTradeMove(client, action.target!), faceStepUp: true })} />
      <SignFlowSheet flow={flow} copy={{
        confirmLabel: 'Firmar con Confío Face',
        successBody: 'Listo. Ahora hago la operación y te aviso en el chat.',
      }} onDone={() => load()} onUnknownDone={() => load()} />
    </View>
  );
}

export function TradeOfferCard({ action, onOpen }: { action: AssistantAction; onOpen: Open }) {
  const diy = diyScreenAllowed(action.destination, DEX_TRADING_UI_ENABLED) ? action.destination! : null;
  const param = diy === 'BuyCrypto' || diy === 'SellCrypto' ? 'symbol' : 'ticker';
  return (
    <View style={styles.card} testID="trade-offer-card">
      {action.target ? (
        <>
          <Text style={styles.title}>Con Cuenta inteligente lo hago por ti</Text>
          <Text style={styles.hint}>Sin firmar cada operación: me lo pides aquí y lo hago.</Text>
          <Button title="Activa Cuenta inteligente"
            onPress={() => onOpen('SmartAccountOffer', { door: 'chip', trigger: action.target })} />
        </>
      ) : null}
      {diy ? (
        <Pressable accessibilityRole="button" testID="trade-offer-diy" style={styles.link}
          onPress={() => onOpen(diy, { [param]: action.ticker })}>
          <Text style={styles.linkText}>Hazlo tú</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function MigrationCard({ action }: { action: AssistantAction }) {
  const client = useApolloClient();
  const flow = useSignFlow();
  return (
    <View style={styles.card} testID="migration-card">
      <Text style={styles.title}>{action.label || 'Actualizar mi Cuenta inteligente'}</Text>
      <Text style={styles.hint}>Una sola firma con Confío Face. Tu dinero y tus reglas pasan a la nueva versión.</Text>
      <Button title="Actualizar con Confío Face" loading={flow.state.phase === 'preparing'}
        onPress={() => flow.start({ prepare: () => prepareAccountMigration(client), faceStepUp: true })} />
      <SignFlowSheet flow={flow} copy={{
        confirmLabel: 'Firmar con Confío Face',
        successBody: 'Listo. Pídeme otra vez la operación y la hago por ti.',
      }} />
    </View>
  );
}

/** Every hands-off card of one message (one of each kind). */
export function HandsOffCards({ messageId, actions, onOpen, onLeave, onSettled }: {
  messageId: string; actions: AssistantAction[]; onOpen: Open; onLeave?: () => void;
  /** Reloads the conversation: a trade or purchase seen settling brings its result note in at once. */
  onSettled?: () => void;
}) {
  const seen = new Set<string>();
  return (
    <ThreadRefreshContext.Provider value={onSettled ?? null}>
      {handsOffActions(actions).filter((a) => !seen.has(a.type) && seen.add(a.type)).map((a) => {
        const key = `${messageId}:${a.type}`;
        if (a.type === 'relay_trade' && a.target) return <RelayTradeCard key={key} action={a} onLeave={onLeave} />;
        if (a.type === 'trade_cap' && a.target) return <TradeCapCard key={key} action={a} onLeave={onLeave} />;
        if (a.type === 'trade_move' && a.target) return <TradeMoveCard key={key} action={a} onLeave={onLeave} />;
        if (a.type === 'trade_offer') return <TradeOfferCard key={key} action={a} onOpen={onOpen} />;
        if (a.type === 'account_migration') return <MigrationCard key={key} action={a} />;
        if (PURCHASE_TYPES.has(a.type)) return <ComprarCard key={key} action={a} onOpen={onOpen} />;
        return null;
      })}
    </ThreadRefreshContext.Provider>
  );
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
  share: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 40,
    borderRadius: 12, borderWidth: 1, borderColor: '#A7F3D0',
  },
  sharePressed: { backgroundColor: '#ECFDF5' },
  shareText: { fontSize: 15, fontWeight: '700', color: '#047857' },
  link: { alignSelf: 'center', minHeight: 36, justifyContent: 'center', paddingHorizontal: 12 },
  linkText: { fontSize: 14, color: MUTED, textDecorationLine: 'underline' },
});
