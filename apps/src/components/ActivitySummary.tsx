import React from 'react';
import { StyleSheet, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';

/** What a Comunidad post made from a money movement shows (communityPostExtras.activity). */
export type ActivityShare = {
  kind: 'stock_buy' | 'stock_sell' | 'top_up' | 'withdraw' | 'send' | 'receive' | string;
  date?: string | null;
  amountUsd?: string | null;
  ticker?: string | null;
  name?: string | null;
  rail?: string | null;
  country?: string | null;
  minutes?: number | null;
  pnlUsd?: string | null;
  pnlPct?: string | null;
  position?: 'open' | 'closed' | string | null;
  headline: string;
};

const COUNTRY_NAMES: Record<string, string> = {
  AR: 'Argentina', BO: 'Bolivia', BR: 'Brasil', CL: 'Chile', CO: 'Colombia', EC: 'Ecuador',
  MX: 'México', PA: 'Panamá', PE: 'Perú', PY: 'Paraguay', UY: 'Uruguay', VE: 'Venezuela', US: 'EE.UU.',
};

const flag = (code?: string | null) =>
  code && /^[A-Z]{2}$/.test(code)
    ? String.fromCodePoint(...Array.from(code).map((ch) => 0x1f1e6 + ch.charCodeAt(0) - 65))
    : '';

const usd = (value?: string | null) => (value ? `US$${value}` : null);

const signed = (value: string, suffix = '') => {
  const n = Number(value);
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(2)}${suffix}`;
};

const ICONS: Record<string, string> = {
  stock_buy: 'trending-up',
  stock_sell: 'trending-down',
  top_up: 'arrow-down-circle',
  withdraw: 'arrow-up-circle',
  send: 'send',
  receive: 'download',
};

function titleFor(a: ActivityShare): string {
  switch (a.kind) {
    case 'stock_buy':
      return `Compró ${a.ticker || 'acciones'}`;
    case 'stock_sell':
      return `Vendió ${a.ticker || 'acciones'}`;
    case 'top_up':
      return 'Recargó dólares';
    case 'withdraw':
      return 'Retiró dólares';
    case 'send':
      return 'Envió a otro usuario de Confío';
    case 'receive':
      return 'Recibió de otro usuario de Confío';
    default:
      return a.headline;
  }
}

function detailFor(a: ActivityShare): string | null {
  if (a.kind === 'stock_buy' || a.kind === 'stock_sell') {
    return a.name && a.name !== a.ticker ? a.name : null;
  }
  if (a.kind === 'top_up' || a.kind === 'withdraw') {
    const parts = [
      a.rail ? `Por ${a.rail}` : null,
      a.minutes ? `en ${a.minutes} min` : null,
      a.country ? `${flag(a.country)} ${COUNTRY_NAMES[a.country] || a.country}`.trim() : null,
    ].filter(Boolean);
    return parts.length ? parts.join(' · ') : null;
  }
  return null;
}

function PnlLine({ a }: { a: ActivityShare }) {
  if (!a.pnlPct) return null;
  const n = Number(a.pnlPct);
  const color = n > 0 ? colors.flowIn.text : n < 0 ? colors.error.icon : colors.text.secondary;
  const label =
    a.kind === 'stock_sell' ? 'Resultado' : a.position === 'closed' ? 'Al vender' : 'Desde la compra';
  const money = a.pnlUsd ? ` (${signed(a.pnlUsd).replace(/^([+−]?)/, '$1US$')})` : '';
  return (
    <Text style={[styles.pnl, { color }]}>
      {label}: {signed(a.pnlPct, '%')}
      {money}
    </Text>
  );
}

/**
 * The verified part of a post made from a money movement: what happened,
 * the amount (unless the member hid it) and, for stocks, how it went.
 * Used by the share sheet's preview and by every feed card.
 */
export function ActivitySummary({ activity, compact = false }: { activity: ActivityShare; compact?: boolean }) {
  const amount = usd(activity.amountUsd);
  const detail = detailFor(activity);
  return (
    <View style={[styles.box, compact && styles.compact]}>
      <View style={styles.icon}>
        <Icon name={ICONS[activity.kind] || 'activity'} size={18} color={colors.flowIn.textSmall} />
      </View>
      <View style={styles.body}>
        <View style={styles.row}>
          <Text style={styles.title} numberOfLines={1}>
            {titleFor(activity)}
          </Text>
          {amount ? <Text style={styles.amount}>{amount}</Text> : null}
        </View>
        {detail ? (
          <Text style={styles.detail} numberOfLines={1}>
            {detail}
          </Text>
        ) : null}
        <PnlLine a={activity} />
        <Text style={styles.verified}>Movimiento real en Confío</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 12,
    gap: 10,
  },
  compact: { padding: 10 },
  icon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.flowIn.chip,
    alignItems: 'center',
    justifyContent: 'center',
  },
  body: { flex: 1, gap: 2 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 },
  title: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.text.primary },
  amount: { fontSize: 15, fontWeight: '700', color: colors.text.primary },
  detail: { fontSize: 13, color: colors.text.secondary },
  pnl: { fontSize: 13, fontWeight: '600' },
  verified: { fontSize: 11, color: colors.text.light, marginTop: 2 },
});
