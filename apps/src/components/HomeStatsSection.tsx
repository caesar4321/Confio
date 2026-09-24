import React, { useEffect, useMemo, useRef } from 'react';
import {
  AppState,
  type AppStateStatus,
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { gql, useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors } from '../config/theme';
import { useCurrency } from '../hooks/useCurrency';
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
    return `${v.toFixed(decimal).replace('.', decimalSeparator)} M`;
  }
  try {
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
      .format(r)
      .replace(/,/g, thousandsSeparator);
  } catch {
    return `${r}`;
  }
};

const CONTAINER_PADDING = 16;
const GRID_COLUMNS = 2;

// Five tiles: proof row of three (Usuarios · Ahorros · Movido) over the
// offers row of two (Acciones · Preventa) — still two rows, so the block
// keeps its height instead of growing a third row with a lonely cell.
const chunkIntoRows = <T,>(items: T[]): T[][] => {
  if (items.length === 5) return [items.slice(0, 3), items.slice(3)];
  const rows: T[][] = [];
  for (let i = 0; i < items.length; i += GRID_COLUMNS) {
    rows.push(items.slice(i, i + GRID_COLUMNS));
  }
  return rows;
};

type Tile = {
  key: string;
  icon: string;
  value: string;
  unit?: string;
  label: string;
  descriptor: string;
  descriptorColor?: string;
  /** Omitted for a read-only stat: no chevron, not announced as a button. */
  onPress?: () => void;
};

type HomeStatsSectionProps = {
  refreshNonce?: number;
};

