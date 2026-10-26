import React from 'react';
import { StyleSheet, View } from 'react-native';

import BitcoinMark from '../svg/BitcoinMark';
import GoldMark from '../svg/GoldMark';
import { TickerLogo } from '../TickerLogo';
import { Text } from '../common/AppText';
import { tickerColor } from '../../utils/perpsPresentation';

const GOLD_TICKERS = new Set(['GOLD', 'PAXG', 'XAUT']);

/**
 * A market's mark: the asset people recognise when there is one (₿, gold,
 * a stock's logo from our mirror), else a ticker disc in a stable hue. An
 * optional leverage badge rides on the corner for open positions.
 */
export function PerpMarketMark({
  ticker,
  logoUrl,
  size = 40,
  leverage,
  badgeColor = '#0F172A',
}: {
  ticker: string;
  logoUrl?: string;
  size?: number;
  leverage?: number;
  badgeColor?: string;
}) {
  const upper = ticker.toUpperCase();
  const mark = upper === 'BTC'
    ? <BitcoinMark size={size} />
    : GOLD_TICKERS.has(upper)
      ? <GoldMark size={size} />
      : <TickerLogo ticker={upper} color={tickerColor(upper)} logoUrl={logoUrl} size={size} />;
  if (!leverage) return mark;
  return (
    <View style={{ width: size, height: size }}>
      {mark}
      <View style={[styles.badge, { backgroundColor: badgeColor, minWidth: size * 0.58 }]}>
        <Text style={styles.badgeText}>{leverage}x</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    position: 'absolute',
    right: -6,
    bottom: -4,
    borderRadius: 8,
    paddingHorizontal: 4,
    paddingVertical: 1,
    borderWidth: 1.5,
    borderColor: '#FFFFFF',
    alignItems: 'center',
  },
  badgeText: { fontSize: 10, fontWeight: '800', color: '#FFFFFF' },
});
