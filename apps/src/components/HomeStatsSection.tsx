import React, { useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Linking } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors } from '../config/theme';
import { useCurrency } from '../hooks/useCurrency';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';
import { CUSD_RESERVE_PERA_URL } from '../config/algorand';

type StatsSummary = {
  totalUsers?: number | null;
  protectedSavings?: number | null;
  totalValueLocked?: number | null;
  presaleCusdRaised?: number | null;
  cusdAssetPeraUrl?: string | null;
};

export const HomeStatsSection: React.FC = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { data } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'cache-and-network',
    nextFetchPolicy: 'cache-first',
  });
  const s: StatsSummary | undefined = data?.statsSummary;

  const formatWhole = useMemo(() => {
    const sep = currency.thousandsSeparator;
    return (n: number | null | undefined) => {
      if (n == null) return '—';
      const r = Math.round(n);
      try {
        return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
          .format(r)
          .replace(/,/g, sep);
      } catch {
        return `${r}`;
      }
    };
  }, [currency.thousandsSeparator]);

  const openUrl = (url?: string | null) => {
    if (!url) return;
    Linking.openURL(url).catch(() => {});
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Crecimiento Confío</Text>

      <TouchableOpacity
        style={styles.card}
        activeOpacity={0.7}
        onPress={() => navigation.navigate('LatamCommunity')}
      >
        <View style={styles.cardMain}>
          <View style={styles.cardText}>
            <Text style={styles.cardLabel}>Usuarios registrados</Text>
            <Text style={styles.cardSub}>Personas verificadas con teléfono.</Text>
          </View>
          <View style={styles.cardRight}>
            <Text style={styles.cardValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
              {formatWhole(s?.totalUsers)}
            </Text>
            <Icon name="chevron-right" size={18} color="#9CA3AF" />
          </View>
        </View>
      </TouchableOpacity>

      <View style={styles.card}>
        <View style={styles.cardMain}>
          <View style={styles.cardText}>
            <Text style={styles.cardLabel}>Ahorros Protegidos</Text>
            <Text style={styles.cardSub}>USDC de respaldo que protege los cUSD.</Text>
          </View>
          <View style={styles.cardRight}>
            <Text style={styles.cardValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
              {`${formatWhole(s?.totalValueLocked ?? s?.protectedSavings)} cUSD`}
            </Text>
          </View>
        </View>
        <View style={styles.linksRow}>
          <TouchableOpacity
            style={[styles.linkButton, !s?.cusdAssetPeraUrl && styles.linkButtonDisabled]}
            onPress={() => openUrl(s?.cusdAssetPeraUrl)}
            disabled={!s?.cusdAssetPeraUrl}
          >
            <Icon
              name="external-link"
              size={12}
              color={s?.cusdAssetPeraUrl ? colors.primary : '#9CA3AF'}
            />
            <Text
              style={[
                styles.linkText,
                !s?.cusdAssetPeraUrl && styles.linkTextDisabled,
              ]}
            >
              Ver cUSD
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.linkButton}
            onPress={() => openUrl(CUSD_RESERVE_PERA_URL)}
          >
            <Icon name="external-link" size={12} color={colors.primary} />
            <Text style={styles.linkText}>Ver respaldo</Text>
          </TouchableOpacity>
        </View>
      </View>

      <TouchableOpacity
        style={styles.card}
        activeOpacity={0.7}
        onPress={() => navigation.navigate('ConfioPresale')}
      >
        <View style={styles.cardMain}>
          <View style={styles.cardText}>
            <Text style={styles.cardLabel}>Preventa de $CONFIO</Text>
            <Text style={styles.cardSub}>cUSD aportados por la comunidad.</Text>
          </View>
          <View style={styles.cardRight}>
            <Text style={styles.cardValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>
              {`${formatWhole(s?.presaleCusdRaised)} cUSD`}
            </Text>
            <Icon name="chevron-right" size={18} color="#9CA3AF" />
          </View>
        </View>
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    marginTop: 8,
    marginBottom: 8,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 10,
  },
  card: {
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
  },
  cardMain: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  cardText: {
    flex: 1,
    minWidth: 0,
  },
  cardLabel: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.dark,
  },
  cardSub: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 3,
    lineHeight: 16,
  },
  cardRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexShrink: 0,
    maxWidth: '50%',
  },
  cardValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'right',
    includeFontPadding: false,
  },
  linksRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 10,
  },
  linkButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: '#E8F7F0',
  },
  linkButtonDisabled: {
    backgroundColor: '#F3F4F6',
  },
  linkText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  linkTextDisabled: {
    color: '#9CA3AF',
  },
});
