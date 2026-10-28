import React, { useState } from 'react';
import { useNavigation } from '@react-navigation/native';
import { useAccount } from '../contexts/AccountContext';
import { Pressable, StyleSheet, Switch, View } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

import { Text } from './common/AppText';
import { colors } from '../config/theme';
import {
  formatAmount,
  formatShares,
  formatHoldTime,
  formatMemberSince,
  formatPctAbs,
  formatPctSigned,
  formatShortDate,
  formatUsd,
  isZeroAmount,
  moneyParts,
  signOf,
  tradeCountLabel,
} from '../utils/portfolioFormat';

export type PortfolioOpenPosition = {
  symbol: string;
  ticker: string;
  name: string;
  units: string;
  valueUsd?: string | null;
  investedUsd?: string | null;
  avgEntryUsd?: string | null;
  pnlUsd?: string | null;
  pnlPct?: string | null;
  dayChangePct?: string | null;
};

/** Where a position opens: the stock's page (an Ondo token is the ticker
 * plus "on": PBR → PBRon) or the Bitcoin & gold asset page. */
export const positionDestination = (position: Pick<PortfolioOpenPosition, 'symbol' | 'ticker'>) => {
  if (!position.symbol || !position.ticker) return null;
  return position.symbol === `${position.ticker}on`
    ? { route: 'StockDetail', params: { ticker: position.ticker } }
    : { route: 'CryptoDetail', params: { symbol: position.symbol } };
};

export type PortfolioClosedPosition = {
  ticker: string;
  name: string;
  investedUsd: string;
  proceedsUsd: string;
  pnlUsd: string;
  pnlPct?: string | null;
  closedOn: string;
};

export type CommunityMemberPortfolio = {
  userId: string;
  isSelf: boolean;
  hidden: boolean;
  totalUsd?: string | null;
  dollarsUsd?: string | null;
  stocksUsd?: string | null;
  /** Bitcoin & gold (its own query; absent on older servers). */
  cryptoUsd?: string | null;
  stocksChange24hUsd?: string | null;
  presaleConfio?: string | null;
  presaleInvestedUsd?: string | null;
  tradeCount: number | null;
  avgHoldSeconds?: number | null;
  memberSince?: string | null;
  /** Null when holdings or history couldn't be read: unavailable, never empty. */
  openPositions: PortfolioOpenPosition[] | null;
  closedPositions: PortfolioClosedPosition[] | null;
};

const GAIN = colors.successText;
const LOSS = colors.error.icon;

const toneOf = (value: string | null | undefined) => {
  const sign = signOf(value);
  return sign === 1 ? GAIN : sign === -1 ? LOSS : colors.textSecondary;
};

/** "▲ 12.30%" in green / "▼ 4.10%" in red; nothing when unknown. */
const PctChange = ({ value, style }: { value?: string | null; style?: object }) => {
  const abs = formatPctAbs(value);
  if (abs === null) return null;
  const sign = signOf(value);
  const arrow = sign === 1 ? '▲ ' : sign === -1 ? '▼ ' : '';
  return <Text style={[styles.pct, { color: toneOf(value) }, style]}>{`${arrow}${abs}`}</Text>;
};

type Props = {
  portfolio: CommunityMemberPortfolio;
  onToggleHidden?: (hidden: boolean) => void;
  hiddenBusy?: boolean;
};

