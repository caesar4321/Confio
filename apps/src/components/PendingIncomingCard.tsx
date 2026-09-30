/**
 * Home promo: money waiting for Confío Face before it reaches the balance.
 * Outranks every other promo: it is the user's own money and it goes back
 * to the payer if nobody confirms within 24 hours.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect } from '@react-navigation/native';
import { colors } from '../config/theme';
import { formatRampMoney } from '../utils/rampFormat';
import { fetchPendingIncoming, isAwaiting, isUnresolved, PendingIncomingPayin, timeLeft } from '../services/pendingIncoming';

/**
 * Waiting pay-ins for the active personal account; [] when disabled.
 * Keyed by account: a response that arrives after an account switch is
 * dropped, and a failed load keeps what was shown instead of hiding money.
 */
export const usePendingIncoming = (accountId: string | undefined, isPersonal: boolean) => {
  const [state, setState] = useState<{ accountId?: string; waiting: PendingIncomingPayin[]; unresolved: PendingIncomingPayin[] }>(
    { waiting: [], unresolved: [] });
  const latest = useRef(0);

  const refresh = useCallback(async () => {
    const request = ++latest.current;
    if (!accountId || !isPersonal) { setState({ accountId, waiting: [], unresolved: [] }); return; }
    const { items } = await fetchPendingIncoming();
    if (request !== latest.current || items === null) return;
    setState({ accountId, waiting: items.filter(isAwaiting), unresolved: items.filter(isUnresolved) });
  }, [accountId, isPersonal]);

  useFocusEffect(useCallback(() => { refresh(); }, [refresh]));
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const sub = AppState.addEventListener('change', s => { if (s === 'active') refresh(); });
    return () => sub.remove();
  }, [refresh]);

  const mine = isPersonal && state.accountId === accountId;
  return { waiting: mine ? state.waiting : [], unresolved: mine ? state.unresolved : [], refresh };
};

export const PendingIncomingCard = ({ waiting, unresolved = [], onPress }: {
  waiting: PendingIncomingPayin[]; unresolved?: PendingIncomingPayin[]; onPress: () => void;
}) => {
  if (!waiting.length) {
    // Confirmed or returning but not settled: keep a way back to the details.
    if (!unresolved.length) return null;
    const returning = unresolved.every(i => i.state === 'returning' || i.state === 'return_failed');
    return (
      <TouchableOpacity style={styles.quietCard} onPress={onPress} activeOpacity={0.9}>
        <Icon name={returning ? 'corner-up-left' : 'clock'} size={18} color={colors.primaryDark} />
        <View style={styles.quietBody}>
          <Text style={styles.quietTitle}>{returning ? 'Devolución en curso' : 'Tu dinero está en camino'}</Text>
          <Text style={styles.quietText}>
            {unresolved.length === 1 ? '1 transferencia' : `${unresolved.length} transferencias`}. Toca para ver el detalle.
          </Text>
        </View>
        <Icon name="chevron-right" size={18} color={colors.textSecondary} />
      </TouchableOpacity>
    );
  }
  const soonest = waiting.reduce((a, b) => (Date.parse(a.returnsAt) <= Date.parse(b.returnsAt) ? a : b));
  const byAsset = new Map<string, number>();
  for (const item of waiting) byAsset.set(item.asset, (byAsset.get(item.asset) || 0) + Number(item.amount || 0));
  const total = [...byAsset.entries()].map(([asset, amount]) => formatRampMoney(amount, asset)).join(' + ');
  const from = waiting.length === 1 && waiting[0].payerName ? `De ${waiting[0].payerName}` : `${waiting.length} transferencias`;

  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.9}>
      <View style={styles.header}>
        <View style={styles.badge}><Text style={styles.badgeText}>POR RECIBIR</Text></View>
        <Text style={styles.timer}>
          <Icon name="clock" size={12} color={colors.textSecondary} /> {timeLeft(soonest.returnsAt)}
        </Text>
      </View>
      <Text style={styles.amount}>{total}</Text>
      <Text style={styles.subtitle}>{from}. Confirma con tu rostro para recibirlo en tu saldo.</Text>
      <View style={styles.button}>
        <Text style={styles.buttonText}>Recibir con mi rostro</Text>
        <Icon name="arrow-right" size={16} color={colors.white} />
      </View>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  card: {
    marginHorizontal: 16, marginBottom: 12, padding: 18, borderRadius: 20,
    backgroundColor: colors.white, borderWidth: 1, borderColor: colors.primaryLight,
  },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  badge: { backgroundColor: colors.primaryLight, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  badgeText: { color: colors.primaryDark, fontSize: 11, fontWeight: '700', letterSpacing: 1 },
  timer: { color: colors.textSecondary, fontSize: 13 },
  amount: { color: colors.dark, fontSize: 26, fontWeight: '700', marginBottom: 4 },
  subtitle: { color: colors.textSecondary, fontSize: 14, lineHeight: 20, marginBottom: 14 },
  button: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    backgroundColor: colors.primaryDark, borderRadius: 14, paddingVertical: 13,
  },
  buttonText: { color: colors.white, fontSize: 15, fontWeight: '700' },
  quietCard: {
    marginHorizontal: 16, marginBottom: 12, padding: 16, borderRadius: 16, gap: 12,
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: colors.white, borderWidth: 1, borderColor: colors.primaryLight,
  },
  quietBody: { flex: 1 },
  quietTitle: { color: colors.dark, fontSize: 15, fontWeight: '700', marginBottom: 2 },
  quietText: { color: colors.textSecondary, fontSize: 13 },
});
