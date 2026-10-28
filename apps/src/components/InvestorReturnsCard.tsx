import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, LayoutChangeEvent, Pressable, StyleSheet, View } from 'react-native';
import { useApolloClient } from '@apollo/client';
import Svg, { Path } from 'react-native-svg';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import { GET_INVESTOR_RETURNS, GET_INVESTOR_TOTAL_RETURN } from '../apollo/queries';
import { formatMemberSince, formatPctSigned, formatUsd, signOf } from '../utils/portfolioFormat';
import { RETURN_RANGES, ReturnPoint, ReturnRange, returnsPath } from '../utils/returnsChart';

type Returns = {
  range: string; pct?: string | null; gainUsd?: string | null; asOf?: string | null; points: ReturnPoint[];
  // Total only: what was bought in all, and since when.
  investedUsd?: string | null; since?: string | null;
};

const CHART_HEIGHT = 120;
const GAIN = colors.successText;
const LOSS = colors.error.icon;

type Props = { userId: string; refreshKey?: number };

/**
 * "Rentabilidad": the member's return on what they invested (stocks, Bitcoin
 * & gold; never cash) for 24 h / 7 d / 30 d, as a big percent, the dollars
 * under it and a line. Unknown is "--", never 0. Renders nothing when the
 * server doesn't answer (older server, not visible to this viewer).
 */
export function InvestorReturnsCard({ userId, refreshKey = 0 }: Props) {
  const client = useApolloClient();
  const [range, setRange] = useState<ReturnRange>('7d');
  const [byRange, setByRange] = useState<Partial<Record<ReturnRange, Returns | null>>>({});
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [width, setWidth] = useState(0);
  const generation = useRef(0);

  const load = useCallback(
    async (key: ReturnRange) => {
      generation.current += 1;
      const requested = generation.current;
      setLoading(true);
      try {
        if (key === 'all') {
          // Since the first trade, from the trade record: no daily line.
          const { data } = await client.query({
            query: GET_INVESTOR_TOTAL_RETURN,
            variables: { userId },
            fetchPolicy: 'network-only',
            context: { queryDeduplication: false },
          });
          if (generation.current !== requested) return;
          const total = data?.investorTotalReturn;
          setByRange((current) => ({
            ...current,
            all: total ? { range: 'all', pct: total.pct, gainUsd: total.gainUsd, investedUsd: total.investedUsd,
              since: total.since, points: [] } : { range: 'all', pct: null, points: [] },
          }));
          return;
        }
        const { data } = await client.query({
          query: GET_INVESTOR_RETURNS,
          variables: { userId, range: key },
          fetchPolicy: 'network-only',
          // A refresh must not reuse a read started before it (e.g. pre-publish).
          context: { queryDeduplication: false },
        });
        if (generation.current !== requested) return;
        const value = (data?.investorReturns ?? null) as Returns | null;
        // null = not visible to this viewer (or no wallet): no card at all.
        if (value === null) setHidden(true);
        setByRange((current) => ({ ...current, [key]: value }));
      } catch {
        if (generation.current !== requested) return;
        // Total is its own query: failing it (an older server) only blanks that tab.
        if (key === 'all') setByRange((current) => ({ ...current, all: { range: 'all', pct: null, points: [] } }));
        else setHidden(true);
      } finally {
        if (generation.current === requested) setLoading(false);
      }
    },
    [client, userId],
  );

  useEffect(() => {
    setByRange({});
    setHidden(false);
    void load(range);
    // Only a new member or an explicit refresh resets every range.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, refreshKey]);

  if (hidden) return null;

  const current = byRange[range];
  const known = current?.pct !== null && current?.pct !== undefined;
  const sign = known ? signOf(current?.pct) : null;
  const tone = sign === 1 ? GAIN : sign === -1 ? LOSS : colors.textSecondary;
  const path = known && current ? returnsPath(current.points, width, CHART_HEIGHT) : null;
  const gain = known ? formatUsd(current?.gainUsd, { signed: true }) : null;
  const rangeLabel = RETURN_RANGES.find((r) => r.key === range)?.label ?? '';

  return (
    <View style={styles.card} accessibilityLabel="Rentabilidad">
      <View style={styles.headerRow}>
        <Text style={styles.title}>Rentabilidad</Text>
        <View style={styles.ranges} accessibilityRole="tablist">
          {RETURN_RANGES.map((r) => {
            const selected = r.key === range;
            return (
              <Pressable
                key={r.key}
                onPress={() => {
                  if (selected) return;
                  setRange(r.key);
                  if (byRange[r.key] === undefined) void load(r.key);
                }}
                style={[styles.range, selected && styles.rangeSelected]}
                accessibilityRole="tab"
                accessibilityState={{ selected }}
                hitSlop={4}
              >
                <Text style={[styles.rangeText, selected && styles.rangeTextSelected]}>{r.label}</Text>
              </Pressable>
            );
          })}
        </View>
      </View>
      {loading && current === undefined ? (
        <ActivityIndicator style={styles.loading} size="small" color={colors.primary} />
      ) : (
        <>
          <Text style={[styles.pct, { color: tone }]}>{known ? formatPctSigned(current?.pct) : '--'}</Text>
          <Text style={styles.sub}>
            {!known
              ? 'Aún no hay datos suficientes para este periodo'
              : range === 'all'
                ? [
                  `${gain ?? ''}${current?.since ? ` desde ${formatMemberSince(current.since)}` : ''}`,
                  current?.investedUsd ? `sobre ${formatUsd(current.investedUsd)} invertidos` : null,
                ].filter(Boolean).join(' · ')
                : range === '24h' ? `${gain ?? ''} hoy` : `${gain ?? ''} en ${rangeLabel}`}
          </Text>
          {range === 'all' ? null : (
            <View
              style={styles.chart}
              onLayout={(e: LayoutChangeEvent) => setWidth(Math.round(e.nativeEvent.layout.width))}
            >
              {path ? (
                <Svg width={width} height={CHART_HEIGHT}>
                  <Path d={path} stroke={tone} strokeWidth={2.5} fill="none" strokeLinejoin="round" strokeLinecap="round" />
                </Svg>
              ) : null}
            </View>
          )}
          <Text style={styles.note}>
            {range === 'all'
              ? 'Lo ganado y perdido en acciones, Bitcoin y oro desde la primera compra, vendido o no. No cuenta los dólares.'
              : 'Sobre lo invertido en acciones, Bitcoin y oro. No cuenta tus dólares.'}
          </Text>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 16,
    padding: 16,
    borderRadius: 16,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  headerRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: 15, fontWeight: '700', color: colors.dark },
  ranges: { flexDirection: 'row', gap: 4 },
  range: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 12 },
  rangeSelected: { backgroundColor: colors.neutralDark },
  rangeText: { fontSize: 13, fontWeight: '600', color: colors.textSecondary },
  rangeTextSelected: { color: colors.dark },
  loading: { marginVertical: 48 },
  pct: { marginTop: 12, fontSize: 32, fontWeight: '700' },
  sub: { marginTop: 2, fontSize: 14, color: colors.textSecondary },
  chart: { marginTop: 12, height: CHART_HEIGHT, width: '100%' },
  note: { marginTop: 8, fontSize: 12, color: colors.textSecondary },
});