/** A member's anonymous asset profile: totals, breakdown and positions. */
export const CommunityPortfolioSection = ({ portfolio, onToggleHidden, hiddenBusy }: Props) => {
  const navigation = useNavigation<any>();
  const { activeAccount } = useAccount();
  const isEmployee = Boolean((activeAccount as { isEmployee?: boolean } | null)?.isEmployee);
  const [tab, setTab] = useState<'open' | 'closed'>('open');
  const [expanded, setExpanded] = useState<string | null>(null);

  const ownHidden = portfolio.isSelf && portfolio.hidden;
  const holdTime = formatHoldTime(portfolio.avgHoldSeconds);
  const memberSince = formatMemberSince(portfolio.memberSince);
  const total = moneyParts(portfolio.totalUsd);
  const dayChange = formatUsd(portfolio.stocksChange24hUsd, { signed: true });
  const dollars = formatUsd(portfolio.dollarsUsd);
  const stocks = formatUsd(portfolio.stocksUsd);
  // A zero row would read as "holds some": shown only when something is held.
  const crypto = portfolio.cryptoUsd && !isZeroAmount(portfolio.cryptoUsd) ? formatUsd(portfolio.cryptoUsd) : null;
  const showConfio = Boolean(portfolio.presaleConfio) && !isZeroAmount(portfolio.presaleConfio);
  const confioAmount = showConfio ? formatAmount(portfolio.presaleConfio) : null;
  const confioInvested = formatUsd(portfolio.presaleInvestedUsd);
  const openPositions = portfolio.openPositions || [];
  const closedPositions = portfolio.closedPositions || [];

  return (
    <View style={styles.section}>
      {portfolio.isSelf ? (
        <View style={styles.privacyCard}>
          <Text style={styles.privacyTitle}>Así te ven en Comunidad</Text>
          <View style={styles.privacyRow}>
            <Text style={styles.privacyLabel}>Ocultar mi perfil de inversor</Text>
            <Switch
              value={portfolio.hidden}
              onValueChange={(value) => onToggleHidden?.(value)}
              disabled={hiddenBusy || !onToggleHidden}
              trackColor={{ false: colors.borderMedium, true: colors.primaryDark }}
              thumbColor={colors.white}
              accessibilityLabel="Ocultar mi perfil de inversor"
            />
          </View>
          {ownHidden ? (
            <Text style={styles.privacyNote}>Oculto: nadie más ve tu perfil de inversor.</Text>
          ) : null}
        </View>
      ) : null}

      <View style={[styles.card, ownHidden && styles.dimmed]}>
        <View style={styles.statsRow}>
          {portfolio.tradeCount !== null && portfolio.tradeCount !== undefined ? (
            <View style={styles.stat}>
              <Icon name="repeat" size={13} color={colors.textSecondary} />
              <Text style={styles.statText}>{tradeCountLabel(portfolio.tradeCount)}</Text>
            </View>
          ) : null}
          {holdTime ? (
            <View style={styles.stat}>
              <Icon name="clock" size={13} color={colors.textSecondary} />
              <Text style={styles.statText}>{`${holdTime} de media por posición`}</Text>
            </View>
          ) : null}
          {memberSince ? (
            <View style={styles.stat}>
              <Icon name="calendar" size={13} color={colors.textSecondary} />
              <Text style={styles.statText}>{`Se unió en ${memberSince}`}</Text>
            </View>
          ) : null}
        </View>

        {total ? (
          <View style={styles.totalBlock}>
            <Text style={styles.totalWhole} accessibilityLabel={`${total.whole}${total.cents}`}>
              {total.whole}
              <Text style={styles.totalCents}>{total.cents}</Text>
            </Text>
            {dayChange ? (
              <Text style={[styles.dayChange, { color: toneOf(portfolio.stocksChange24hUsd) }]}>
                {`${dayChange} en 24 h`}
              </Text>
            ) : null}
          </View>
        ) : dayChange ? (
          <Text style={[styles.dayChange, styles.dayChangeAlone, { color: toneOf(portfolio.stocksChange24hUsd) }]}>
            {`${dayChange} en 24 h`}
          </Text>
        ) : null}

        {dollars || stocks || crypto || showConfio ? (
          <View style={styles.breakdown}>
            {dollars ? (
              <BreakdownRow icon="dollar-sign" tint={colors.primarySoft} iconColor={colors.successText} label="Dólares" value={dollars} />
            ) : null}
            {stocks ? (
              <BreakdownRow icon="trending-up" tint={colors.infoLight} iconColor={colors.accent} label="Acciones de EE.UU." value={stocks} />
            ) : null}
            {crypto ? (
              <BreakdownRow icon="hexagon" tint={colors.warning.background} iconColor={colors.warning.icon} label="Oro y Bitcoin" value={crypto} />
            ) : null}
            {showConfio && confioAmount ? (
              <BreakdownRow
                icon="star"
                tint={colors.violetLight}
                iconColor={colors.secondaryDark}
                label="CONFIO (preventa)"
                value={`${confioAmount} CONFIO`}
                secondary={confioInvested ? `US${confioInvested} invertidos` : undefined}
              />
            ) : null}
          </View>
        ) : null}
      </View>

      <View style={[styles.card, ownHidden && styles.dimmed]}>
        <Text style={styles.positionsTitle}>Posiciones</Text>
        <View style={styles.segmented} accessibilityRole="tablist">
          {(['open', 'closed'] as const).map((key) => {
            const active = tab === key;
            const list = key === 'open' ? portfolio.openPositions : portfolio.closedPositions;
            const count = list ? ` (${list.length})` : '';
            const label = key === 'open' ? `Abiertas${count}` : `Cerradas${count}`;
            return (
              <Pressable
                key={key}
                onPress={() => setTab(key)}
                style={[styles.segment, active && styles.segmentActive]}
                accessibilityRole="tab"
                accessibilityState={{ selected: active }}
              >
                <Text style={[styles.segmentText, active && styles.segmentTextActive]}>{label}</Text>
              </Pressable>
            );
          })}
        </View>

        {(tab === 'open' ? portfolio.openPositions : portfolio.closedPositions) == null ? (
          <Text style={styles.empty}>No pudimos cargar estas posiciones ahora.</Text>
        ) : tab === 'open' ? (
          openPositions.length === 0 ? (
            <Text style={styles.empty}>Sin posiciones abiertas</Text>
          ) : (
            openPositions.map((position, index) => {
              const key = `${position.symbol || position.ticker}-${index}`;
              const details = [
                position.investedUsd ? `Invertido ${formatUsd(position.investedUsd)}` : null,
                position.avgEntryUsd ? `Entrada prom. ${formatUsd(position.avgEntryUsd)}` : null,
                position.pnlUsd ? `Resultado ${formatUsd(position.pnlUsd, { signed: true })}` : null,
                position.dayChangePct ? `Hoy ${formatPctSigned(position.dayChangePct)}` : null,
              ].filter(Boolean);
              const canExpand = details.length > 0;
              const isOpen = expanded === key;
              const units = formatShares(position.units);
              // Employees never reach the asset page (it trades): the owner manages investments.
              const destination = isEmployee ? null : positionDestination(position);
              const open = () => destination && navigation.navigate(destination.route, destination.params);
              return (
                <Pressable
                  key={key}
                  onPress={() => (canExpand ? setExpanded(isOpen ? null : key) : open())}
                  disabled={!canExpand && !destination}
                  style={({ pressed }) => [styles.positionRow, index > 0 && styles.rowDivider, pressed && styles.pressed]}
                  accessibilityRole={canExpand ? 'button' : undefined}
                  accessibilityState={canExpand ? { expanded: isOpen } : undefined}
                >
                  <View style={styles.positionMain}>
                    <View style={styles.positionLeft}>
                      <Text style={styles.ticker} numberOfLines={1}>
                        {position.ticker}
                        <Text style={styles.positionName}>{`  ${position.name}`}</Text>
                      </Text>
                      {units ? (
                        <Text style={styles.secondary}>{`${units} ${Number(position.units) === 1 ? 'acción' : 'acciones'}`}</Text>
                      ) : null}
                    </View>
                    <View style={styles.positionRight}>
                      <Text style={styles.positionValue}>{formatUsd(position.valueUsd) ?? '—'}</Text>
                      <PctChange value={position.pnlPct} />
                    </View>
                  </View>
                  {isOpen ? <Text style={styles.detail}>{details.join(' · ')}</Text> : null}
                  {isOpen && destination ? (
                    <Pressable onPress={open} hitSlop={8} accessibilityRole="link" style={styles.openLink}>
                      <Text style={styles.openLinkText}>{`Ver ${position.ticker}`}</Text>
                      <Icon name="chevron-right" size={14} color={colors.primaryDark} />
                    </Pressable>
                  ) : null}
                </Pressable>
              );
            })
          )
        ) : closedPositions.length === 0 ? (
          <Text style={styles.empty}>Sin posiciones cerradas</Text>
        ) : (
          closedPositions.map((position, index) => {
            const closedOn = formatShortDate(position.closedOn);
            const pnl = formatUsd(position.pnlUsd, { signed: true });
            return (
              <View key={`${position.ticker}-${position.closedOn}-${index}`} style={[styles.positionRow, index > 0 && styles.rowDivider]}>
                <View style={styles.positionMain}>
                  <View style={styles.positionLeft}>
                    <Text style={styles.ticker} numberOfLines={1}>
                      {position.ticker}
                      <Text style={styles.positionName}>{`  ${position.name}`}</Text>
                    </Text>
                    {closedOn ? <Text style={styles.secondary}>{`Cerrada el ${closedOn}`}</Text> : null}
                  </View>
                  <View style={styles.positionRight}>
                    <Text style={[styles.positionValue, { color: pnl ? toneOf(position.pnlUsd) : colors.dark }]}>
                      {pnl ?? '—'}
                    </Text>
                    <PctChange value={position.pnlPct} />
                  </View>
                </View>
              </View>
            );
          })
        )}
      </View>
    </View>
  );
};

