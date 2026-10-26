// Where a trade actually executes, in the same slim line as Ondo's "En
// alianza con" row — but "Se opera en", never "en alianza": PancakeSwap
// (Oro y Bitcoin) and Hyperliquid (Futuros) are independent, third-party
// decentralized exchanges Confío routes to, not partners under contract.
// The real logos make that plain to members and to App Review alike.
import React from 'react';
import { Image, StyleSheet, View } from 'react-native';
import { Text } from './common/AppText';
import { colors } from '../config/theme';
import PancakeSwapLogo from '../assets/png/PancakeSwap.png';
import HyperliquidLogo from '../assets/png/Hyperliquid.png';

export type Venue = 'pancakeswap' | 'hyperliquid';

const VENUES: Record<Venue, { name: string; logo: number }> = {
  pancakeswap: { name: 'PancakeSwap', logo: PancakeSwapLogo },
  hyperliquid: { name: 'Hyperliquid', logo: HyperliquidLogo },
};

/** The spoken line, for a card whose own label hides nested ones (a Pressable). */
export const venueA11y = (venue: Venue) =>
  `Se opera en ${VENUES[venue].name}. Exchange descentralizado de terceros, independiente de Confío.`;

export function VenueAttribution({ venue, compact = false, testID }: {
  venue: Venue;
  /** One line only (lists, cards): the "independent" note moves into the a11y label. */
  compact?: boolean;
  testID?: string;
}) {
  const { name, logo } = VENUES[venue];
  const note = 'Exchange descentralizado de terceros, independiente de Confío';
  return (
    <View style={styles.wrap} accessible accessibilityLabel={venueA11y(venue)} testID={testID}>
      <View style={styles.row}>
        <Text style={styles.text}>Se opera en</Text>
        <Image source={logo} style={styles.logo} />
        <Text style={styles.brand}>{name}</Text>
      </View>
      {!compact && <Text style={styles.note}>{note}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', marginTop: 12 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  text: { fontSize: 12, color: colors.text.light },
  logo: { width: 16, height: 16, borderRadius: 8 },
  brand: { fontSize: 12, fontWeight: '700', color: colors.text.secondary },
  note: { fontSize: 11, color: colors.text.light, marginTop: 3, textAlign: 'center' },
});