export const HomeStatsSection: React.FC<HomeStatsSectionProps> = ({
  refreshNonce = 0,
}) => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
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
  const thousandsSeparator = currency.thousandsSeparator;
  const decimalSeparator = currency.decimalSeparator;
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
      };
      // An offer, so it sits in the offers row next to Preventa: the catalog
      // size until the invested total is meaningful (server-gated at
      // GM_HOME_INVESTED_MIN_USD), then what users actually hold.
      const stocks: Tile | null = stockInvestedUsd != null
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
        descriptorColor: colors.violet,
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
     stockAssetCount, stockInvestedUsd,
     s?.presaleCusdRaised, thousandsSeparator, decimalSeparator, navigation]
  );

  const accessibilityLabelFor = (tile: Tile) =>
    `${tile.label}: ${tile.value}${tile.unit ? ` ${tile.unit}` : ''}. ${tile.descriptor}`;

  // Three tiles: the original one-row strip, untouched.
  const renderStripTile = (tile: Tile) => (
    <TouchableOpacity
      key={tile.key}
      style={styles.tile}
      activeOpacity={0.7}
      onPress={tile.onPress}
      disabled={!tile.onPress}
      accessibilityRole={tile.onPress ? 'button' : 'text'}
      accessibilityLabel={accessibilityLabelFor(tile)}
    >
      <View style={styles.tileTopRow}>
        <Icon name={tile.icon} size={13} color={colors.primary} />
        {tile.onPress && <Icon name="chevron-right" size={14} color="#9CA3AF" />}
      </View>
      <Text
        style={styles.tileValue}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.65}
      >
        {tile.value}
        {tile.unit ? <Text style={styles.tileUnit}> {tile.unit}</Text> : null}
      </Text>
      <Text
        style={styles.tileLabel}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.75}
      >
        {tile.label}
      </Text>
      <Text
        style={[
          styles.tileDescriptor,
          tile.descriptorColor ? { color: tile.descriptorColor } : null,
        ]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.8}
      >
        {tile.descriptor}
      </Text>
    </TouchableOpacity>
  );

  // Four tiles: 2x2. A grid cell is ~twice the width of a strip tile, so it
  // does NOT reuse the strip's four stacked lines — that is what made the
  // first grid attempt tall enough to shove the wallets down (four lines ≈
  // 91pt per tile, ≈190pt for two rows, about two wallet cards of height for
  // a stats block). Width is the resource we just gained and height is the
  // one we cannot spend, so the cell spends the width instead: icon and value
  // share one line, label and descriptor share the next. Two lines ≈ 56pt,
  // so the whole grid lands near 128pt — every stat full size, nothing
  // hidden, nothing scrolling.
  // `compact` = a third-width cell (the five-tile proof row): the merged
  // "label · descriptor" line doesn't fit there, so it splits in two. That
  // row grows ~13pt; the offers row keeps the two-line cell. It also drops
  // the chevron and may shrink further so a value never ends in "…".
  const renderGridCell = (tile: Tile, compact = false) => (
    <TouchableOpacity
      key={tile.key}
      style={styles.cell}
      activeOpacity={0.7}
      onPress={tile.onPress}
      disabled={!tile.onPress}
      accessibilityRole={tile.onPress ? 'button' : 'text'}
      accessibilityLabel={accessibilityLabelFor(tile)}
    >
      <View style={styles.cellValueRow}>
        <Icon name={tile.icon} size={13} color={colors.primary} />
        <Text
          style={styles.cellValue}
          numberOfLines={1}
          adjustsFontSizeToFit
          minimumFontScale={compact ? 0.6 : 0.7}
        >
          {tile.value}
          {tile.unit ? <Text style={styles.tileUnit}> {tile.unit}</Text> : null}
        </Text>
        {/* Third-width cells drop the chevron: icon + chevron + padding left
            ~58pt for "6.789 USD" on a 375pt iPhone and iOS truncated it to
            "6.789…". The whole cell stays tappable. */}
        {tile.onPress && !compact && <Icon name="chevron-right" size={14} color="#9CA3AF" />}
      </View>
      {/* Label and descriptor merged onto one line. Sentence case, no
          letter-spacing: the strip's uppercase treatment is ~15% wider and
          "Usuarios · Didit: 1.234" does not survive it at half-container
          width. The descriptor keeps its own color so Preventa's violet
          accent still reads. */}
      {compact ? (
        <>
          <Text style={styles.cellMeta} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.75}>
            {tile.label}
          </Text>
          <Text
            style={[styles.cellDescriptor, tile.descriptorColor ? { color: tile.descriptorColor } : null]}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.75}
          >
            {tile.descriptor}
          </Text>
        </>
      ) : (
        <Text
          style={styles.cellMeta}
          numberOfLines={1}
          adjustsFontSizeToFit
          minimumFontScale={0.75}
        >
          {tile.label}
          <Text style={styles.cellMetaSeparator}> · </Text>
          <Text style={tile.descriptorColor ? { color: tile.descriptorColor } : undefined}>
            {tile.descriptor}
          </Text>
        </Text>
      )}
    </TouchableOpacity>
  );

  return (
    <View style={styles.container}>
      {tiles.length > 3 ? (
        // One card with a hairline cross rather than four separate bordered
        // cards: four borders and four shadows is a lot of visual weight for
        // a section that sits directly above the wallets, and the single
        // container matches the three-tile strip it replaces.
        <View style={[styles.card, styles.grid]}>
          {chunkIntoRows(tiles).map((row, rowIdx) => (
            <React.Fragment key={row.map(t => t.key).join('-')}>
              {rowIdx > 0 && <View style={styles.rowDivider} />}
              <View style={styles.gridRow}>
                {row.map((tile, idx) => (
                  <React.Fragment key={tile.key}>
                    {idx > 0 && <View style={styles.divider} />}
                    {renderGridCell(tile, row.length > GRID_COLUMNS)}
                  </React.Fragment>
                ))}
                {/* Odd tile count would leave a half-width cell stretched
                    across the row; hold the column instead. */}
                {row.length === 1 && <View style={styles.cell} />}
              </View>
            </React.Fragment>
          ))}
        </View>
      ) : (
        <View style={[styles.card, styles.strip]}>
          {tiles.map((tile, idx) => (
            <React.Fragment key={tile.key}>
              {idx > 0 && <View style={styles.divider} />}
              {renderStripTile(tile)}
            </React.Fragment>
          ))}
        </View>
      )}
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
    backgroundColor: '#fff',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    paddingVertical: 12,
    paddingHorizontal: 4,
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 1,
  },
  // Three tiles side by side.
  strip: {
    flexDirection: 'row',
    alignItems: 'stretch',
  },
  // Two rows of two, stacked.
  grid: {
    flexDirection: 'column',
  },
  tile: {
    flex: 1,
    paddingHorizontal: 8,
  },
  gridRow: {
    flexDirection: 'row',
    alignItems: 'stretch',
  },
  cell: {
    flex: 1,
    paddingHorizontal: 8,
    paddingVertical: 2,
    justifyContent: 'center',
  },
  cellValueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  cellValue: {
    flex: 1,
    fontSize: 18,
    fontWeight: '800',
    color: colors.primary,
    includeFontPadding: false,
  },
  cellMeta: {
    fontSize: 10,
    color: colors.dark,
    marginTop: 3,
    fontWeight: '700',
  },
  cellDescriptor: {
    fontSize: 10,
    color: '#6B7280',
    marginTop: 1,
    fontWeight: '600',
  },
  cellMetaSeparator: {
    color: '#9CA3AF',
    fontWeight: '600',
  },
  rowDivider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: '#E5E7EB',
    marginHorizontal: 4,
    marginVertical: 10,
  },
  tileTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  tileValue: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.primary,
    includeFontPadding: false,
  },
  tileUnit: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.primary,
  },
  tileLabel: {
    fontSize: 11,
    color: colors.dark,
    marginTop: 4,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  tileDescriptor: {
    fontSize: 10,
    color: '#6B7280',
    marginTop: 2,
    fontWeight: '600',
  },
  divider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: '#E5E7EB',
    marginVertical: 4,
  },
});
