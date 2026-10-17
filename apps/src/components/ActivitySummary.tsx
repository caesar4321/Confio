import React from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useAccount } from '../contexts/AccountContext';
import { useRampCountry } from '../hooks/useRampCountry';
import Icon from 'react-native-vector-icons/Feather';
import { Text } from './common/AppText';
import { colors } from '../config/theme';

/** What a Comunidad post made from a money movement shows (communityPostExtras.activity). */
export type ActivityShare = {
  kind: 'stock_buy' | 'stock_sell' | 'top_up' | 'withdraw' | 'send' | 'receive' | 'pay' | string;
  date?: string | null;
  amountUsd?: string | null;
  ticker?: string | null;
  name?: string | null;
  rail?: string | null;
  country?: string | null;
  minutes?: number | null;
  /** Pay: the business paid; null for a personal merchant (never named). */
  merchant?: string | null;
  /** A local-account transfer (Infinia): send/receive name the rail only. */
  local?: boolean | null;
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
  pay: 'shopping-bag',
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
      return a.local ? `Envió por ${a.rail || 'transferencia'}` : 'Envió a otro usuario de Confío';
    case 'receive':
      return a.local ? 'Recibió por su cuenta local' : 'Recibió de otro usuario de Confío';
    case 'pay':
      return a.merchant ? `Pagó en ${a.merchant}` : 'Pagó con QR';
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
  if (a.local && a.country) {
    // Local payments, sends and receipts: where, never who.
    return `${flag(a.country)} ${COUNTRY_NAMES[a.country] || a.country}`.trim();
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

const OWNER_ONLY_ROUTES = new Set(['TopUp', 'Sell']);

/**
 * Where tapping a post's activity takes the reader: the stock's own page
 * (where they can look and buy), or the matching money screen to do the
 * same thing themselves. Null when there's nowhere sensible to go.
 */
export function activityDestination(activity: ActivityShare): { route: string; params?: object; label: string } | null {
  switch (activity.kind) {
    case 'stock_buy':
    case 'stock_sell':
      return activity.ticker
        ? { route: 'StockDetail', params: { ticker: activity.ticker }, label: `Ver ${activity.ticker}` }
        : null;
    // The promoted dollar rail (USDT on BSC → Confío Dollar / Dollar+), the
    // same door Recibir's "Recargar" and Enviar's "Retirar" open. Without a
    // destination these screens would pick the legacy Algorand cUSD.
    case 'top_up':
      return { route: 'TopUp', params: { destination: 'cusd_plus' }, label: 'Recargar dólares' };
    case 'withdraw':
      return { route: 'Sell', params: { destination: 'cusd_plus' }, label: 'Retirar dólares' };
    case 'send':
    case 'receive':
      return { route: 'Send', label: 'Enviar dinero' };
    case 'pay':
      return { route: 'Scan', params: { mode: 'pagar' }, label: 'Pagar con QR' };
    default:
      return null;
  }
}

/**
 * The verified part of a post made from a money movement: what happened,
 * the amount (unless the member hid it) and, for stocks, how it went.
 * Used by the share sheet's preview and by every feed card.
 */
export function ActivitySummary({
  activity,
  compact = false,
  navigable = false,
}: {
  activity: ActivityShare;
  compact?: boolean;
  /** In the feed and post detail: tapping opens the stock or money screen. */
  navigable?: boolean;
}) {
  const amount = usd(activity.amountUsd);
  const detail = detailFor(activity);
  const destination = useActivityDestination(navigable ? activity : null);
  const content = (
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
      {destination ? <Icon name="chevron-right" size={18} color={colors.text.light} style={styles.chevron} /> : null}
    </View>
  );
  if (!destination) return content;
  return OWNER_ONLY_ROUTES.has(destination.route) ? (
    <RampSummary activity={activity} destination={destination}>{content}</RampSummary>
  ) : (
    <NavigableSummary activity={activity} destination={destination}>{content}</NavigableSummary>
  );
}

type Destination = { route: string; params?: object; label: string };

/** The activity's destination for this viewer: employees never reach the
 * owner's money rails (Recargar / Retirar). Null for no activity. */
export function useActivityDestination(activity: ActivityShare | null | undefined): Destination | null {
  const { activeAccount } = useAccount();
  const isEmployee = Boolean((activeAccount as { isEmployee?: boolean } | null)?.isEmployee);
  const target = activity ? activityDestination(activity) : null;
  return target && isEmployee && OWNER_ONLY_ROUTES.has(target.route) ? null : target;
}

/** What a screen reader says for the activity: the movement itself. */
export const activityAccessibilityLabel = (activity: ActivityShare) => {
  const parts = [activity.headline];
  if (activity.pnlPct && activity.kind === 'stock_buy') {
    parts.push(`${activity.position === 'closed' ? 'al vender' : 'desde la compra'} ${activity.pnlPct}%`);
  }
  return parts.join(', ');
};

type SummaryLinkProps = { activity: ActivityShare; destination: Destination; children: React.ReactNode };

function NavigableSummary({ activity, destination, children }: SummaryLinkProps) {
  const navigation = useNavigation<any>();
  return (
    <SummaryLink activity={activity} destination={destination}
      onPress={() => navigation.navigate(destination.route, destination.params)}>
      {children}
    </SummaryLink>
  );
}

/** Recargar / Retirar go through the same country gate as everywhere else:
 * where no ramp provider operates, it opens the cash directory instead. */
function RampSummary({ activity, destination, children }: SummaryLinkProps) {
  const { navigateToRampOrEfectivo } = useRampCountry();
  return (
    <SummaryLink activity={activity} destination={destination}
      onPress={() => navigateToRampOrEfectivo(destination.route as 'TopUp' | 'Sell', destination.params as any)}>
      {children}
    </SummaryLink>
  );
}

function SummaryLink({ activity, destination, children, onPress }: SummaryLinkProps & { onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      // The movement is the content; where it goes is the hint.
      accessibilityLabel={activityAccessibilityLabel(activity)}
      accessibilityHint={destination.label}
      style={({ pressed }) => (pressed ? styles.pressed : undefined)}
    >
      {children}
    </Pressable>
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
  chevron: { alignSelf: 'center' },
  pressed: { opacity: 0.7 },
});
