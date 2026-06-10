import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  FlatList,
  Modal,
  Linking,
  StatusBar,
  Share,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { SHARE_LINKS } from '../config/shareLinks';
import { getCountryByIso } from '../utils/countries';
import { useCountry } from '../contexts/CountryContext';
import { useAuth } from '../contexts/AuthContext';
import { useNumberFormat } from '../utils/numberFormatting';
import { buildInviteLink } from '../utils/inviteLinks';
import { Financiera, USDC_ALGORAND_TAG, serviceBadges } from '../types/financiera';
import {
  GET_FINANCIERAS,
  GET_FINANCIERA_LOCATION_OPTIONS,
  GET_MY_FINANCIERAS,
} from '../apollo/queries';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

const WHATSAPP_GREEN = '#25D366';
const STAR_GOLD = '#F59E0B';

// Location is always scoped to the user's country server-side; the filter only
// cascades through the levels below it.
type LocationFilter = {
  state?: string;
  city?: string;
  barrio?: string;
};

type LevelKey = 'state' | 'city' | 'neighborhood';

// ---- Small presentational helpers -------------------------------------------

const Stars = ({ rating, size = 14 }: { rating: number; size?: number }) => (
  <View style={{ flexDirection: 'row' }}>
    {[1, 2, 3, 4, 5].map((s) => (
      <Icon
        key={s}
        name="star"
        size={size}
        color={rating >= s - 0.25 ? STAR_GOLD : '#E5E7EB'}
        style={{ marginRight: 1 }}
      />
    ))}
  </View>
);

const flagFor = (iso: string) => getCountryByIso(iso)?.[3] || '';
const countryNameFor = (iso: string) => getCountryByIso(iso)?.[0] || iso;

// ---- Location filter modal --------------------------------------------------

const LocationFilterModal = ({
  visible,
  value,
  countryIso,
  onClose,
  onApply,
}: {
  visible: boolean;
  value: LocationFilter;
  countryIso: string;
  onClose: () => void;
  onApply: (next: LocationFilter) => void;
}) => {
  const [draft, setDraft] = useState<LocationFilter>(value);

  React.useEffect(() => {
    if (visible) setDraft(value);
  }, [visible, value]);

  const level: LevelKey = !draft.state ? 'state' : !draft.city ? 'city' : 'neighborhood';

  const { data, loading } = useQuery(GET_FINANCIERA_LOCATION_OPTIONS, {
    variables: { level, state: draft.state, city: draft.city },
    skip: !visible,
    fetchPolicy: 'cache-and-network',
  });
  const options: string[] = data?.financieraLocationOptions || [];

  const title =
    level === 'state' ? 'Estado / Provincia' : level === 'city' ? 'Ciudad' : 'Barrio / Zona';

  const select = (v: string) => {
    if (level === 'state') setDraft({ state: v });
    else if (level === 'city') setDraft({ ...draft, city: v });
    // Barrio is the last level — selecting it commits the filter and closes the
    // sheet, since there is nothing deeper to drill into.
    else onApply({ ...draft, barrio: v });
  };

  const stepBack = () => {
    if (level === 'neighborhood') setDraft({ ...draft, city: undefined });
    else if (level === 'city') setDraft({ state: undefined });
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHandle} />
          <View style={styles.modalHeaderRow}>
            {level !== 'state' ? (
              <TouchableOpacity onPress={stepBack} style={styles.modalIconBtn}>
                <Icon name="chevron-left" size={22} color={colors.text.primary} />
              </TouchableOpacity>
            ) : (
              <View style={styles.modalIconBtn} />
            )}
            <Text style={styles.modalTitle}>{title}</Text>
            <TouchableOpacity onPress={onClose} style={styles.modalIconBtn}>
              <Icon name="x" size={22} color={colors.text.primary} />
            </TouchableOpacity>
          </View>

          {(draft.state || draft.city) && (
            <View style={styles.breadcrumbRow}>
              <Text style={styles.breadcrumb}>
                {flagFor(countryIso)} {countryNameFor(countryIso)}
              </Text>
              {draft.state && <Text style={styles.breadcrumb}> › {draft.state}</Text>}
              {draft.city && <Text style={styles.breadcrumb}> › {draft.city}</Text>}
            </View>
          )}

          {loading && options.length === 0 ? (
            <View style={styles.modalLoading}>
              <ActivityIndicator color={colors.primary} />
            </View>
          ) : options.length === 0 ? (
            <Text style={styles.modalEmptyText}>
              No hay más zonas con financieras dentro de esta selección.
            </Text>
          ) : (
            <FlatList
              data={options}
              keyExtractor={(item) => item}
              style={{ maxHeight: 360 }}
              initialNumToRender={20}
              maxToRenderPerBatch={10}
              windowSize={21}
              renderItem={({ item }) => {
                const selected =
                  (level === 'neighborhood' ? draft.barrio : draft[level as 'state' | 'city']) === item;
                return (
                  <TouchableOpacity style={styles.optionRow} onPress={() => select(item)}>
                    <Text style={[styles.optionLabel, selected && styles.optionLabelSelected]}>
                      {item}
                    </Text>
                    {selected ? (
                      <Icon name="check" size={18} color={colors.primaryDark} />
                    ) : (
                      <Icon name="chevron-right" size={18} color={colors.text.light} />
                    )}
                  </TouchableOpacity>
                );
              }}
            />
          )}

          <View style={styles.modalActions}>
            <TouchableOpacity
              style={styles.modalClearBtn}
              onPress={() => {
                setDraft({});
                onApply({});
              }}
            >
              <Text style={styles.modalClearText}>Limpiar</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.modalApplyBtn} onPress={() => onApply(draft)}>
              <Text style={styles.modalApplyText}>Aplicar</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
};

