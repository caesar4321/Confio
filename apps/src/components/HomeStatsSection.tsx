import React, { useEffect, useMemo, useRef } from 'react';
import {
  AppState,
  type AppStateStatus,
  View,
  StyleSheet,
  TouchableOpacity,
} from 'react-native';
import { Text } from './common/AppText';
import Icon from 'react-native-vector-icons/Feather';
import { gql, useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors } from '../config/theme';
import { useNumberLocale } from '../contexts/NumberLocaleProvider';
import { formatDecimal } from '../utils/numberLocale';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';
import { useGmHomeTile } from '../hooks/useGmMarket';

// All-time deposits + withdrawals, each counted once at the delivery
// boundary (ramps/metrics.py). Own query per the new-field rule: an older
// server fails only this tile, never the shared stats snapshot.
const FUND_FLOW_STATS = gql`
  query FundFlowStats {
    fundFlowStats {
      totalUsd
      operationCount
    }
  }
`;

type StatsSummary = {
  totalUsers?: number | null;
  diditVerifiedUsers?: number | null;
  protectedSavings?: number | null;
  totalValueLocked?: number | null;
  usdyReserve?: number | null;
  cusdBscReserve?: number | null;
  presaleCusdRaised?: number | null;
  ondoStocksTvl?: number | null;
};

// Latino-friendly number formatting: full numbers up to 999,999 with the
// locale thousands separator (typically "." in LATAM Spanish). "M" only kicks
// in at one million+. No "K" — most readers don't parse it consistently.
const formatLocale = (
  n: number | null | undefined,
  thousandsSeparator: string,
  decimalSeparator: string
): string => {
  if (n == null) return '—';
  const r = Math.round(n);
  if (r >= 1_000_000) {
    const v = r / 1_000_000;
    const decimal = v < 10 ? 1 : 0;
    return `${formatDecimal(v, { decimals: decimal, separators: { group: thousandsSeparator, decimal: decimalSeparator } })} M`;
  }
  return formatDecimal(r, { decimals: 0, separators: { group: thousandsSeparator, decimal: decimalSeparator } });
};

const CONTAINER_PADDING = 16;

// Design A (2026-10-04): one hue per tile so the row scans at a glance.
// Acciones is indigo, not violet: violet stays reserved for $CONFIO
// (DESIGN.md), and Preventa takes the mockup's amber.
const TILE_COLORS = {
  users: colors.primaryDark, // emerald
  savings: colors.primaryDark, // emerald
  flow: colors.accent, // blue
  stocks: '#6366F1', // indigo
  presale: '#F59E0B', // amber
} as const;
type Tile = {
  key: string;
  icon: string;
  value: string;
  unit?: string;
  label: string;
  /** The detail behind the number (Didit count, backing assets, …). Not shown
   *  on Home (design A: icon, number, one word); read to screen readers and
   *  shown on the screen the tile opens. */
  descriptor: string;
  /** Omitted for a read-only stat: not announced as a button. */
  onPress?: () => void;
};

type HomeStatsSectionProps = {
  refreshNonce?: number;
  /** The portfolio's stocks.enabled — the same flag the explorer checks.
   * The tile must never offer a screen that will answer "no disponibles". */
  stocksEnabled?: boolean;
};

