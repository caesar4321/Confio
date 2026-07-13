import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  FlatList,
  Modal,
  Alert,
  Linking,
  StatusBar,
  Share,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import { SHARE_LINKS } from '../config/shareLinks';
import { Country, filterCountries, getCountryByIso } from '../utils/countries';
import { useCountry } from '../contexts/CountryContext';
import { useAuth } from '../contexts/AuthContext';
import { useNumberFormat } from '../utils/numberFormatting';
import { buildInviteLink } from '../utils/inviteLinks';
import { AnalyticsService } from '../services/analyticsService';
import { OfferCardSkeleton } from '../components/SkeletonLoader';
import {
  Financiera,
  USDC_ALGORAND_TAG,
  localCurrencyShort,
  serviceBadges,
} from '../types/financiera';
import {
  GET_FINANCIERAS,
  GET_FINANCIERA_COUNTRIES,
  GET_FINANCIERA_LOCATION_OPTIONS,
  GET_MY_FINANCIERAS,
} from '../apollo/queries';

type NavProp = NativeStackNavigationProp<MainStackParamList>;

const WHATSAPP_GREEN = '#25D366';
const STAR_GOLD = colors.offRampIcon;

type LocationFilter = {
  state?: string;
  city?: string;
  barrio?: string;
};

// Payout facet keys map 1:1 to Financiera boolean fields.
type PayoutKey = 'cashUsd' | 'cashLocal' | 'digitalLocal';

type LevelKey = 'state' | 'city' | 'neighborhood';

// ---- Small presentational helpers -------------------------------------------

const Stars = ({ rating, size = 14 }: { rating: number; size?: number }) => (
  <View style={{ flexDirection: 'row' }}>
    {[1, 2, 3, 4, 5].map((s) => (
      <Icon
        key={s}
        name="star"
        size={size}
        color={rating >= s - 0.25 ? STAR_GOLD : colors.border}
        style={{ marginRight: 1 }}
      />
    ))}
  </View>
);

const flagFor = (iso: string) => getCountryByIso(iso)?.[3] || '';
const countryNameFor = (iso: string) => getCountryByIso(iso)?.[0] || iso;

// The headline figure is always the USD value of what reviewers reported, so
// the tag under it must describe the number, not the payout method list.
const rateTag = (f: Financiera) => (f.cashUsd ? 'en efectivo' : 'equivalente en USD');

