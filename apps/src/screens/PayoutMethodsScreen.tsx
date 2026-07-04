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
import MCIcon from 'react-native-vector-icons/MaterialCommunityIcons';
import { AddPayoutMethodModal } from '../components/AddPayoutMethodModal';
import Svg, { Defs, LinearGradient, Stop, Rect, Circle } from 'react-native-svg';
import { colors } from '../config/theme';
import { InlineBanner } from '../components/common/InlineBanner';
import { EmptyState } from '../components/EmptyState';
import { Header } from '../navigation/Header';

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
  const shimmerLoopRef = useRef<Animated.CompositeAnimation | null>(null);

  useEffect(() => {
    shimmerLoopRef.current = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(shimmer, { toValue: 0, duration: 900, useNativeDriver: true }),
      ])
    );
    shimmerLoopRef.current.start();
    return () => {
      shimmerLoopRef.current?.stop();
      shimmer.stopAnimation();
    };
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
  // Provider accents from theme tokens. (colors.providerColors only holds
  // ramp-provider brands, so the old lookup always came back undefined and
  // the previous accent bars never actually rendered a color.)
  const providerAccents: Record<string, string> = {
    BANK: colors.accent,
    DIGITAL_WALLET: colors.secondary,
    MOBILE_PAYMENT: colors.primaryDark,
  };
  const accentColor = providerAccents[providerType] ?? colors.primaryDark;

  const providerLabel: Record<string, string> = {
    BANK: 'Banco',
    DIGITAL_WALLET: 'Billetera Digital',
    MOBILE_PAYMENT: 'Pago Móvil',
  };
  const typeLabel = providerLabel[providerType] ?? 'Forma de cobro';

  const flagEmoji =
    payoutMethod.paymentMethod?.bank?.country?.flagEmoji ||
    payoutMethod.paymentMethod?.country?.flagEmoji ||
    payoutMethod.country?.flagEmoji;

  const providerIcon: Record<string, string> = {
    BANK: 'bank',
    DIGITAL_WALLET: 'wallet',
    MOBILE_PAYMENT: 'cellphone',
  };

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
      {/* Provider identity as an icon chip (app grammar) — no accent rails */}
      <View style={[styles.cardIconChip, { backgroundColor: accentColor + '18' }]}>
        <MCIcon name={providerIcon[providerType] || 'bank'} size={20} color={accentColor} />
      </View>

      <View style={styles.cardInner}>
        {/* Row 1: flag + name + verified + actions */}
        <View style={styles.cardRow}>
          {flagEmoji ? <Text style={styles.cardFlag}>{flagEmoji}</Text> : null}
          <Text style={styles.cardBankName} numberOfLines={1} ellipsizeMode="tail">
            {displayName}
          </Text>
          {payoutMethod.isVerified && (
            <Icon name="check-circle" size={13} color={colors.success} style={styles.verifiedIcon} />
          )}
          <View style={styles.cardActions}>
            <TouchableOpacity onPress={onEdit} style={styles.actionBtn} accessibilityRole="button" accessibilityLabel="Editar forma de cobro">
              <Icon name="edit-2" size={14} color={colors.accent} />
            </TouchableOpacity>
            {!payoutMethod.isDefault && (
              <TouchableOpacity onPress={onSetDefault} style={styles.actionBtn} accessibilityRole="button" accessibilityLabel="Marcar como predeterminada">
                <Icon name="star" size={14} color={colors.warning.icon} />
              </TouchableOpacity>
            )}
            <TouchableOpacity onPress={onDelete} style={styles.actionBtn} accessibilityRole="button" accessibilityLabel="Eliminar forma de cobro">
              <Icon name="trash-2" size={14} color={colors.error.icon} />
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
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);
  const dismissBanner = React.useCallback(() => setBanner(null), []);
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
        setBanner({ variant: 'success', message: 'Cuenta bancaria marcada como predeterminada' });
        refetchBankAccounts();
      } else {
        setBanner({ variant: 'error', message: data?.setDefaultBankInfo?.error || 'No se pudo marcar como predeterminada' });
      }
    } catch {
      setBanner({ variant: 'error', message: 'Error de conexión. Intenta de nuevo.' });
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
                setBanner({ variant: 'success', message: 'Cuenta bancaria eliminada' });
                refetchBankAccounts();
              } else {
                setBanner({ variant: 'error', message: data?.deleteBankInfo?.error || 'No se pudo eliminar la cuenta' });
              }
            } catch {
              setBanner({ variant: 'error', message: 'Error de conexión. Intenta de nuevo.' });
            }
          },
        },
      ]
    );
  };

  // ── Permission denied ──
  if (!canManageBankAccounts) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation as any}
          title="Formas de cobro"
          backgroundColor={colors.primary}
          isLight
          showBackButton
        />
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
      </View>
    );
  }

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
        <EmptyState
          icon="wifi-off"
          title="No se pudieron cargar las formas de cobro"
          subtitle="Revisa tu conexión e intenta de nuevo."
          actionLabel="Reintentar"
          onAction={onRefresh}
        />
      );
    }

    if (payoutMethods.length === 0) {
      return (
        <EmptyState
          icon="credit-card"
          title="Sin formas de cobro"
          subtitle="Agrega tu cuenta bancaria o billetera para recibir retiros y cobros en la app."
          actionLabel="Agregar forma de cobro"
          onAction={handleAddNew}
        />
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
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Formas de cobro"
        backgroundColor={colors.primary}
        isLight
        showBackButton
        rightAccessory={(
          <TouchableOpacity onPress={handleAddNew} style={styles.addHeaderButton} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} accessibilityRole="button" accessibilityLabel="Agregar forma de cobro">
            <Icon name="plus" size={20} color={colors.white} />
          </TouchableOpacity>
        )}
      />

      {/* Emerald brand field: lead with where the money lands. Padding on
          fieldInner (Yoga absolute-child rule); vertical gradient meets the
          flat nav header without a seam. */}
      <View style={styles.brandField}>
        <Svg style={StyleSheet.absoluteFill}>
          <Defs>
            <LinearGradient id="payoutField" x1="0" y1="0" x2="0" y2="1">
              <Stop offset="0" stopColor={colors.primary} />
              <Stop offset="1" stopColor={colors.primaryDark} />
            </LinearGradient>
          </Defs>
          <Rect width="100%" height="100%" fill="url(#payoutField)" />
          <Circle cx="105%" cy="18%" r="80" stroke={colors.white} strokeWidth="20" strokeOpacity="0.10" fill="none" />
        </Svg>
        <View style={styles.fieldInner}>
          <Text style={styles.fieldEyebrow}>RETIROS Y COBROS</Text>
          <Text style={styles.fieldTitle}>¿Dónde recibes tu dinero?</Text>
          <Text style={styles.fieldSubtitle}>
            {!bankAccountsLoading && payoutMethods.length > 0
              ? `${payoutMethods.length} ${payoutMethods.length === 1 ? 'forma de cobro guardada' : 'formas de cobro guardadas'} · la predeterminada se usa al retirar`
              : 'Guarda cuentas bancarias o billeteras para recibir retiros y cobros.'}
          </Text>
        </View>
      </View>

      <View style={styles.contentContainer}>
        {banner && (
          <InlineBanner
            message={banner.message}
            variant={banner.variant}
            onDismiss={dismissBanner}
            autoHideMs={banner.variant === 'success' ? 2500 : undefined}
            style={{ marginHorizontal: 16, marginTop: 16, marginBottom: 0 }}
          />
        )}
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
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },

  // ── Brand field ──
  brandField: {
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
  fieldTitle: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.white,
  },
  fieldSubtitle: {
    fontSize: 13,
    lineHeight: 19,
    color: 'rgba(255, 255, 255, 0.85)',
    marginTop: 6,
  },
  addHeaderButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },

  // ── Content ──
  contentContainer: {
    flex: 1,
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
        shadowColor: colors.primaryDeep,
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
  cardIconChip: {
    width: 40,
    height: 40,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    alignSelf: 'center',
    marginLeft: 12,
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