export const HomeStatsSection: React.FC<HomeStatsSectionProps> = ({
  refreshNonce = 0,
  stocksEnabled = false,
}) => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { separators } = useNumberLocale();
  const { data, refetch } = useQuery(GET_STATS_SUMMARY, {
    // The server owns the one universal snapshot. Never promote a prior
    // device-local Apollo result to authoritative on a later execution.
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'network-only',
    pollInterval: 300_000, // follows the server's marked-to-market stock snapshot cadence
  });
  // Cumulative and cached: it only grows, so the last value painted on a
  // reopen is never an overstatement of anything that has since shrunk.
  const { data: flowData, refetch: refetchFlow } = useQuery(FUND_FLOW_STATS, {
    fetchPolicy: 'cache-and-network',
    errorPolicy: 'all',
    // Home stays mounted while the user navigates, so mount/refresh/foreground
    // alone could leave it stale; follow the server's 10-minute cache.
    pollInterval: 600_000,
  });
  // Shared with Home's Acciones row through Apollo's cache. Null for users
  // outside Ondo's eligibility — then the tile is simply absent.
  const { assetCount: stockAssetCount, investedUsd: stockInvestedUsd, refetch: refetchStockTile } = useGmHomeTile();
  const flowTotalUsd: number | null = flowData?.fundFlowStats?.totalUsd ?? null;
  const flowOperations: number | null = flowData?.fundFlowStats?.operationCount ?? null;
  const previousRefreshNonce = useRef(refreshNonce);
  const previousAppState = useRef<AppStateStatus | null>(AppState.currentState);

  useEffect(() => {
    if (refreshNonce === previousRefreshNonce.current) return;
    previousRefreshNonce.current = refreshNonce;
    refetch().catch(() => {});
    refetchFlow().catch(() => {});
    refetchStockTile().catch(() => {});
  }, [refreshNonce, refetch, refetchFlow, refetchStockTile]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', nextState => {
      const returningToForeground =
        previousAppState.current != null &&
        /inactive|background/.test(previousAppState.current) &&
        nextState === 'active';
      previousAppState.current = nextState;
      if (returningToForeground) {
        refetch().catch(() => {});
        refetchFlow().catch(() => {});
        refetchStockTile().catch(() => {});
      }
    });
    return () => subscription.remove();
  }, [refetch, refetchFlow, refetchStockTile]);

  const s: StatsSummary | undefined = data?.statsSummary;
  const thousandsSeparator = separators.group;
  const decimalSeparator = separators.decimal;
  // Keep each reserve independent in the API and add them only for this
  // portfolio-level tile: legacy a-cUSD/USDC, cUSD/USDT, cUSD+/USDY.
  const legacyCusdReserve = s?.totalValueLocked ?? s?.protectedSavings ?? null;
  const cusdReserve = s?.cusdBscReserve ?? null;
  const usdyReserve = s?.usdyReserve ?? null;
  // Missing network data is unknown, not a real zero. This matters now that
  // the universal server snapshot deliberately bypasses Apollo's local read.
  const tvl = legacyCusdReserve == null || cusdReserve == null || usdyReserve == null
    ? null
    : legacyCusdReserve + cusdReserve + usdyReserve;
  const backingDescriptor = tvl == null
    ? 'Reservas'
    : [
        (legacyCusdReserve ?? 0) / Math.max(tvl, 1) >= 0.01 ? 'USDC' : null,
        (cusdReserve ?? 0) / Math.max(tvl, 1) >= 0.01 ? 'USDT' : null,
        (usdyReserve ?? 0) / Math.max(tvl, 1) >= 0.01 ? 'USDY' : null,
      ].filter(Boolean).join(' · ') || 'Reservas';
  const verified = s?.diditVerifiedUsers ?? 0;
  const fmt = (value: number | null | undefined) =>
    formatLocale(value, thousandsSeparator, decimalSeparator);

  const tiles: Tile[] = useMemo(
    () => {
      const users: Tile = {
        key: 'users',
        icon: 'users',
        value: fmt(s?.totalUsers),
        label: 'Usuarios',
        descriptor: verified > 0 ? `Didit: ${fmt(verified)}` : 'Con teléfono',
        onPress: () => navigation.navigate('LatamCommunity'),
      };
      const savings: Tile = {
        key: 'savings',
        icon: 'shield',
        value: fmt(tvl),
        // Dollars, not a token ticker: the figure now blends cUSD and cUSD+.
        unit: 'USD',
        // UI copy stays Spanish (identifiers-in-English rule is code-only).
        label: 'Ahorros',
        // The "what is USDY" education lives in the Ahorros hub — the tile
        // only names the backing assets (see backingDescriptor above).
        descriptor: backingDescriptor,
        onPress: () => navigation.navigate('ProtectedSavings'),
      };
      // Money that actually moved through Confío, both ways. "Retiros" is
      // deliberate: proof that money gets OUT is what LATAM users check.
      // Cumulative, so it never drops when a large holder leaves — the
      // reserves figure (Ahorros) is the one that honestly moves with them.
      const flow: Tile = {
        key: 'flow',
        icon: 'repeat',
        value: fmt(flowTotalUsd),
        unit: 'USD',
        label: 'Movido',
        descriptor: flowOperations != null
          ? `${fmt(flowOperations)} depósitos y retiros`
          : 'Depósitos y retiros',
        // The breakdown: split, typical withdrawal time, countries, method.
        onPress: () => navigation.navigate('FundFlow'),
      };
      // An offer, so it sits in the offers row next to Preventa: the catalog
      // size until the invested total is meaningful (server-gated at
      // GM_HOME_INVESTED_MIN_USD), then what users actually hold.
      // Visibility follows stocksEnabled (the explorer's own gate); the
      // count query still starts in parallel, so it is ready when shown.
      const stocks: Tile | null = !stocksEnabled
        ? null
        : stockInvestedUsd != null
        ? {
          key: 'stocks',
          icon: 'trending-up',
          value: fmt(stockInvestedUsd),
          unit: 'USD',
          label: 'Acciones',
          descriptor: 'Invertido en EE.UU.',
          onPress: () => navigation.navigate('StocksList'),
        }
        : stockAssetCount != null
          ? {
            key: 'stocks',
            icon: 'trending-up',
            value: fmt(stockAssetCount),
            label: 'Acciones',
            // No trailing "…": in a one-line cell it read as truncated.
            descriptor: 'S&P 500, Apple, oro y más',
            onPress: () => navigation.navigate('StocksList'),
          }
          : null;
      const presale: Tile = {
        key: 'presale',
        icon: 'zap',
        value: fmt(s?.presaleCusdRaised),
        // Dollars, like the savings tile: the presale now charges on BSC and
        // the raise spans cUSD (legacy) and Confío Dollar contributions.
        unit: 'USD',
        label: 'Preventa',
        descriptor: '$CONFIO',

        onPress: () => navigation.navigate('ConfioPresale'),
      };

      // Order is PROOF FIRST, OFFER LAST, and it does not bend for layout.
      //
      // Usuarios / Ahorros / Acciones are verifiable facts about the network;
      // Preventa is an ask. Preventa is also the raise's only passive surface
      // on Home while we are raising (the banner above is claim-only by
      // design), so there is standing pressure to promote it — don't. On a
      // wallet whose entire pitch is safety, an ask sitting above the trust
      // numbers costs more credibility than the extra taps are worth. If the
      // raise needs a louder surface, it gets its OWN affordance; it does not
      // get to outrank the proof inside the proof strip.
      return stocks
        ? [users, savings, flow, stocks, presale]
        : [users, savings, flow, presale];
    },
    [s?.totalUsers, verified, tvl, backingDescriptor, flowTotalUsd, flowOperations,
     stockAssetCount, stockInvestedUsd, stocksEnabled,
     s?.presaleCusdRaised, thousandsSeparator, decimalSeparator, navigation]
  );

  const accessibilityLabelFor = (tile: Tile) =>
    `${tile.label}: ${tile.value}${tile.unit ? ` ${tile.unit}` : ''}. ${tile.descriptor}`;

  // One row, every tile the same (design A, 2026-10-04): icon, number,
  // one word. Calm on Home; each tile opens the screen with the details.
  const renderTile = (tile: Tile) => (
    <TouchableOpacity
      key={tile.key}
      style={styles.tile}
      activeOpacity={0.7}
      onPress={tile.onPress}
      disabled={!tile.onPress}
      accessibilityRole={tile.onPress ? 'button' : 'text'}
      accessibilityLabel={accessibilityLabelFor(tile)}
    >
      <Icon name={tile.icon} size={18} color={TILE_COLORS[tile.key as keyof typeof TILE_COLORS] ?? colors.primaryDark} />
      {/* Exact numbers (no K/M); a long one shrinks instead of wrapping. The
          unit sits on its own small line so the number gets the tile's full
          width (~53pt each on a 320pt phone); every tile reserves that line so
          the labels stay aligned. Font scale is capped for the same reason. */}
      <Text style={styles.tileValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.5}
        maxFontSizeMultiplier={1.2}>
        {tile.value}
      </Text>
      <Text style={styles.tileUnit} numberOfLines={1} maxFontSizeMultiplier={1.2}>{tile.unit ?? ' '}</Text>
      <Text style={styles.tileLabel} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}
        maxFontSizeMultiplier={1.2}>
        {tile.label}
      </Text>
    </TouchableOpacity>
  );

  return (
    <View style={styles.container}>
      <View style={styles.card}>
        {tiles.map((tile, idx) => (
          <React.Fragment key={tile.key}>
            {idx > 0 && <View style={styles.divider} />}
            {renderTile(tile)}
          </React.Fragment>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: CONTAINER_PADDING,
    marginTop: 4,
    marginBottom: 0,
  },
  card: {
    flexDirection: 'row',
    alignItems: 'stretch',
    backgroundColor: '#fff',
    borderRadius: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    paddingVertical: 14,
    paddingHorizontal: 0,
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  tile: {
    flex: 1,
    alignItems: 'center',
    paddingHorizontal: 2,
    minHeight: 44,
  },
  tileValue: {
    marginTop: 8,
    alignSelf: 'stretch',
    textAlign: 'center',
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
    fontVariant: ['tabular-nums'],
    includeFontPadding: false,
  },
  tileUnit: {
    fontSize: 9,
    lineHeight: 11,
    fontWeight: '600',
    color: '#6B7280',
  },
  tileLabel: {
    marginTop: 3,
    fontSize: 11,
    fontWeight: '500',
    color: '#6B7280',
  },
  divider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: '#E5E7EB',
    marginVertical: 6,
  },
});
