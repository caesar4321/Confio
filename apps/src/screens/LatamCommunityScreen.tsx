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
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { EmptyState } from '../components/EmptyState';

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

      {/* Brand field — the verified count IS the community's headline stat.
          Self-measuring backdrop: the number arrives async. */}
      <View style={styles.field}>
        <BrandFieldBackground id="communityField" ringCy="25%" ringR={80} ringWidth={20} />
        <View style={styles.fieldInner}>
          <Text style={styles.fieldEyebrow}>IDENTIDADES VERIFICADAS</Text>
          <View style={styles.fieldStatRow}>
            <Icon name="check-circle" size={20} color={colors.primaryLight} />
            <Text style={styles.fieldStat}>{formatVerifiedCount(diditVerified)}</Text>
          </View>
          <Text style={styles.fieldSubtitle}>
            Personas reales verificadas con Didit. Confío crece en toda Latinoamérica.
          </Text>
        </View>
      </View>

      <Text style={styles.sectionLabel}>Usuarios por país</Text>

      {loading && rows.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : error && rows.length === 0 ? (
        <EmptyState
          icon="wifi-off"
          title="No pudimos cargar tu comunidad"
          subtitle="Revisa tu conexión e inténtalo de nuevo."
          actionLabel="Reintentar"
          onAction={() => refetch()}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon="globe"
          title="Pronto verás tu comunidad aquí"
          subtitle="Las comunidades por país aparecerán a medida que crezcan."
        />
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
    backgroundColor: colors.white,
  },
  field: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
  },
  fieldInner: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 22,
  },
  fieldEyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2,
    color: colors.primaryLight,
    marginBottom: 6,
  },
  fieldStatRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  fieldStat: {
    fontSize: 30,
    fontWeight: '800',
    color: colors.white,
  },
  fieldSubtitle: {
    fontSize: 13,
    lineHeight: 19,
    color: 'rgba(255,255,255,0.85)',
    marginTop: 8,
  },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 8,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
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
    backgroundColor: colors.primarySoft,
    borderWidth: 1,
    borderColor: colors.primaryLight,
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
    color: colors.text.light,
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
    backgroundColor: colors.border,
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
