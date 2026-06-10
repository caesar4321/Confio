import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  FlatList,
  StatusBar,
  Alert,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery, useMutation } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { useNumberFormat } from '../utils/numberFormatting';
import { Financiera } from '../types/financiera';
import {
  GET_MY_FINANCIERAS,
  GET_FINANCIERAS,
  SET_FINANCIERA_ACTIVE,
  DELETE_FINANCIERA,
} from '../apollo/queries';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

const STAR_GOLD = '#F59E0B';

const refetchAfterChange = [
  { query: GET_MY_FINANCIERAS },
  { query: GET_FINANCIERAS, variables: { sortBy: 'rating', limit: 100, offset: 0 } },
];

const MyFinancieraCard = ({
  financiera,
  onEdit,
  onToggleActive,
  onDelete,
  onOpen,
}: {
  financiera: Financiera;
  onEdit: () => void;
  onToggleActive: () => void;
  onDelete: () => void;
  onOpen: () => void;
}) => {
  const { formatNumber } = useNumberFormat();
  const active = financiera.isActive !== false;

  return (
    <View style={styles.card}>
      <TouchableOpacity style={styles.cardTop} activeOpacity={0.85} onPress={onOpen}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <View style={styles.titleRow}>
            <Text style={styles.cardName} numberOfLines={1}>
              {financiera.name}
            </Text>
            <View style={[styles.statusBadge, active ? styles.statusActive : styles.statusPaused]}>
              <Text style={[styles.statusText, { color: active ? colors.primaryDark : colors.warning.text }]}>
                {active ? 'Activa' : 'Pausada'}
              </Text>
            </View>
          </View>
          <Text style={styles.locationText} numberOfLines={1}>
            {financiera.neighborhood ? `${financiera.neighborhood}, ` : ''}
            {financiera.city}, {financiera.state}
          </Text>
          <View style={styles.statsRow}>
            <Icon name="star" size={13} color={STAR_GOLD} />
            <Text style={styles.statText}>
              {financiera.avgRating != null
                ? formatNumber(financiera.avgRating, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
                : '—'}
            </Text>
            <Text style={styles.statDim}>· {financiera.reviewCount} reseñas</Text>
            <Text style={styles.statDim}>
              · 100 USDC →{' '}
              {financiera.avgReceivedPer100 != null
                ? `$${formatNumber(financiera.avgReceivedPer100, { maximumFractionDigits: 1 })}`
                : '—'}
            </Text>
          </View>
        </View>
        <Icon name="chevron-right" size={20} color={colors.text.light} />
      </TouchableOpacity>

      <View style={styles.actionsRow}>
        <TouchableOpacity style={styles.actionBtn} onPress={onEdit}>
          <Icon name="edit-2" size={14} color={colors.text.primary} />
          <Text style={styles.actionText}>Editar</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionBtn} onPress={onToggleActive}>
          <Icon name={active ? 'pause' : 'play'} size={14} color={colors.text.primary} />
          <Text style={styles.actionText}>{active ? 'Pausar' : 'Activar'}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.actionBtn} onPress={onDelete}>
          <Icon name="trash-2" size={14} color={colors.danger} />
          <Text style={[styles.actionText, { color: colors.danger }]}>Eliminar</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
};

