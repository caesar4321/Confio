import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Platform,
  Alert,
  ActivityIndicator,
  Modal,
  RefreshControl,
  FlatList,
  Animated,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery, useMutation } from '@apollo/client';
import {
  GET_USER_BANK_ACCOUNTS,
  DELETE_BANK_INFO,
  SET_DEFAULT_BANK_INFO,
} from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AddPayoutMethodModal } from '../components/AddPayoutMethodModal';
import Svg, { Defs, LinearGradient, Stop, Rect, Circle } from 'react-native-svg';
import { colors } from '../config/theme';

type PayoutMethodsNavigationProp = NativeStackNavigationProp<any>;

interface SavedPayoutMethod {
  id: string;
  account: {
    id: string;
    accountId: string;
    displayName: string;
    accountType: string;
  };
  paymentMethod?: {
    id: string;
    name: string;
    displayName: string;
    providerType: string;
    icon: string;
    requiresPhone: boolean;
    requiresEmail: boolean;
    requiresAccountNumber: boolean;
    bank?: {
      id: string;
      name: string;
      shortName?: string;
      country: {
        id: string;
        code: string;
        name: string;
        flagEmoji: string;
        requiresIdentification: boolean;
        identificationName: string;
      };
    };
    country?: {
      id: string;
      code: string;
      name: string;
      flagEmoji: string;
      requiresIdentification: boolean;
      identificationName: string;
    };
  };
  country?: {
    id: string;
    code: string;
    name: string;
    flagEmoji: string;
    requiresIdentification: boolean;
    identificationName: string;
  };
  bank?: {
    id: string;
    name: string;
    shortName?: string;
  };
  accountHolderName: string;
  accountNumber?: string;
  maskedAccountNumber?: string;
  accountType?: string;
  identificationNumber?: string;
  phoneNumber?: string;
  email?: string;
  username?: string;
  providerMetadata?: Record<string, string> | string;
  isDefault: boolean;
  isPublic: boolean;
  isVerified: boolean;
  summaryText: string;
  fullBankName: string;
  requiresIdentification: boolean;
  identificationLabel: string;
  createdAt: string;
}

// ─── Skeleton Card ───────────────────────────────────────────────────────────

const SkeletonCard = () => {
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(shimmer, { toValue: 0, duration: 900, useNativeDriver: true }),
      ])
    ).start();
  }, [shimmer]);

  const opacity = shimmer.interpolate({ inputRange: [0, 1], outputRange: [0.4, 0.85] });

  return (
    <Animated.View style={[styles.skeletonCard, { opacity }]}>
      <View style={styles.skeletonAccent} />
      <View style={{ flex: 1, paddingLeft: 12 }}>
        <View style={styles.skeletonRow}>
          <View style={styles.skeletonFlag} />
          <View style={styles.skeletonTitle} />
          <View style={styles.skeletonBadge} />
        </View>
        <View style={styles.skeletonLine} />
        <View style={[styles.skeletonLine, { width: '55%' }]} />
      </View>
    </Animated.View>
  );
};

// ─── Header SVG Background ───────────────────────────────────────────────────

const HeaderBackground = ({ height }: { height: number }) => (
  <Svg width="100%" height={height} style={StyleSheet.absoluteFill}>
    <Defs>
      <LinearGradient id="headerGrad" x1="0" y1="0" x2="1" y2="1">
        <Stop offset="0" stopColor="#34d399" stopOpacity="1" />
        <Stop offset="1" stopColor="#6ee7b7" stopOpacity="1" />
      </LinearGradient>
    </Defs>
    <Rect width="100%" height={height} fill="url(#headerGrad)" />
    {/* Decorative circles */}
    <Circle cx="90%" cy="20" r="80" fill="rgba(255,255,255,0.08)" />
    <Circle cx="15%" cy="90%" r="50" fill="rgba(255,255,255,0.06)" />
  </Svg>
);

// ─── Payout Method Card ───────────────────────────────────────────────────────

