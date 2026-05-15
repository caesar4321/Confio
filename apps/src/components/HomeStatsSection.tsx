import React, { useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors } from '../config/theme';
import { useCurrency } from '../hooks/useCurrency';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';

type StatsSummary = {
  totalUsers?: number | null;
  diditVerifiedUsers?: number | null;
  protectedSavings?: number | null;
  totalValueLocked?: number | null;
  presaleCusdRaised?: number | null;
};

// Latino-friendly number formatting: full numbers up to 999,999 with the
// locale thousands separator (typically "." in LATAM Spanish). "M" only kicks
// in at one million+. No "K" — most readers don't parse it consistently.
const formatLocale = (n: number | null | undefined, sep: string): string => {
  if (n == null) return '—';
  const r = Math.round(n);
  if (r >= 1_000_000) {
    const v = r / 1_000_000;
    const decimal = v < 10 ? 1 : 0;
    return `${v.toFixed(decimal).replace('.', ',')} M`;
  }
  try {
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
      .format(r)
      .replace(/,/g, sep);
  } catch {
    return `${r}`;
  }
};

type Tile = {
  key: string;
  icon: string;
  value: string;
  unit?: string;
  label: string;
  descriptor: string;
  descriptorColor?: string;
  onPress: () => void;
};

export const HomeStatsSection: React.FC = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { data } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'cache-and-network',
    nextFetchPolicy: 'cache-first',
  });
  const s: StatsSummary | undefined = data?.statsSummary;
  const sep = currency.thousandsSeparator;
  const tvl = s?.totalValueLocked ?? s?.protectedSavings;
  const verified = s?.diditVerifiedUsers ?? 0;

  const tiles: Tile[] = useMemo(
    () => [
      {
        key: 'users',
        icon: 'users',
        value: formatLocale(s?.totalUsers, sep),
        label: 'Usuarios',
        descriptor: verified > 0 ? `✓ ${formatLocale(verified, sep)}` : 'Con teléfono',
        onPress: () => navigation.navigate('LatamCommunity'),
      },
      {
        key: 'savings',
        icon: 'shield',
        value: formatLocale(tvl, sep),
        unit: 'cUSD',
        label: 'Ahorros',
        descriptor: 'USDC',
        onPress: () => navigation.navigate('ProtectedSavings'),
      },
      {
        key: 'presale',
        icon: 'zap',
        value: formatLocale(s?.presaleCusdRaised, sep),
        unit: 'cUSD',
        label: 'Preventa',
        descriptor: '$CONFIO',
        descriptorColor: colors.violet,
        onPress: () => navigation.navigate('ConfioPresale'),
      },
    ],
    [s?.totalUsers, verified, tvl, s?.presaleCusdRaised, sep, navigation]
  );

  return (
    <View style={styles.container}>
      <View style={styles.strip}>
        {tiles.map((tile, idx) => (
          <React.Fragment key={tile.key}>
            {idx > 0 && <View style={styles.divider} />}
            <TouchableOpacity style={styles.tile} activeOpacity={0.7} onPress={tile.onPress}>
              <View style={styles.tileTopRow}>
                <Icon name={tile.icon} size={13} color={colors.primary} />
                <Icon name="chevron-right" size={14} color="#9CA3AF" />
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
              <Text style={styles.tileLabel}>{tile.label}</Text>
              <Text
                style={[
                  styles.tileDescriptor,
                  tile.descriptorColor ? { color: tile.descriptorColor } : null,
                ]}
                numberOfLines={1}
              >
                {tile.descriptor}
              </Text>
            </TouchableOpacity>
          </React.Fragment>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    marginTop: 4,
    marginBottom: 0,
  },
  strip: {
    flexDirection: 'row',
    alignItems: 'stretch',
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
  tile: {
    flex: 1,
    paddingHorizontal: 8,
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