export const MyFinancierasScreen = () => {
  const navigation = useNavigation<NavProp>();

  const { data, loading, refetch, networkStatus } = useQuery(GET_MY_FINANCIERAS, {
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });
  const financieras: Financiera[] = data?.myFinancieras || [];
  const refreshing = networkStatus === 4;

  const [setActiveMutation] = useMutation(SET_FINANCIERA_ACTIVE, {
    refetchQueries: refetchAfterChange,
  });
  const [deleteMutation] = useMutation(DELETE_FINANCIERA, {
    refetchQueries: refetchAfterChange,
  });

  const toggleActive = (f: Financiera) => {
    const next = f.isActive === false;
    setActiveMutation({ variables: { financieraId: f.id, isActive: next } })
      .then((res) => {
        const payload = res.data?.setFinancieraActive;
        if (!payload?.success) {
          Alert.alert('Error', payload?.error || 'No se pudo actualizar.');
        }
      })
      .catch(() => Alert.alert('Error', 'No se pudo actualizar. Revisa tu conexión.'));
  };

  const confirmDelete = (f: Financiera) => {
    Alert.alert(
      'Eliminar financiera',
      `"${f.name}" dejará de aparecer en el directorio y perderá sus ${f.reviewCount} reseñas. Esta acción no se puede deshacer.`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: async () => {
            try {
              const res = await deleteMutation({ variables: { financieraId: f.id } });
              if (!res.data?.deleteFinanciera?.success) {
                Alert.alert('Error', res.data?.deleteFinanciera?.error || 'No se pudo eliminar.');
              }
            } catch {
              Alert.alert('Error', 'No se pudo eliminar. Revisa tu conexión.');
            }
          },
        },
      ],
    );
  };

  const editFinanciera = (f: Financiera) => {
    navigation.navigate('RegisterFinanciera', {
      edit: {
        financieraId: f.id,
        name: f.name,
        countryCode: f.countryCode,
        state: f.state,
        city: f.city,
        neighborhood: f.neighborhood,
        whatsapp: f.whatsapp,
        helpsWithConfio: f.helpsWithConfio,
        homeService: f.homeService,
        openWeekends: f.openWeekends,
      },
    });
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
              <Icon name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Mis financieras</Text>
            <TouchableOpacity
              onPress={() => navigation.navigate('RegisterFinanciera')}
              style={styles.headerIconBtn}
            >
              <Icon name="plus" size={24} color="#fff" />
            </TouchableOpacity>
          </View>
        </View>
      </SafeAreaView>

      <FlatList
        data={financieras}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => refetch()}
            tintColor={colors.primary}
          />
        }
        renderItem={({ item }) => (
          <MyFinancieraCard
            financiera={item}
            onOpen={() => navigation.navigate('FinancieraDetail', { financieraId: item.id })}
            onEdit={() => editFinanciera(item)}
            onToggleActive={() => toggleActive(item)}
            onDelete={() => confirmDelete(item)}
          />
        )}
        ListHeaderComponent={
          financieras.length > 0 ? (
            <Text style={styles.hint}>
              Pausa tu financiera cuando no puedas atender; tus reseñas se conservan.
            </Text>
          ) : null
        }
        ListEmptyComponent={
          loading ? (
            <View style={styles.empty}>
              <ActivityIndicator color={colors.primary} size="large" />
            </View>
          ) : (
            <View style={styles.empty}>
              <Icon name="briefcase" size={40} color={colors.text.light} />
              <Text style={styles.emptyTitle}>Aún no tienes financieras</Text>
              <Text style={styles.emptyText}>
                Registra tu financiera gratis en el directorio y recibe clientes de tu zona.
              </Text>
              <TouchableOpacity
                style={styles.emptyBtn}
                onPress={() => navigation.navigate('RegisterFinanciera')}
              >
                <Text style={styles.emptyBtnText}>Registrar financiera</Text>
              </TouchableOpacity>
            </View>
          )
        }
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  header: { backgroundColor: colors.primary, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 16 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },

  listContent: { padding: 16, paddingBottom: 40 },
  hint: { fontSize: 12, color: colors.text.secondary, marginBottom: 4, lineHeight: 17 },

  card: {
    backgroundColor: '#fff',
    borderRadius: 14,
    marginTop: 12,
    borderWidth: 1,
    borderColor: colors.borderLight,
  },
  cardTop: { flexDirection: 'row', alignItems: 'center', padding: 14 },
  titleRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  cardName: { fontSize: 15, fontWeight: '700', color: colors.text.primary, flexShrink: 1 },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6 },
  statusActive: { backgroundColor: colors.primaryLight },
  statusPaused: { backgroundColor: colors.warning.background },
  statusText: { fontSize: 10, fontWeight: '700' },
  locationText: { fontSize: 12, color: colors.text.secondary, marginTop: 4 },
  statsRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 6 },
  statText: { fontSize: 12, fontWeight: '700', color: colors.text.primary },
  statDim: { fontSize: 12, color: colors.text.secondary },

  actionsRow: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: colors.borderLight,
  },
  actionBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 12,
  },
  actionText: { fontSize: 13, fontWeight: '600', color: colors.text.primary },

  empty: { alignItems: 'center', paddingVertical: 60, paddingHorizontal: 24 },
  emptyTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary, marginTop: 12 },
  emptyText: { fontSize: 13, color: colors.text.secondary, textAlign: 'center', marginTop: 6, lineHeight: 19 },
  emptyBtn: {
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingHorizontal: 24,
    height: 46,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 20,
  },
  emptyBtnText: { fontSize: 14, fontWeight: '700', color: '#fff' },
});

export default MyFinancierasScreen;
