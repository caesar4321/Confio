import React, { useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { useCurrency } from '../hooks/useCurrency';
import { useAuth } from '../contexts/AuthContext';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';

type CountryStat = {
  countryIso: string;
  countryName: string;
  verifiedCount: number;
};

const isoToFlag = (iso?: string | null) => {
  if (!iso || iso.length !== 2) return '🌎';
  const base = 0x1f1e6;
  const a = iso.toUpperCase().charCodeAt(0) - 65;
  const b = iso.toUpperCase().charCodeAt(1) - 65;
  if (a < 0 || a > 25 || b < 0 || b > 25) return '🌎';
  return String.fromCodePoint(base + a) + String.fromCodePoint(base + b);
};

export const LatamCommunityScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { userProfile } = useAuth();
  const { data, loading, error, refetch } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });

  const userCountryIso = (userProfile?.phoneCountry || '').toUpperCase();

  const formatWhole = (n: number) => {
    try {
      return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
        .format(Math.round(n))
        .replace(/,/g, currency.thousandsSeparator);
    } catch {
      return `${Math.round(n)}`;
    }
  };

  const { rows, maxCount, userInList } = useMemo(() => {
    const list: CountryStat[] = data?.statsSummary?.usersByCountry ?? [];
    const max = list.reduce((m, r) => Math.max(m, r.verifiedCount || 0), 0);
    const present = list.some((r) => r.countryIso?.toUpperCase() === userCountryIso);
    return { rows: list, maxCount: max, userInList: present };
  }, [data, userCountryIso]);

  const diditVerified = data?.statsSummary?.diditVerifiedUsers ?? 0;
  const formatVerifiedCount = (n: number) => {
    try {
      return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
        .format(Math.round(n))
        .replace(/,/g, currency.thousandsSeparator);
    } catch {
      return `${Math.round(n)}`;
    }
  };

  const renderItem = ({ item, index }: { item: CountryStat; index: number }) => {
    const isUser = userInList && item.countryIso?.toUpperCase() === userCountryIso;
    const widthPct = maxCount > 0 ? Math.max(8, (item.verifiedCount / maxCount) * 100) : 0;
    return (
      <View style={[styles.row, isUser && styles.rowHighlight]}>
        <View style={styles.rowHeader}>
          <Text style={styles.rank}>{index + 1}</Text>
          <Text style={styles.flag}>{isoToFlag(item.countryIso)}</Text>
          <View style={styles.countryBlock}>
            <Text style={styles.countryName} numberOfLines={1}>
              {item.countryName}
            </Text>
            {isUser ? <Text style={styles.userPin}>Tu país</Text> : null}
          </View>
          <Text style={styles.count}>{formatWhole(item.verifiedCount)}</Text>
        </View>
        <View style={styles.barTrack}>
          <View
            style={[
              styles.barFill,
              { width: `${widthPct}%` },
              isUser && styles.barFillUser,
            ]}
          />
        </View>
      </View>
    );
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Tu comunidad en Confío"
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />

      <View style={styles.intro}>
        <Text style={styles.introTitle}>Usuarios por país</Text>
        <Text style={styles.introSubtitle}>
          Confío crece en toda Latinoamérica. Aquí están las comunidades que ya forman parte.
        </Text>
        <View style={styles.verifiedPill}>
          <Icon name="check-circle" size={14} color={colors.primary} />
          <Text style={styles.verifiedPillText}>
            {formatVerifiedCount(diditVerified)} identidades verificadas con Didit
          </Text>
        </View>
      </View>

      {loading && rows.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : error && rows.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>No pudimos cargar tu comunidad.</Text>
          <TouchableOpacity onPress={() => refetch()} style={styles.retryButton}>
            <Text style={styles.retryText}>Reintentar</Text>
          </TouchableOpacity>
        </View>
      ) : rows.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyText}>Pronto verás tu comunidad aquí.</Text>
        </View>
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.countryIso}
          renderItem={renderItem}
          contentContainerStyle={styles.listContent}
          initialNumToRender={20}
          maxToRenderPerBatch={10}
          windowSize={21}
          showsVerticalScrollIndicator={false}
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  intro: {
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 12,
  },
  introTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
  },
  introSubtitle: {
    fontSize: 14,
    color: '#6B7280',
    marginTop: 4,
    lineHeight: 20,
  },
  verifiedPill: {
    alignSelf: 'flex-start',
    marginTop: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: '#E8F7F0',
  },
  verifiedPillText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  errorText: {
    color: '#6B7280',
    fontSize: 14,
    textAlign: 'center',
    marginBottom: 12,
  },
  retryButton: {
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 20,
    backgroundColor: colors.primary,
  },
  retryText: {
    color: '#fff',
    fontWeight: '600',
  },
  emptyText: {
    color: '#6B7280',
    fontSize: 14,
    textAlign: 'center',
  },
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 32,
  },
  row: {
    backgroundColor: colors.neutral,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
    marginBottom: 10,
  },
  rowHighlight: {
    backgroundColor: '#E8F7F0',
    borderWidth: 1,
    borderColor: colors.primary,
  },
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  rank: {
    width: 22,
    textAlign: 'center',
    fontSize: 12,
    fontWeight: '700',
    color: '#9CA3AF',
  },
  flag: {
    fontSize: 22,
  },
  countryBlock: {
    flex: 1,
    minWidth: 0,
  },
  countryName: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.dark,
  },
  userPin: {
    fontSize: 11,
    color: colors.primary,
    fontWeight: '700',
    marginTop: 2,
  },
  count: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.dark,
  },
  barTrack: {
    marginTop: 8,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#E5E7EB',
    overflow: 'hidden',
  },
  barFill: {
    height: 6,
    backgroundColor: colors.primary,
    borderRadius: 3,
  },
  barFillUser: {
    backgroundColor: colors.violet,
  },
});