const PayoutMethodCard = ({
  payoutMethod,
  onEdit,
  onSetDefault,
  onDelete,
}: {
  payoutMethod: SavedPayoutMethod;
  onEdit: () => void;
  onSetDefault: () => void;
  onDelete: () => void;
}) => {
  const providerType = payoutMethod.paymentMethod?.providerType ?? 'DEFAULT';
  const accentColor =
    colors.providerColors[providerType as keyof typeof colors.providerColors] ??
    colors.providerColors.DEFAULT;

  const providerLabel: Record<string, string> = {
    BANK: 'Banco',
    DIGITAL_WALLET: 'Billetera Digital',
    MOBILE_PAYMENT: 'Pago Móvil',
  };
  const typeLabel = providerLabel[providerType] ?? 'Forma de cobro';

  let flagEmoji =
    payoutMethod.paymentMethod?.bank?.country?.flagEmoji ||
    payoutMethod.paymentMethod?.country?.flagEmoji ||
    payoutMethod.country?.flagEmoji;

  if (!flagEmoji) {
    if (providerType === 'DIGITAL_WALLET') flagEmoji = '💳';
    else if (providerType === 'MOBILE_PAYMENT') flagEmoji = '📱';
    else flagEmoji = '🏦';
  }

  const displayName =
    payoutMethod.fullBankName ||
    payoutMethod.paymentMethod?.displayName ||
    payoutMethod.bank?.name ||
    'Forma de cobro';

  const countryName =
    payoutMethod.paymentMethod?.bank?.country?.name ||
    payoutMethod.paymentMethod?.country?.name ||
    payoutMethod.country?.name ||
    '';

  return (
    <View style={[styles.card, payoutMethod.isDefault && styles.cardDefault]}>
      {/* Left accent bar */}
      <View style={[styles.cardAccent, { backgroundColor: accentColor }]} />

      <View style={styles.cardInner}>
        {/* Row 1: flag + name + verified + actions */}
        <View style={styles.cardRow}>
          <Text style={styles.cardFlag}>{flagEmoji}</Text>
          <Text style={styles.cardBankName} numberOfLines={1} ellipsizeMode="tail">
            {displayName}
          </Text>
          {payoutMethod.isVerified && (
            <Icon name="check-circle" size={13} color={colors.success} style={styles.verifiedIcon} />
          )}
          <View style={styles.cardActions}>
            <TouchableOpacity onPress={onEdit} style={styles.actionBtn}>
              <Icon name="edit-2" size={14} color={colors.accent} />
            </TouchableOpacity>
            {!payoutMethod.isDefault && (
              <TouchableOpacity onPress={onSetDefault} style={styles.actionBtn}>
                <Icon name="star" size={14} color={colors.warning} />
              </TouchableOpacity>
            )}
            <TouchableOpacity onPress={onDelete} style={styles.actionBtn}>
              <Icon name="trash-2" size={14} color={colors.error} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Row 2: type pill + country + default badge */}
        <View style={styles.cardRow2}>
          <View style={[styles.typePill, { backgroundColor: accentColor + '18' }]}>
            <Text style={[styles.typePillText, { color: accentColor }]}>{typeLabel}</Text>
          </View>
          {countryName ? (
            <Text style={styles.countryName} numberOfLines={1}>{countryName}</Text>
          ) : null}
          {payoutMethod.isDefault && (
            <View style={styles.defaultBadge}>
              <Text style={styles.defaultText}>Predeterminada</Text>
            </View>
          )}
        </View>

        {/* Row 3: holder · summary */}
        <Text style={styles.cardDetail} numberOfLines={1} ellipsizeMode="middle">
          {payoutMethod.accountHolderName}
          {payoutMethod.summaryText ? `  ·  ${payoutMethod.summaryText}` : ''}
        </Text>

        {payoutMethod.identificationNumber ? (
          <Text style={styles.identificationText} numberOfLines={1}>
            {payoutMethod.identificationLabel}: {payoutMethod.identificationNumber}
          </Text>
        ) : null}
      </View>
    </View>
  );
};

// ─── Main Screen ──────────────────────────────────────────────────────────────