const CountryPickerModal = ({
  visible,
  valueIso,
  listingCounts,
  onClose,
  onSelect,
}: {
  visible: boolean;
  valueIso: string;
  listingCounts: Record<string, number>;
  onClose: () => void;
  onSelect: (c: Country) => void;
}) => {
  const [q, setQ] = useState('');
  const data = useMemo(() => {
    const base = filterCountries(q);
    // Countries that already have listings float to the top so users land on
    // real content instead of wandering into empty countries. Stable sort
    // keeps the alphabetical order within each group.
    return [...base].sort(
      (a, b) => (listingCounts[String(b[2])] || 0) - (listingCounts[String(a[2])] || 0),
    );
  }, [q, listingCounts]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalSheet}>
          <View style={styles.modalHandle} />
          <View style={styles.modalHeaderRow}>
            <Text style={styles.modalTitle}>País</Text>
            <TouchableOpacity onPress={onClose} style={styles.modalIconBtn} accessibilityRole="button" accessibilityLabel="Cerrar">
              <Icon name="x" size={22} color={colors.text.primary} />
            </TouchableOpacity>
          </View>
          <View style={styles.modalSearchBox}>
            <Icon name="search" size={18} color={colors.text.light} />
            <TextInput
              style={styles.searchInput}
              placeholder="Buscar país"
              placeholderTextColor={colors.text.light}
              value={q}
              onChangeText={setQ}
            />
          </View>
          <FlatList
            data={data}
            keyExtractor={(item) => String(item[2])}
            style={{ maxHeight: 420 }}
            initialNumToRender={20}
            maxToRenderPerBatch={15}
            windowSize={21}
            keyboardShouldPersistTaps="handled"
            renderItem={({ item }) => {
              const selected = String(item[2]) === valueIso;
              return (
                <TouchableOpacity
                  style={styles.optionRow}
                  onPress={() => {
                    onSelect(item);
                    setQ('');
                  }}
                >
                  <Text style={[styles.optionLabel, selected && styles.optionLabelSelected]}>
                    {item[3]}  {item[0]}
                  </Text>
                  {selected ? (
                    <Icon name="check" size={18} color={colors.primaryDark} />
                  ) : listingCounts[String(item[2])] ? (
                    <Text style={styles.optionCount}>
                      {listingCounts[String(item[2])]}{' '}
                      {listingCounts[String(item[2])] === 1 ? 'financiera' : 'financieras'}
                    </Text>
                  ) : (
                    <Text style={styles.optionCode}>{item[1]}</Text>
                  )}
                </TouchableOpacity>
              );
            }}
          />
        </View>
      </View>
    </Modal>
  );
};

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
    variables: { level, state: draft.state, city: draft.city, countryCode: countryIso },
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
              <TouchableOpacity onPress={stepBack} style={styles.modalIconBtn} accessibilityRole="button" accessibilityLabel="Volver al nivel anterior">
                <Icon name="chevron-left" size={22} color={colors.text.primary} />
              </TouchableOpacity>
            ) : (
              <View style={styles.modalIconBtn} />
            )}
            <Text style={styles.modalTitle}>{title}</Text>
            <TouchableOpacity onPress={onClose} style={styles.modalIconBtn} accessibilityRole="button" accessibilityLabel="Cerrar">
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
          <Text style={styles.rateCashTag}>{rateTag(financiera)}</Text>
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
          <Icon name="message-circle" size={14} color={colors.white} />
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
  const defaultCountryIso = userCountry ? String(userCountry[2]) : '';

  const [search, setSearch] = useState('');
  const [selectedCountryIso, setSelectedCountryIso] = useState(defaultCountryIso);
  const [countryModal, setCountryModal] = useState(false);
  const [location, setLocation] = useState<LocationFilter>({});
  const [locationModal, setLocationModal] = useState(false);
  const [sortBy, setSortBy] = useState<'rating' | 'rate'>('rating');
  // Facet chips: attention mode is one-of (local vs digital); payout methods
  // are any-of. Both AND together, matching standard faceted filtering.
  const [attentionFilter, setAttentionFilter] = useState<'local' | 'digital' | null>(null);
  const [payoutFilters, setPayoutFilters] = useState<PayoutKey[]>([]);

  useEffect(() => {
    if (defaultCountryIso && !selectedCountryIso) {
      setSelectedCountryIso(defaultCountryIso);
    }
  }, [defaultCountryIso, selectedCountryIso]);

  const { data, loading, refetch, networkStatus } = useQuery(GET_FINANCIERAS, {
    variables: {
      state: location.state,
      city: location.city,
      neighborhood: location.barrio,
      countryCode: selectedCountryIso || undefined,
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

  // Which countries actually have listings — the picker pins them first so
  // users don't wander into empty countries.
  const { data: countryData } = useQuery(GET_FINANCIERA_COUNTRIES, {
    fetchPolicy: 'cache-and-network',
  });
  const listingCounts: Record<string, number> = useMemo(() => {
    const map: Record<string, number> = {};
    (countryData?.financieraCountries || []).forEach(
      (c: { countryCode: string; count: number }) => {
        map[c.countryCode] = c.count;
      },
    );
    return map;
  }, [countryData]);

  const openWhatsApp = (f: Financiera) => {
    void AnalyticsService.logFunnelEvent(
      'financiera_whatsapp_tapped',
      { financiera_id: f.id, surface: 'directory', country: f.countryCode },
      { sourceType: 'financieras', channel: 'whatsapp' },
    );
    const text = encodeURIComponent(
      `Hola ${f.name}, te encontré en el directorio de Confío y quiero más información.`,
    );
    Linking.openURL(`https://wa.me/${f.whatsapp}?text=${text}`).catch(() => {});
  };

  // Friendly heads-up (not a scare screen): sets the "Confío only lists" frame
  // at the exact moment of contact, when it actually matters.
  const confirmWhatsApp = (f: Financiera) => {
    Alert.alert(
      `Contactar a ${f.name}`,
      'Confío es un directorio informativo: el acuerdo es directamente entre tú y la financiera.\n\nConsejo: la primera vez, empieza con un monto pequeño.',
      [
        { text: 'Cancelar', style: 'cancel' },
        { text: 'Abrir WhatsApp', onPress: () => openWhatsApp(f) },
      ],
    );
  };

  // Growth loop: let users invite a financiera they already trust. The
  // personalized invite link credits the inviter and tracks this funnel.
  const inviteFinanciera = () => {
    const inviteLink = userProfile?.username
      ? buildInviteLink({ username: userProfile.username, source: 'financieras' })
      : SHARE_LINKS.web.landing;
    Share.share({
      message:
        `¿Tienes una financiera? Regístrala gratis en el directorio de Confío y recibe clientes de tu zona: ${inviteLink}`,
    }).catch(() => {});
  };

  // Server handles location + sort; search and facet chips filter the loaded
  // page client-side (fine at directory scale — one country fits in a page).
  const filtered = useMemo(() => {
    let list = financieras;
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter((f) =>
        `${f.name} ${f.city} ${f.neighborhood} ${f.state}`.toLowerCase().includes(q),
      );
    }
    if (attentionFilter) {
      list = list.filter((f) =>
        attentionFilter === 'local' ? f.hasPhysicalLocation : !f.hasPhysicalLocation,
      );
    }
    if (payoutFilters.length > 0) {
      list = list.filter((f) => payoutFilters.some((key) => f[key]));
    }
    return list;
  }, [search, financieras, attentionFilter, payoutFilters]);

  const filtersActive = attentionFilter != null || payoutFilters.length > 0;
  const clearFacets = () => {
    setAttentionFilter(null);
    setPayoutFilters([]);
  };

  const locationLabel = useMemo(() => {
    if (location.barrio) return location.barrio;
    if (location.city) return location.city;
    if (location.state) return location.state;
    return selectedCountryIso ? `Todo ${countryNameFor(selectedCountryIso)}` : 'Todas las zonas';
  }, [location, selectedCountryIso]);

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.primary} />
      <SafeAreaView edges={['top']} style={{ backgroundColor: colors.primary }}>
        {/* Brand field: emerald gradient + coin ring; padding on headerInner
            (Yoga insets absolute children by parent padding). */}
        <View style={styles.header}>
          <Svg style={StyleSheet.absoluteFill}>
            <Defs>
              <SvgLinearGradient id="financierasField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.primary} />
                <Stop offset="1" stopColor={colors.primaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#financierasField)" />
            <Circle cx="105%" cy="30%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.headerInner}>
          <View style={styles.headerTopRow}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerIconBtn} accessibilityRole="button" accessibilityLabel="Volver">
              <Icon name="arrow-left" size={24} color={colors.white} />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Financieras</Text>
            <TouchableOpacity
              onPress={() => navigation.navigate('RegisterFinanciera')}
              style={styles.headerIconBtn}
              accessibilityRole="button"
              accessibilityLabel="Registrar financiera"
            >
              <Icon name="plus" size={24} color={colors.white} />
            </TouchableOpacity>
          </View>
          <Text style={styles.headerSubtitle}>
            {selectedCountryIso ? `${flagFor(selectedCountryIso)} ` : ''}
            Financieras verificadas
            {selectedCountryIso ? ` de ${countryNameFor(selectedCountryIso)}` : ''}
          </Text>
          </View>
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
                Confío es un directorio informativo. No participa en los acuerdos entre tú y
                la financiera; solo mostramos listados y reseñas para que decidas con confianza.
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
                <TouchableOpacity onPress={() => setSearch('')} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} accessibilityRole="button" accessibilityLabel="Borrar búsqueda">
                  <Icon name="x-circle" size={18} color={colors.text.light} />
                </TouchableOpacity>
              )}
            </View>

            <View style={styles.filterRow}>
              <TouchableOpacity style={[styles.locationPill, styles.countryPill]} onPress={() => setCountryModal(true)}>
                <Text style={styles.countryFlag}>{selectedCountryIso ? flagFor(selectedCountryIso) : ''}</Text>
                <Text style={styles.locationPillText} numberOfLines={1}>
                  {selectedCountryIso ? countryNameFor(selectedCountryIso) : 'País'}
                </Text>
                <Icon name="chevron-down" size={16} color={colors.text.secondary} />
              </TouchableOpacity>
              <TouchableOpacity style={[styles.locationPill, { flex: 1 }]} onPress={() => setLocationModal(true)}>
                <Icon name="map-pin" size={16} color={colors.primaryDark} />
                <Text style={styles.locationPillText} numberOfLines={1}>
                  {locationLabel}
                </Text>
                <Icon name="chevron-down" size={16} color={colors.text.secondary} />
              </TouchableOpacity>
            </View>

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

            {/* Facet chips: attention mode + payout methods */}
            <View style={styles.facetRow}>
              {(
                [
                  { key: 'local', label: 'Local físico' },
                  { key: 'digital', label: 'Atención digital' },
                ] as const
              ).map((a) => {
                const active = attentionFilter === a.key;
                return (
                  <TouchableOpacity
                    key={a.key}
                    style={[styles.facetChip, active && styles.facetChipActive]}
                    onPress={() => setAttentionFilter(active ? null : a.key)}
                  >
                    <Text style={[styles.facetChipText, active && styles.facetChipTextActive]}>
                      {a.label}
                    </Text>
                  </TouchableOpacity>
                );
              })}
              {(
                [
                  { key: 'cashUsd' as PayoutKey, label: 'Efectivo USD' },
                  {
                    key: 'cashLocal' as PayoutKey,
                    label: `Efectivo ${localCurrencyShort(selectedCountryIso)}`,
                  },
                  {
                    key: 'digitalLocal' as PayoutKey,
                    label: `${localCurrencyShort(selectedCountryIso)} digital`,
                  },
                ]
              ).map((p) => {
                const active = payoutFilters.includes(p.key);
                return (
                  <TouchableOpacity
                    key={p.key}
                    style={[styles.facetChip, active && styles.facetChipActive]}
                    onPress={() =>
                      setPayoutFilters((prev) =>
                        active ? prev.filter((k) => k !== p.key) : [...prev, p.key],
                      )
                    }
                  >
                    <Text style={[styles.facetChipText, active && styles.facetChipTextActive]}>
                      {p.label}
                    </Text>
                  </TouchableOpacity>
                );
              })}
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
            onWhatsApp={() => confirmWhatsApp(item)}
          />
        )}
        ListEmptyComponent={
          loading ? (
            <View style={{ paddingTop: 8 }}>
              {Array.from({ length: 4 }).map((_, i) => (
                <OfferCardSkeleton key={i} />
              ))}
            </View>
          ) : financieras.length > 0 && filtersActive ? (
            // The country HAS listings — the facets just filtered them all out.
            // Recruiting here would be wrong; offer to clear instead.
            <View style={styles.empty}>
              <Icon name="filter" size={40} color={colors.text.light} />
              <Text style={styles.emptyTitle}>Sin resultados con estos filtros</Text>
              <TouchableOpacity style={styles.emptyInviteBtn} onPress={clearFacets}>
                <Text style={styles.emptyInviteText}>Limpiar filtros</Text>
              </TouchableOpacity>
            </View>
          ) : (
            // A truly empty country is a recruitment surface, not a dead end.
            <View style={styles.empty}>
              <Icon name="map-pin" size={40} color={colors.text.light} />
              <Text style={styles.emptyTitle}>
                {selectedCountryIso
                  ? `Aún no hay financieras en ${countryNameFor(selectedCountryIso)}`
                  : 'Aún no hay financieras aquí'}
              </Text>
              <Text style={styles.emptyText}>
                ¿Conoces una casa de cambio de confianza? Invítala — sus primeros
                clientes ya están en Confío.
              </Text>
              <TouchableOpacity style={styles.emptyInviteBtn} onPress={inviteFinanciera}>
                <Icon name="share-2" size={16} color={colors.white} />
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
        countryIso={selectedCountryIso}
        onClose={() => setLocationModal(false)}
        onApply={(next) => {
          setLocation(next);
          setLocationModal(false);
        }}
      />
      <CountryPickerModal
        visible={countryModal}
        valueIso={selectedCountryIso}
        listingCounts={listingCounts}
        onClose={() => setCountryModal(false)}
        onSelect={(country) => {
          const nextIso = String(country[2]);
          setSelectedCountryIso(nextIso);
          setLocation({});
          setCountryModal(false);
        }}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },

  // Header
  header: { backgroundColor: colors.primary, overflow: 'hidden' },
  headerInner: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 20 },
  headerTopRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  headerIconBtn: { padding: 6, width: 40, alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: colors.white },
  headerSubtitle: { fontSize: 13, color: colors.white, opacity: 0.9, marginTop: 8, lineHeight: 18 },

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
    backgroundColor: colors.white,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 12,
    height: 46,
    gap: 8,
  },
  searchInput: { flex: 1, fontSize: 15, color: colors.text.primary, paddingVertical: 0 },

  // Location pill
  filterRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  locationPill: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.white,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 12,
    height: 44,
    gap: 8,
  },
  countryPill: { flexBasis: 136, flexGrow: 0, flexShrink: 0 },
  countryFlag: { fontSize: 16 },
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
  sortChipTextActive: { color: colors.white },

  facetRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 },
  facetChip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 14,
    backgroundColor: colors.surfaceMuted,
    borderWidth: 1,
    borderColor: 'transparent',
  },
  facetChipActive: {
    backgroundColor: colors.primaryLight,
    borderColor: colors.primaryDark,
  },
  facetChipText: { fontSize: 12, fontWeight: '600', color: colors.text.secondary },
  facetChipTextActive: { color: colors.primaryDark },
  resultCount: { fontSize: 12, color: colors.text.secondary },

  // Card (compact comparison row)
  card: {
    backgroundColor: colors.white,
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
  whatsappPillText: { color: colors.white, fontSize: 12, fontWeight: '700' },

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
  registerBtnText: { fontSize: 13, fontWeight: '700', color: colors.white },

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
  emptyInviteText: { fontSize: 14, fontWeight: '700', color: colors.white },
  emptyRegisterLink: { fontSize: 13, fontWeight: '600', color: colors.primaryDark, marginTop: 14 },

  // Modal
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: colors.white,
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
  modalSearchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surfaceMuted,
    borderRadius: 12,
    paddingHorizontal: 12,
    height: 44,
    gap: 8,
    marginBottom: 8,
  },
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
  optionCode: { fontSize: 14, color: colors.text.light },
  optionCount: { fontSize: 13, fontWeight: '700', color: colors.primaryDark },
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
  modalApplyText: { fontSize: 15, fontWeight: '700', color: colors.white },
});

export default FinancierasScreen;
