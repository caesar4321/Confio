import React, { useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors } from '../config/theme';
import { useCurrency } from '../hooks/useCurrency';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';

type StatsSummary = {
  totalUsers?: number | null;
  protectedSavings?: number | null;
  totalValueLocked?: number | null;
  presaleCusdRaised?: number | null;
};

const formatCompact = (n: number | null | undefined, sep: string): string => {
  if (n == null) return '—';
  const r = Math.round(n);
  if (r >= 1_000_000) {
    const v = r / 1_000_000;
    return `${v >= 10 ? v.toFixed(0) : v.toFixed(1)}M`;
  }
  if (r >= 10_000) {
    return `${Math.round(r / 1_000)}K`;
  }
  try {
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
      .format(r)
      .replace(/,/g, sep);
  } catch {
    return `${r}`;
  }
};

export const HomeStatsSection: React.FC = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { data } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'cache-and-network',
    nextFetchPolicy: 'cache-first',
  });
  const s: StatsSummary | undefined = data?.statsSummary;

  const tvl = s?.totalValueLocked ?? s?.protectedSavings;

  const usersValue = useMemo(
    () => formatCompact(s?.totalUsers, currency.thousandsSeparator),
    [s?.totalUsers, currency.thousandsSeparator]
  );
  const savingsValue = useMemo(
    () => formatCompact(tvl, currency.thousandsSeparator),
    [tvl, currency.thousandsSeparator]
  );
  const presaleValue = useMemo(
    () => formatCompact(s?.presaleCusdRaised, currency.thousandsSeparator),
    [s?.presaleCusdRaised, currency.thousandsSeparator]
  );

  return (
    <View style={styles.container}>
      <View style={styles.strip}>
        <TouchableOpacity
          style={styles.tile}
          activeOpacity={0.6}
          onPress={() => navigation.navigate('LatamCommunity')}
        >
          <Text
            style={styles.tileValue}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.7}
          >
            {usersValue}
          </Text>
          <Text style={styles.tileLabel}>Usuarios</Text>
        </TouchableOpacity>

        <View style={styles.divider} />

        <TouchableOpacity
          style={styles.tile}
          activeOpacity={0.6}
          onPress={() => navigation.navigate('AhorrosProtegidos')}
        >
          <Text
            style={styles.tileValue}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.7}
          >
            {`${savingsValue}`}
            <Text style={styles.tileUnit}> cUSD</Text>
          </Text>
          <Text style={styles.tileLabel}>Ahorros</Text>
        </TouchableOpacity>

        <View style={styles.divider} />

        <TouchableOpacity
          style={styles.tile}
          activeOpacity={0.6}
          onPress={() => navigation.navigate('ConfioPresale')}
        >
          <Text
            style={styles.tileValue}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.7}
          >
            {`${presaleValue}`}
            <Text style={styles.tileUnit}> cUSD</Text>
          </Text>
          <Text style={styles.tileLabel}>Preventa</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    marginTop: 4,
    marginBottom: 8,
  },
  strip: {
    flexDirection: 'row',
    alignItems: 'stretch',
    backgroundColor: colors.neutral,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 4,
  },
  tile: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  tileValue: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
    includeFontPadding: false,
  },
  tileUnit: {
    fontSize: 11,
    fontWeight: '600',
    color: '#6B7280',
  },
  tileLabel: {
    fontSize: 11,
    color: '#6B7280',
    marginTop: 4,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  divider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: '#E5E7EB',
    marginVertical: 4,
  },
});