const BreakdownRow = ({
  icon,
  tint,
  iconColor,
  label,
  value,
  secondary,
}: {
  icon: string;
  tint: string;
  iconColor: string;
  label: string;
  value: string;
  secondary?: string;
}) => (
  <View style={styles.breakdownRow}>
    <View style={[styles.breakdownIcon, { backgroundColor: tint }]}>
      <Icon name={icon} size={16} color={iconColor} />
    </View>
    <Text style={styles.breakdownLabel} numberOfLines={1}>
      {label}
    </Text>
    <View style={styles.breakdownValues}>
      <Text style={styles.breakdownValue}>{value}</Text>
      {secondary ? <Text style={styles.secondary}>{secondary}</Text> : null}
    </View>
  </View>
);

export default CommunityPortfolioSection;

const styles = StyleSheet.create({
  section: {
    alignSelf: 'stretch',
    marginTop: 20,
    gap: 12,
  },
  privacyCard: {
    backgroundColor: colors.background,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  privacyTitle: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.textSecondary,
  },
  privacyRow: {
    marginTop: 6,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  privacyLabel: {
    flex: 1,
    fontSize: 15,
    color: colors.dark,
  },
  privacyNote: {
    marginTop: 6,
    fontSize: 13,
    color: colors.textSecondary,
  },
  card: {
    backgroundColor: colors.background,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
  },
  dimmed: {
    opacity: 0.55,
  },
  statsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    columnGap: 14,
    rowGap: 6,
  },
  stat: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  statText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  totalBlock: {
    marginTop: 14,
  },
  totalWhole: {
    fontSize: 34,
    fontWeight: '700',
    color: colors.dark,
    letterSpacing: -0.5,
  },
  totalCents: {
    fontSize: 22,
    fontWeight: '600',
    color: colors.textTertiary,
  },
  dayChange: {
    marginTop: 2,
    fontSize: 14,
    fontWeight: '600',
  },
  dayChangeAlone: {
    marginTop: 12,
  },
  breakdown: {
    marginTop: 16,
    gap: 12,
  },
  breakdownRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  breakdownIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  breakdownLabel: {
    flex: 1,
    fontSize: 15,
    color: colors.dark,
  },
  breakdownValues: {
    alignItems: 'flex-end',
  },
  breakdownValue: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.dark,
  },
  positionsTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  segmented: {
    marginTop: 12,
    marginBottom: 4,
    flexDirection: 'row',
    backgroundColor: colors.neutralDark,
    borderRadius: 10,
    padding: 3,
  },
  segment: {
    flex: 1,
    paddingVertical: 7,
    borderRadius: 8,
    alignItems: 'center',
  },
  segmentActive: {
    backgroundColor: colors.background,
    shadowColor: colors.shadowBase,
    shadowOpacity: 0.08,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 1,
  },
  segmentText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  segmentTextActive: {
    color: colors.dark,
  },
  empty: {
    paddingVertical: 18,
    textAlign: 'center',
    fontSize: 14,
    color: colors.textSecondary,
  },
  positionRow: {
    paddingVertical: 12,
  },
  rowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.border,
  },
  pressed: {
    opacity: 0.7,
  },
  positionMain: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  positionLeft: {
    flex: 1,
    minWidth: 0,
  },
  openLink: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 2, marginTop: 8 },
  openLinkText: { fontSize: 13, fontWeight: '600', color: colors.primaryDark },
  ticker: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  positionName: {
    fontSize: 13,
    fontWeight: '400',
    color: colors.textSecondary,
  },
  secondary: {
    marginTop: 2,
    fontSize: 12,
    color: colors.textSecondary,
  },
  positionRight: {
    alignItems: 'flex-end',
  },
  positionValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
  },
  pct: {
    marginTop: 2,
    fontSize: 12,
    fontWeight: '600',
  },
  detail: {
    marginTop: 8,
    fontSize: 12,
    lineHeight: 17,
    color: colors.textSecondary,
  },
});