// ---- Card -------------------------------------------------------------------

// Compact row optimized for comparison: identity + rating on the left, the
// headline "what you get for 100 USDC" figure on the right, badges + a small
// WhatsApp pill below. The full rate breakdown lives on the detail screen.
const FinancieraCard = ({
  financiera,
  onPress,
  onWhatsApp,
}: {
  financiera: Financiera;
  onPress: () => void;
  onWhatsApp: () => void;
}) => {
  const { formatNumber } = useNumberFormat();
  const badges = serviceBadges(financiera);

  return (
    <TouchableOpacity style={styles.card} activeOpacity={0.85} onPress={onPress}>
      <View style={styles.cardTop}>
        <View style={{ flex: 1, marginRight: 12 }}>
          <View style={styles.cardTitleRow}>
            <Text style={styles.cardName} numberOfLines={1}>
              {financiera.name}
            </Text>
            {financiera.isVerified && (
              <Icon name="check-circle" size={14} color={colors.primaryDark} />
            )}
          </View>
          <View style={styles.ratingRow}>
            {financiera.avgRating != null ? (
              <>
                <Stars rating={financiera.avgRating} size={12} />
                <Text style={styles.ratingValue}>
                  {formatNumber(financiera.avgRating, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                </Text>
                <Text style={styles.reviewCount}>({financiera.reviewCount})</Text>
              </>
            ) : (
              <Text style={styles.newTag}>Nuevo · sin reseñas</Text>
            )}
          </View>
          <View style={styles.locationRow}>
            <Icon name="map-pin" size={11} color={colors.text.secondary} />
            <Text style={styles.locationText} numberOfLines={1}>
              {financiera.neighborhood ? `${financiera.neighborhood}, ` : ''}
              {financiera.city}
            </Text>
          </View>
        </View>

        <View style={styles.rateCol}>
          <Text style={styles.rateBig}>
            {financiera.avgReceivedPer100 != null
              ? `$${formatNumber(financiera.avgReceivedPer100, { maximumFractionDigits: 1 })}`
              : '—'}
          </Text>
          <Text style={styles.rateSub}>por 100 USDC</Text>
          <Text style={styles.rateCashTag}>en efectivo</Text>
        </View>
      </View>

      <View style={styles.cardBottom}>
        <View style={styles.chipsRow}>
          <View style={styles.railChip}>
            <Text style={styles.railChipText}>{USDC_ALGORAND_TAG}</Text>
          </View>
          {badges.map((b) => (
            <View key={b} style={styles.serviceChip}>
              <Text style={styles.serviceChipText}>{b}</Text>
            </View>
          ))}
        </View>
        <TouchableOpacity style={styles.whatsappPill} onPress={onWhatsApp}>
          <Icon name="message-circle" size={14} color="#fff" />
          <Text style={styles.whatsappPillText}>WhatsApp</Text>
        </TouchableOpacity>
      </View>
    </TouchableOpacity>
  );
};

// ---- Screen -----------------------------------------------------------------

export const FinancierasScreen = () => {
  const navigation = useNavigation<NavProp>();
  const { userCountry } = useCountry();
  const { userProfile } = useAuth();
  // Display only — the API scopes the directory to the JWT user's country.
  const countryIso = userCountry ? String(userCountry[2]) : '';

  const [search, setSearch] = useState('');
  const [location, setLocation] = useState<LocationFilter>({});
  const [locationModal, setLocationModal] = useState(false);
  const [sortBy, setSortBy] = useState<'rating' | 'rate'>('rating');

  const { data, loading, refetch, networkStatus } = useQuery(GET_FINANCIERAS, {
    variables: {
      state: location.state,
      city: location.city,
      neighborhood: location.barrio,
      sortBy,
      limit: 100,
      offset: 0,
    },
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
  });
  const financieras: Financiera[] = data?.financieras || [];
  const refreshing = networkStatus === 4;

  // Owners get a management shortcut at the top of the directory.
  const { data: myData } = useQuery(GET_MY_FINANCIERAS, { fetchPolicy: 'cache-and-network' });
  const ownedCount = (myData?.myFinancieras || []).length;

  const openWhatsApp = (f: Financiera) => {
    const text = encodeURIComponent(
      `Hola ${f.name}, te encontré en Confío. Quiero cambiar USDC por dólares.`,
    );
    Linking.openURL(`https://wa.me/${f.whatsapp}?text=${text}`).catch(() => {});
  };

  // Growth loop: let users invite a financiera they already trust. The
  // personalized invite link credits the inviter and tracks this funnel.
  const inviteFinanciera = () => {
    const inviteLink = userProfile?.username
      ? buildInviteLink({ username: userProfile.username, source: 'financieras' })
      : SHARE_LINKS.web.landing;
    Share.share({
      message:
        `¿Tienes una financiera? Regístrala gratis en Confío y recibe clientes que quieren cambiar dólares digitales por efectivo: ${inviteLink}`,
    }).catch(() => {});
  };

  // Server handles location + sort; the search box filters the loaded page.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return financieras;
    return financieras.filter((f) =>
      `${f.name} ${f.city} ${f.neighborhood} ${f.state}`.toLowerCase().includes(q),
    );
  }, [search, financieras]);

  const locationLabel = useMemo(() => {
    if (location.barrio) return location.barrio;
    if (location.city) return location.city;
    if (location.state) return location.state;
    return countryIso ? `Todo ${countryNameFor(countryIso)}` : 'Todas las zonas';
  }, [location, countryIso]);

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        <View style={styles.header}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn}>
              <Icon name="arrow-left" size={24} color="#fff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Financieras</Text>
            <TouchableOpacity
              onPress={() => navigation.navigate('RegisterFinanciera')}
              style={styles.headerIconBtn}
            >
              <Icon name="plus" size={24} color="#fff" />
            </TouchableOpacity>
          </View>
          <Text style={styles.headerSubtitle}>
            {countryIso ? `${flagFor(countryIso)} ` : ''}
            Cambia USDC por dólares en efectivo con financieras
            {countryIso ? ` de ${countryNameFor(countryIso)}` : ' locales'}
          </Text>
        </View>
      </SafeAreaView>

      <FlatList
        data={filtered}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.listContent}
        initialNumToRender={10}
        maxToRenderPerBatch={8}
        windowSize={11}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => refetch()}
            tintColor={colors.primary}
          />
        }
        ListHeaderComponent={
          <View>
            {/* Owner shortcut */}
            {ownedCount > 0 && (
              <TouchableOpacity
                style={styles.myFinancierasBanner}
                onPress={() => navigation.navigate('MyFinancieras')}
              >
                <Icon name="briefcase" size={16} color={colors.primaryDark} />
                <Text style={styles.myFinancierasText}>
                  {ownedCount === 1 ? 'Gestionar mi financiera' : `Gestionar mis ${ownedCount} financieras`}
                </Text>
                <Icon name="chevron-right" size={16} color={colors.primaryDark} />
              </TouchableOpacity>
            )}

            {/* Disclaimer: we only list, we don't intermediate */}
            <View style={styles.disclaimer}>
              <Icon name="info" size={14} color={colors.accent} />
              <Text style={styles.disclaimerText}>
                Confío no participa en estos cambios. Solo mostramos financieras locales y sus
                reseñas para que decidas con confianza.
              </Text>
            </View>

            {/* Search */}
            <View style={styles.searchBox}>
              <Icon name="search" size={18} color={colors.text.light} />
              <TextInput
                style={styles.searchInput}
                placeholder="Buscar financiera, ciudad o barrio"
                placeholderTextColor={colors.text.light}
                value={search}
                onChangeText={setSearch}
              />
              {search.length > 0 && (
                <TouchableOpacity onPress={() => setSearch('')}>
                  <Icon name="x-circle" size={18} color={colors.text.light} />
                </TouchableOpacity>
              )}
            </View>

            {/* Location pill */}
            <TouchableOpacity style={styles.locationPill} onPress={() => setLocationModal(true)}>
              <Icon name="map-pin" size={16} color={colors.primaryDark} />
              <Text style={styles.locationPillText} numberOfLines={1}>
                {locationLabel}
              </Text>
              <Icon name="chevron-down" size={16} color={colors.text.secondary} />
            </TouchableOpacity>

            {/* Sort + result count */}
            <View style={styles.sortRow}>
              <View style={styles.sortChips}>
                {(
                  [
                    { key: 'rating', label: 'Mejor calificación' },
                    { key: 'rate', label: 'Mejor tasa' },
                  ] as const
                ).map((s) => {
                  const active = sortBy === s.key;
                  return (
                    <TouchableOpacity
                      key={s.key}
                      style={[styles.sortChip, active && styles.sortChipActive]}
                      onPress={() => setSortBy(s.key)}
                    >
                      <Text style={[styles.sortChipText, active && styles.sortChipTextActive]}>
                        {s.label}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
              <Text style={styles.resultCount}>{filtered.length}</Text>
            </View>
          </View>
        }
        ListFooterComponent={
          filtered.length > 0 ? (
            <View style={styles.registerCard}>
              <View style={styles.registerIcon}>
                <Icon name="briefcase" size={20} color={colors.primaryDark} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.registerTitle}>¿Tienes una financiera?</Text>
                <Text style={styles.registerText}>
                  Regístrala gratis y recibe clientes de tu zona.
                </Text>
              </View>
              <TouchableOpacity
                style={styles.registerBtn}
                onPress={() => navigation.navigate('RegisterFinanciera')}
              >
                <Text style={styles.registerBtnText}>Registrar</Text>
              </TouchableOpacity>
            </View>
          ) : null
        }
        renderItem={({ item }) => (
          <FinancieraCard
            financiera={item}
            onPress={() => navigation.navigate('FinancieraDetail', { financieraId: item.id })}
            onWhatsApp={() => openWhatsApp(item)}
          />
        )}
        ListEmptyComponent={
          loading ? (
            <View style={styles.empty}>
              <ActivityIndicator color={colors.primary} size="large" />
            </View>
          ) : (
            <View style={styles.empty}>
              <Icon name="map-pin" size={40} color={colors.text.light} />
              <Text style={styles.emptyTitle}>Aún no hay financieras aquí</Text>
              <Text style={styles.emptyText}>
                Prueba otra zona, o invita a una financiera de confianza a registrarse.
              </Text>
              <TouchableOpacity style={styles.emptyInviteBtn} onPress={inviteFinanciera}>
                <Icon name="share-2" size={16} color="#fff" />
                <Text style={styles.emptyInviteText}>Invitar a una financiera</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => navigation.navigate('RegisterFinanciera')}>
                <Text style={styles.emptyRegisterLink}>¿Es tuya? Regístrala gratis</Text>
              </TouchableOpacity>
            </View>
          )
        }
      />

      <LocationFilterModal
        visible={locationModal}
        value={location}
        countryIso={countryIso}
        onClose={() => setLocationModal(false)}
        onApply={(next) => {
          setLocation(next);
          setLocationModal(false);
        }}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  // Header
  header: { backgroundColor: colors.primary, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 20 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },
  headerSubtitle: { fontSize: 13, color: '#fff', opacity: 0.9, marginTop: 8, lineHeight: 18 },

  listContent: { padding: 16, paddingBottom: 40 },

  myFinancierasBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.primaryLight,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginBottom: 12,
  },
  myFinancierasText: { flex: 1, fontSize: 14, fontWeight: '700', color: colors.primaryDark },

  // Disclaimer
  disclaimer: {
    flexDirection: 'row',
    backgroundColor: colors.infoLight,
    borderRadius: 12,
    padding: 12,
    gap: 8,
    marginBottom: 16,
  },
  disclaimerText: { flex: 1, fontSize: 12, color: colors.text.secondary, lineHeight: 17 },

  // Search
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 12,
    height: 46,
    gap: 8,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.text.primary, paddingVertical: 0 },

  // Location pill
  locationPill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 12,
    height: 44,
    marginTop: 10,
    gap: 8,
  },
  locationPillText: { flex: 1, fontSize: 14, fontWeight: '600', color: colors.text.primary },

  // Sort + result count
  sortRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 12,
    marginBottom: 4,
  },
  sortChips: { flexDirection: 'row', gap: 8 },
  sortChip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 16,
    backgroundColor: colors.surfaceMuted,
  },
  sortChipActive: { backgroundColor: colors.primary },
  sortChipText: { fontSize: 12, fontWeight: '600', color: colors.text.secondary },
  sortChipTextActive: { color: '#fff' },
  resultCount: { fontSize: 12, color: colors.text.secondary },

  // Card (compact comparison row)
  card: {
    backgroundColor: '#fff',
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 14,
    marginTop: 10,
    borderWidth: 1,
    borderColor: colors.borderLight,
  },
  cardTop: { flexDirection: 'row', alignItems: 'flex-start' },
  cardTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  cardName: { fontSize: 15, fontWeight: '700', color: colors.text.primary, flexShrink: 1 },
  ratingRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 4 },
  ratingValue: { fontSize: 12, fontWeight: '700', color: colors.text.primary },
  reviewCount: { fontSize: 11, color: colors.text.secondary },
  newTag: { fontSize: 12, fontWeight: '600', color: colors.accent },
  locationRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 4 },
  locationText: { fontSize: 12, color: colors.text.secondary, flex: 1 },

  rateCol: { alignItems: 'flex-end' },
  rateBig: { fontSize: 20, fontWeight: '800', color: colors.primaryDark },
  rateSub: { fontSize: 10, color: colors.text.secondary, marginTop: 1 },
  rateCashTag: { fontSize: 10, fontWeight: '700', color: colors.primaryDark, marginTop: 1 },

  cardBottom: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 10,
    gap: 8,
  },
  chipsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 5, flex: 1, alignItems: 'center' },
  railChip: {
    backgroundColor: colors.primaryLight,
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 5,
  },
  railChipText: { fontSize: 10, fontWeight: '700', color: colors.primaryDark },
  serviceChip: { backgroundColor: colors.surfaceMuted, paddingHorizontal: 7, paddingVertical: 3, borderRadius: 5 },
  serviceChipText: { fontSize: 10, fontWeight: '600', color: colors.text.secondary },

  whatsappPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    backgroundColor: WHATSAPP_GREEN,
    borderRadius: 16,
    paddingHorizontal: 12,
    height: 32,
  },
  whatsappPillText: { color: '#fff', fontSize: 12, fontWeight: '700' },

  // Register footer card
  registerCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: colors.primarySoft,
    borderRadius: 14,
    padding: 14,
    marginTop: 16,
  },
  registerIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primaryLight,
    alignItems: 'center',
    justifyContent: 'center',
  },
  registerTitle: { fontSize: 14, fontWeight: '700', color: colors.text.primary },
  registerText: { fontSize: 12, color: colors.text.secondary, marginTop: 2 },
  registerBtn: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  registerBtnText: { fontSize: 13, fontWeight: '700', color: '#fff' },

  // Empty
  empty: { alignItems: 'center', paddingVertical: 48, paddingHorizontal: 24 },
  emptyTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary, marginTop: 12 },
  emptyText: { fontSize: 13, color: colors.text.secondary, textAlign: 'center', marginTop: 6, lineHeight: 19 },
  emptyInviteBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingHorizontal: 20,
    height: 46,
    marginTop: 20,
  },
  emptyInviteText: { fontSize: 14, fontWeight: '700', color: '#fff' },
  emptyRegisterLink: { fontSize: 13, fontWeight: '600', color: colors.primaryDark, marginTop: 14 },

  // Modal
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 16,
    paddingBottom: 28,
    paddingTop: 8,
  },
  modalHandle: {
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    alignSelf: 'center',
    marginBottom: 8,
  },
  modalHeaderRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  modalIconBtn: { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  modalTitle: { fontSize: 16, fontWeight: '700', color: colors.text.primary },
  modalLoading: { paddingVertical: 40, alignItems: 'center' },
  modalEmptyText: {
    paddingVertical: 32,
    textAlign: 'center',
    fontSize: 13,
    color: colors.text.secondary,
  },
  breadcrumbRow: { flexDirection: 'row', flexWrap: 'wrap', paddingVertical: 6 },
  breadcrumb: { fontSize: 12, color: colors.text.secondary },
  optionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  optionLabel: { fontSize: 15, color: colors.text.primary },
  optionLabelSelected: { fontWeight: '700', color: colors.primaryDark },
  modalActions: { flexDirection: 'row', gap: 12, marginTop: 16 },
  modalClearBtn: {
    flex: 1,
    height: 48,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  modalClearText: { fontSize: 15, fontWeight: '600', color: colors.text.secondary },
  modalApplyBtn: {
    flex: 2,
    height: 48,
    borderRadius: 12,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  modalApplyText: { fontSize: 15, fontWeight: '700', color: '#fff' },
});

export default FinancierasScreen;