export const PayoutMethodsScreen = () => {
  const navigation = useNavigation<PayoutMethodsNavigationProp>();
  const { activeAccount } = useAccount();

  const [showAddModal, setShowAddModal] = useState(false);
  const [editingPayoutMethod, setEditingPayoutMethod] = useState<SavedPayoutMethod | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const isEmployee = activeAccount?.isEmployee || false;
  const canManageBankAccounts =
    !isEmployee || Boolean((activeAccount as any)?.employeePermissions?.manageBankAccounts);

  const {
    data: bankAccountsData,
    loading: bankAccountsLoading,
    error: bankAccountsError,
    refetch: refetchBankAccounts,
  } = useQuery(GET_USER_BANK_ACCOUNTS, { fetchPolicy: 'cache-and-network' });

  const payoutMethods: SavedPayoutMethod[] = bankAccountsData?.userBankAccounts || [];

  const [setDefaultBankInfo] = useMutation(SET_DEFAULT_BANK_INFO);
  const [deleteBankInfo] = useMutation(DELETE_BANK_INFO);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refetchBankAccounts();
    } catch (e) {
      console.error('Error refreshing bank accounts:', e);
    } finally {
      setRefreshing(false);
    }
  };

  useFocusEffect(
    React.useCallback(() => {
      refetchBankAccounts();
    }, [refetchBankAccounts])
  );

  const handleSetDefault = async (bankInfoId: string) => {
    try {
      const { data } = await setDefaultBankInfo({ variables: { bankInfoId } });
      if (data?.setDefaultBankInfo?.success) {
        Alert.alert('Éxito', 'Cuenta bancaria marcada como predeterminada');
        refetchBankAccounts();
      } else {
        Alert.alert('Error', data?.setDefaultBankInfo?.error || 'Error al marcar como predeterminada', [{ text: 'Entendido' }]);
      }
    } catch {
      Alert.alert('Error', 'Error de conexión', [{ text: 'Entendido' }]);
    }
  };

  const handleDelete = async (bankInfoId: string, bankName: string) => {
    Alert.alert(
      'Eliminar Cuenta Bancaria',
      `¿Estás seguro de que quieres eliminar la cuenta de ${bankName}?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: async () => {
            try {
              const { data } = await deleteBankInfo({ variables: { bankInfoId } });
              if (data?.deleteBankInfo?.success) {
                Alert.alert('Éxito', 'Cuenta bancaria eliminada', [{ text: 'Entendido' }]);
                refetchBankAccounts();
              } else {
                Alert.alert('Error', data?.deleteBankInfo?.error || 'Error al eliminar', [{ text: 'Entendido' }]);
              }
            } catch {
              Alert.alert('Error', 'Error de conexión', [{ text: 'Entendido' }]);
            }
          },
        },
      ]
    );
  };

  // ── Permission denied ──
  if (!canManageBankAccounts) {
    return (
      <SafeAreaView edges={['top']} style={styles.container}>
        <View style={styles.headerWrap}>
          <HeaderBackground height={120} />
          <View style={[styles.headerContent, { paddingTop: 8 }]}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
              <Icon name="arrow-left" size={22} color="white" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Formas de cobro</Text>
            <View style={{ width: 40 }} />
          </View>
        </View>
        <View style={styles.permissionDeniedContainer}>
          <View style={styles.lockIconWrap}>
            <Icon name="lock" size={32} color={colors.text.light} />
          </View>
          <Text style={styles.permissionDeniedTitle}>Información del Negocio</Text>
          <Text style={styles.permissionDeniedText}>
            Las formas de cobro de {activeAccount?.business?.name || 'la empresa'} son gestionadas
            por el equipo administrativo.
          </Text>
          <Text style={styles.permissionDeniedSubtext}>
            Si necesitas información sobre pagos, consulta con tu supervisor.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  // ── Main render ──
  const HEADER_HEIGHT = 110;

  const renderContent = () => {
    if (bankAccountsLoading && !refreshing) {
      return (
        <View style={styles.skeletonContainer}>
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </View>
      );
    }

    if (bankAccountsError) {
      return (
        <View style={styles.errorContainer}>
          <Icon name="wifi-off" size={48} color={colors.error} />
          <Text style={styles.errorText}>No se pudieron cargar las formas de cobro</Text>
          <TouchableOpacity style={styles.retryButton} onPress={onRefresh}>
            <Icon name="refresh-cw" size={16} color="white" />
            <Text style={styles.retryText}>Reintentar</Text>
          </TouchableOpacity>
        </View>
      );
    }

    if (payoutMethods.length === 0) {
      return (
        <View style={styles.emptyState}>
          <Svg width={120} height={100} viewBox="0 0 120 100">
            <Defs>
              <LinearGradient id="emptyGrad" x1="0" y1="0" x2="1" y2="1">
                <Stop offset="0" stopColor="#34d399" stopOpacity="0.25" />
                <Stop offset="1" stopColor="#6ee7b7" stopOpacity="0.1" />
              </LinearGradient>
            </Defs>
            <Rect x="10" y="20" width="100" height="65" rx="12" fill="url(#emptyGrad)" stroke="#34d399" strokeWidth="2" strokeOpacity="0.4" />
            <Rect x="20" y="38" width="40" height="6" rx="3" fill="#34d399" fillOpacity="0.5" />
            <Rect x="20" y="50" width="60" height="4" rx="2" fill="#34d399" fillOpacity="0.3" />
            <Rect x="20" y="60" width="45" height="4" rx="2" fill="#34d399" fillOpacity="0.2" />
            <Circle cx="88" cy="42" r="10" fill="#34d399" fillOpacity="0.15" stroke="#34d399" strokeWidth="1.5" strokeOpacity="0.5" />
            <Rect x="83" y="41" width="10" height="2" rx="1" fill="#34d399" fillOpacity="0.6" />
            <Rect x="87" y="37" width="2" height="10" rx="1" fill="#34d399" fillOpacity="0.6" />
          </Svg>
          <Text style={styles.emptyTitle}>Sin formas de cobro</Text>
          <Text style={styles.emptyDescription}>
            Agrega tu cuenta bancaria o billetera para recibir retiros y cobros en la app.
          </Text>
          <TouchableOpacity style={styles.addButton} onPress={handleAddNew}>
            <Icon name="plus" size={18} color="white" />
            <Text style={styles.addButtonText}>Agregar forma de cobro</Text>
          </TouchableOpacity>
        </View>
      );
    }

    return (
      <FlatList
        data={payoutMethods}
        keyExtractor={(item) => item.id}
        style={{ flex: 1 }}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            colors={[colors.primary]}
            tintColor={colors.primary}
          />
        }
        renderItem={({ item }) => (
          <PayoutMethodCard
            payoutMethod={item}
            onEdit={() => handleEdit(item)}
            onSetDefault={() => handleSetDefault(item.id)}
            onDelete={() => {
              const name =
                item.fullBankName ||
                item.paymentMethod?.displayName ||
                item.bank?.name ||
                'esta cuenta';
              handleDelete(item.id, name);
            }}
          />
        )}
        ListFooterComponent={
          <TouchableOpacity style={styles.addMoreButton} onPress={handleAddNew}>
            <Icon name="plus-circle" size={18} color={colors.primary} />
            <Text style={styles.addMoreText}>Agregar otra forma de cobro</Text>
          </TouchableOpacity>
        }
        initialNumToRender={10}
        maxToRenderPerBatch={10}
        windowSize={21}
        removeClippedSubviews={true}
      />
    );
  };

  const handleEdit = (payoutMethod: SavedPayoutMethod) => {
    setEditingPayoutMethod(payoutMethod);
    setShowAddModal(true);
  };

  const handleAddNew = () => {
    setEditingPayoutMethod(null);
    setShowAddModal(true);
  };

  return (
    <SafeAreaView edges={['top']} style={styles.container}>
      {/* Header with gradient background + curved bottom */}
      <View style={[styles.headerWrap, { height: HEADER_HEIGHT }]}>
        <HeaderBackground height={HEADER_HEIGHT} />
        <View style={[styles.headerContent, { paddingTop: 8 }]}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={22} color="white" />
          </TouchableOpacity>
          <View style={{ alignItems: 'center' }}>
            <Text style={styles.headerTitle}>Formas de cobro</Text>
            {!bankAccountsLoading && payoutMethods.length > 0 && (
              <View style={styles.countBadge}>
                <Text style={styles.countBadgeText}>
                  {payoutMethods.length} {payoutMethods.length === 1 ? 'método' : 'métodos'}
                </Text>
              </View>
            )}
          </View>
          <TouchableOpacity onPress={handleAddNew} style={styles.addHeaderButton}>
            <Icon name="plus" size={22} color="white" />
          </TouchableOpacity>
        </View>
      </View>

      {/* Content overlaps header by 16px for the "card peeking" effect */}
      <View style={styles.contentContainer}>
        {renderContent()}
      </View>

      <Modal visible={showAddModal} animationType="slide" presentationStyle="pageSheet">
        <AddPayoutMethodModal
          isVisible={showAddModal}
          onClose={() => {
            setShowAddModal(false);
            setEditingPayoutMethod(null);
          }}
          onSuccess={() => {
            setShowAddModal(false);
            setEditingPayoutMethod(null);
            refetchBankAccounts();
          }}
          accountId={activeAccount?.id || null}
          editingPayoutMethod={editingPayoutMethod as any}
        />
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },

  // ── Header ──
  headerWrap: {
    overflow: 'hidden',
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingBottom: 20,
    flex: 1,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  addHeaderButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 19,
    fontWeight: 'bold',
    color: 'white',
  },
  countBadge: {
    marginTop: 3,
    backgroundColor: 'rgba(255,255,255,0.25)',
    paddingHorizontal: 10,
    paddingVertical: 2,
    borderRadius: 10,
  },
  countBadgeText: {
    fontSize: 11,
    color: 'white',
    fontWeight: '600',
  },

  // ── Content ──
  contentContainer: {
    flex: 1,
    marginTop: -4, // slight overlap for seamless curve-to-content transition
  },
  listContent: {
    paddingTop: 16,
    paddingHorizontal: 16,
    paddingBottom: 32,
  },

  // ── Payment method card ──
  card: {
    flexDirection: 'row',
    backgroundColor: colors.background,
    borderRadius: 14,
    marginBottom: 10,
    overflow: 'hidden',
    ...Platform.select({
      ios: {
        shadowColor: '#064e3b',
        shadowOffset: { width: 0, height: 3 },
        shadowOpacity: 0.07,
        shadowRadius: 8,
      },
      android: { elevation: 3 },
    }),
  },
  cardDefault: {
    borderWidth: 1.5,
    borderColor: colors.primaryDark,
  },
  cardAccent: {
    width: 4,
  },
  cardInner: {
    flex: 1,
    paddingVertical: 14,
    paddingHorizontal: 12,
  },
  // Row 1: flag | name (flex:1, shrinks) | verified | actions (fixed)
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  cardFlag: {
    fontSize: 18,
    marginRight: 6,
    flexShrink: 0,
  },
  cardBankName: {
    flex: 1,
    fontSize: 14,
    fontWeight: '700',
    color: colors.text.primary,
  },
  verifiedIcon: {
    marginLeft: 4,
    flexShrink: 0,
  },
  cardActions: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 8,
    flexShrink: 0,
  },
  actionBtn: {
    paddingHorizontal: 6,
    paddingVertical: 4,
  },
  // Row 2: pill | country | default badge — all auto-width, no flex stretch
  cardRow2: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 7,
  },
  typePill: {
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 5,
    marginRight: 5,
  },
  typePillText: {
    fontSize: 10,
    fontWeight: '700',
  },
  countryName: {
    fontSize: 11,
    color: colors.text.light,
    marginRight: 5,
    flexShrink: 1,
  },
  defaultBadge: {
    backgroundColor: colors.primaryLight,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 5,
  },
  defaultText: {
    fontSize: 10,
    color: colors.primaryDeep,
    fontWeight: '700',
  },
  // Row 3
  cardDetail: {
    fontSize: 12,
    color: colors.text.secondary,
  },
  identificationText: {
    fontSize: 11,
    color: colors.text.light,
    marginTop: 2,
  },

  // ── Skeleton ──
  skeletonContainer: {
    paddingTop: 16,
    paddingHorizontal: 16,
  },
  skeletonCard: {
    flexDirection: 'row',
    backgroundColor: colors.background,
    borderRadius: 16,
    marginBottom: 12,
    overflow: 'hidden',
    height: 90,
    ...Platform.select({
      ios: { shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.06, shadowRadius: 6 },
      android: { elevation: 2 },
    }),
  },
  skeletonAccent: {
    width: 5,
    backgroundColor: colors.neutralDark,
  },
  skeletonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 10,
    gap: 8,
  },
  skeletonFlag: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.neutralDark,
  },
  skeletonTitle: {
    flex: 1,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.neutralDark,
  },
  skeletonBadge: {
    width: 60,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.neutralDark,
  },
  skeletonLine: {
    width: '75%',
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.neutralDark,
    marginBottom: 6,
  },

  // ── Empty state ──
  emptyState: {
    alignItems: 'center',
    paddingVertical: 60,
    paddingHorizontal: 32,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginTop: 20,
    marginBottom: 8,
  },
  emptyDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 28,
  },
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 24,
    paddingVertical: 13,
    borderRadius: 12,
    gap: 8,
  },
  addButtonText: {
    color: 'white',
    fontWeight: '700',
    fontSize: 15,
  },

  // ── Add more ──
  addMoreButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
    paddingVertical: 16,
    borderRadius: 14,
    borderWidth: 2,
    borderColor: colors.primaryLight,
    borderStyle: 'dashed',
    gap: 8,
    marginTop: 4,
  },
  addMoreText: {
    color: colors.primary,
    fontWeight: '700',
    fontSize: 14,
  },

  // ── Error ──
  errorContainer: {
    alignItems: 'center',
    paddingVertical: 60,
    paddingHorizontal: 32,
  },
  errorText: {
    marginTop: 12,
    marginBottom: 20,
    color: colors.text.secondary,
    textAlign: 'center',
    fontSize: 15,
  },
  retryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 10,
    gap: 8,
  },
  retryText: {
    color: 'white',
    fontWeight: '700',
  },

  // ── Permission denied ──
  permissionDeniedContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  lockIconWrap: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  permissionDeniedTitle: {
    fontSize: 22,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginTop: 16,
    marginBottom: 12,
  },
  permissionDeniedText: {
    fontSize: 15,
    color: colors.text.secondary,
    textAlign: 'center',
    marginBottom: 8,
    lineHeight: 22,
  },
  permissionDeniedSubtext: {
    fontSize: 13,
    color: colors.text.light,
    textAlign: 'center',
    lineHeight: 20,
  },
});
