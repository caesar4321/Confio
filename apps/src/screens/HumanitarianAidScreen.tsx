import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { Buffer } from 'buffer';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, LinearGradient as SvgLinearGradient, Stop, Rect } from 'react-native-svg';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useMutation, useQuery } from '@apollo/client';
import {
  GET_HUMANITARIAN_CAMPAIGN,
  GET_MY_BALANCES,
  GET_MY_HUMANITARIAN_VOLUNTEER_APPLICATION,
} from '../apollo/queries';
import { APPLY_HUMANITARIAN_VOLUNTEER } from '../apollo/mutations';
import { MainStackParamList } from '../types/navigation';
import { colors } from '../config/theme';
import algorandService from '../services/algorandService';
import { biometricAuthService } from '../services/biometricAuthService';
import { HumanitarianWsSession } from '../services/humanitarianWs';
import { countryInfo } from '../utils/humanitarianCountry';

const DEFAULT_CAMPAIGN_SLUG = 'venezuela-2026-earthquake';
const SUGGESTED_AMOUNTS = ['5', '10', '25', '50'];
type Navigation = NativeStackNavigationProp<MainStackParamList>;

function toNumber(value?: string | number | null) {
  const n = typeof value === 'number' ? value : parseFloat(String(value || '0'));
  return Number.isFinite(n) ? n : 0;
}

function formatAmount(value?: string | number | null) {
  const n = toNumber(value);
  return `${n.toLocaleString('es-VE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} cUSD`;
}

function formatCompact(value?: string | number | null) {
  const n = toNumber(value);
  return `${n.toLocaleString('es-VE', { maximumFractionDigits: 0 })} cUSD`;
}

function shortHash(hash?: string | null) {
  if (!hash) return '';
  return hash.length > 14 ? `${hash.slice(0, 7)}...${hash.slice(-5)}` : hash;
}

function normalizeStatus(status?: string | null) {
  return String(status || '').toLowerCase();
}

function timeAgo(iso?: string | null) {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return '';
  const diffMin = Math.floor((Date.now() - then) / 60000);
  if (diffMin < 1) return 'ahora';
  if (diffMin < 60) return `hace ${diffMin} min`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `hace ${diffH} h`;
  const diffD = Math.floor(diffH / 24);
  return diffD === 1 ? 'hace 1 día' : `hace ${diffD} días`;
}

function initials(name?: string | null) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '❤';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

const AVATAR_COLORS = [
  { bg: '#D1FAE5', fg: '#047857' }, // emerald
  { bg: '#DBEAFE', fg: '#1D4ED8' }, // blue
  { bg: '#EDE9FE', fg: '#6D28D9' }, // violet
  { bg: '#FEF3C7', fg: '#B45309' }, // amber
  { bg: '#FCE7F3', fg: '#BE185D' }, // pink
  { bg: '#CCFBF1', fg: '#0F766E' }, // teal
];

function avatarColor(name?: string | null) {
  const s = String(name || '');
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function explorerBase() {
  return __DEV__ ? 'https://testnet.explorer.perawallet.app' : 'https://explorer.perawallet.app';
}

function openAddress(address?: string | null) {
  if (!address) return;
  Linking.openURL(`${explorerBase()}/address/${encodeURIComponent(address)}`);
}

function openTransaction(hash?: string | null) {
  if (!hash) return;
  Linking.openURL(`${explorerBase()}/tx/${encodeURIComponent(hash)}`);
}

export const HumanitarianAidScreen = () => {
  const navigation = useNavigation<Navigation>();
  const route = useRoute<RouteProp<MainStackParamList, 'HumanitarianAid'>>();
  const campaignSlug = route.params?.slug || DEFAULT_CAMPAIGN_SLUG;
  const [serviceArea, setServiceArea] = useState('');
  const [notes, setNotes] = useState('');
  const [selectedAmount, setSelectedAmount] = useState<string | null>(null);
  const [customAmount, setCustomAmount] = useState('');
  const [donating, setDonating] = useState(false);
  const [heroSize, setHeroSize] = useState({ width: 0, height: 0 });
  const { data, loading, error, refetch } = useQuery(GET_HUMANITARIAN_CAMPAIGN, {
    variables: { slug: campaignSlug },
    fetchPolicy: 'cache-and-network',
  });
  const { data: balancesData, loading: balancesLoading, refetch: refetchBalances } = useQuery(GET_MY_BALANCES, {
    fetchPolicy: 'cache-and-network',
  });
  const campaign = data?.humanitarianCampaign;
  const country = countryInfo(campaign?.countryCode);
  const volunteerSectionTitle = campaign?.volunteerSectionTitle || '';
  const volunteerSectionSubtitle = campaign?.volunteerSectionSubtitle || '';
  const volunteerServiceAreaPlaceholder = campaign?.volunteerServiceAreaPlaceholder || '';
  const volunteerNotesPlaceholder = campaign?.volunteerNotesPlaceholder || '';
  const volunteerCtaLabel = campaign?.volunteerCtaLabel || '';
  const {
    data: myApplicationData,
    refetch: refetchApplication,
  } = useQuery(GET_MY_HUMANITARIAN_VOLUNTEER_APPLICATION, {
    variables: { slug: campaignSlug },
    skip: !campaign?.slug,
    fetchPolicy: 'cache-and-network',
  });
  const [applyVolunteer, { loading: applying }] = useMutation(APPLY_HUMANITARIAN_VOLUNTEER);

  const proofCount = useMemo(() => {
    return (campaign?.releases || []).reduce((count: number, release: any) => {
      return count + (release?.proofLinks?.length || 0);
    }, 0);
  }, [campaign?.releases]);

  const goal = toNumber(campaign?.goalAmount);
  const donated = toNumber(campaign?.totalDonated);
  const rawProgress = goal > 0 ? (donated / goal) * 100 : 0;
  const displayProgress = Math.round(rawProgress);
  const fillWidth = Math.min(100, Math.max(rawProgress, donated > 0 ? 3 : 0));
  const goalReached = goal > 0 && donated >= goal;
  const donationAmount = selectedAmount || customAmount;
  const parsedDonationAmount = parseFloat(String(donationAmount || '').replace(',', '.')) || 0;
  const availableCusd = useMemo(() => parseFloat(balancesData?.myBalances?.cusd || '0'), [balancesData?.myBalances?.cusd]);
  const exceedsBalance = !balancesLoading && parsedDonationAmount > availableCusd;
  const canDonate = parsedDonationAmount >= 1 && !exceedsBalance && !donating;
  const hasNoBalance = !balancesLoading && availableCusd <= 0;
  const needsTopUp = hasNoBalance || exceedsBalance;

  const onApply = async () => {
    try {
      const res = await applyVolunteer({
        variables: {
          campaignSlug,
          serviceArea: serviceArea.trim(),
          notes: notes.trim(),
        },
      });
      const payload = res.data?.applyHumanitarianVolunteer;
      if (!payload?.success) {
        if (payload?.error === 'country_kyc_required') {
          Alert.alert(
            'Verifica tu identidad',
            `Para ser voluntario en ${country.name}, primero confirma tu identidad con Didit. Así nos aseguramos de que la ayuda llegue a personas reales.`,
            [
              { text: 'Ahora no', style: 'cancel' },
              { text: 'Verificar ahora', onPress: () => navigation.navigate('Verification') },
            ],
          );
        } else {
          Alert.alert('No se pudo enviar', payload?.error || 'Intenta de nuevo.');
        }
        return;
      }
      await refetchApplication();
      Alert.alert('Solicitud enviada', 'El equipo revisará tu solicitud antes de liberar fondos.');
    } catch (e: any) {
      Alert.alert('No se pudo enviar', e?.message || 'Intenta de nuevo.');
    }
  };

  const executeDonation = async () => {
    try {
      const bioOk = await biometricAuthService.authenticate(
        'Autoriza esta donación humanitaria',
        false,
        false
      );
      if (!bioOk) {
        Alert.alert('Se requiere biometría', Platform.OS === 'ios' ? 'Confirma con Face ID o Touch ID para continuar.' : 'Confirma con tu huella digital para continuar.');
        return;
      }

      setDonating(true);
      const session = new HumanitarianWsSession();
      await session.open();
      const pack = await session.prepareDonation(campaignSlug, parsedDonationAmount.toFixed(2));
      const donationId = pack?.donation_id || pack?.donationId;
      if (!donationId) throw new Error('donation_id_missing');
      const txns = Array.isArray(pack?.transactions) ? pack.transactions : [];
      const sponsorTxns = (pack?.sponsor_transactions || []).slice();
      const userToSign = txns.find((txn: any) => txn?.index === 0 && (txn?.needs_signature || !txn?.signed));
      if (!userToSign) throw new Error('donation_missing_user_txn');
      const userBytes = Buffer.from(userToSign.transaction, 'base64');
      const signedUser = await algorandService.signTransactionBytes(userBytes);
      const signedUserB64 = Buffer.from(signedUser).toString('base64');
      await session.submitDonation(donationId, signedUserB64, sponsorTxns);
      session.close();
      setSelectedAmount(null);
      setCustomAmount('');
      await Promise.all([refetch(), refetchBalances()]);
      Alert.alert('Donación enviada', 'Gracias. Tu donación aparecerá en la lista pública de donaciones recientes.');
    } catch (e: any) {
      Alert.alert('No se pudo donar', e?.message || 'Intenta de nuevo.');
    } finally {
      setDonating(false);
    }
  };

  const onDonate = () => {
    if (parsedDonationAmount < 1) {
      Alert.alert('Monto mínimo', 'La donación mínima es 1 cUSD.');
      return;
    }
    if (exceedsBalance) {
      Alert.alert('Saldo insuficiente', 'No tienes suficiente cUSD para esta donación.');
      return;
    }
    Alert.alert(
      'Confirmar donación',
      `¿Donar ${parsedDonationAmount.toFixed(2)} cUSD a esta campaña de ayuda humanitaria?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        { text: 'Donar', onPress: executeDonation },
      ],
    );
  };

  const onTopUp = () => {
    navigation.navigate('TopUp');
  };

  const goBack = () => {
    if (navigation.canGoBack()) {
      navigation.goBack();
      return;
    }
    navigation.navigate('BottomTabs', { screen: 'Home' });
  };

  const renderBackButton = (light?: boolean) => (
    <TouchableOpacity
      style={[styles.backButton, light && styles.backButtonLight]}
      onPress={goBack}
      activeOpacity={0.85}
      accessibilityRole="button"
      accessibilityLabel="Volver"
    >
      <Icon name="arrow-left" size={20} color={light ? '#FFFFFF' : colors.textFlat} />
    </TouchableOpacity>
  );

  if (loading && !campaign) {
    return (
      <View style={styles.container}>
        <View style={styles.loadingContent}>
          <View style={styles.topBar}>{renderBackButton()}</View>
          <View style={styles.loadingBody}>
            <ActivityIndicator color={colors.primary} />
          </View>
        </View>
      </View>
    );
  }

  if (error || !campaign) {
    return (
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.centerContent}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refetch} />}
      >
        <View style={styles.emptyTopBar}>{renderBackButton()}</View>
        <Text style={styles.emptyFlag}>{country.flag}</Text>
        <Text style={styles.emptyTitle}>Ayuda humanitaria</Text>
        <Text style={styles.emptyText}>Todavía no hay una campaña activa.</Text>
      </ScrollView>
    );
  }

  const application = myApplicationData?.myHumanitarianVolunteerApplication;
  const donations = campaign.donations || [];
  const donateLabel = donating
    ? 'Donando...'
    : parsedDonationAmount > 0
      ? `Donar ${parsedDonationAmount.toFixed(2)} cUSD`
      : 'Donar cUSD';

  return (
    <View style={styles.container}>
      <SafeAreaView edges={['top']} style={styles.safeTop} />
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refetch} tintColor={colors.primary} />}
      >
      {/* Hero with warm emerald gradient */}
      <View
        style={styles.hero}
        onLayout={(e) => {
          const { width, height } = e.nativeEvent.layout;
          setHeroSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
        }}
      >
        {heroSize.width > 0 && heroSize.height > 0 && (
          <Svg style={StyleSheet.absoluteFill} width={heroSize.width} height={heroSize.height}>
            <Defs>
              <SvgLinearGradient id="heroGrad" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0%" stopColor="#34D399" stopOpacity="1" />
                <Stop offset="100%" stopColor="#059669" stopOpacity="1" />
              </SvgLinearGradient>
            </Defs>
            <Rect x="0" y="0" width={heroSize.width} height={heroSize.height} fill="url(#heroGrad)" />
          </Svg>
        )}

        <View style={styles.heroTopBar}>{renderBackButton(true)}</View>

        <View style={styles.heroBody}>
          <View style={styles.kickerRow}>
            <Text style={styles.heroFlag}>{country.flag}</Text>
            <Text style={styles.kicker}>CONFÍO · AYUDA HUMANITARIA</Text>
          </View>
          <Text style={styles.title}>{campaign.title || 'Ayuda humanitaria directa'}</Text>
          <Text style={styles.description}>
            {campaign.description ||
              'Tu donación llega completa. Voluntarios verificados compran y entregan ayuda local — cada entrega queda publicada con monto y prueba.'}
          </Text>

          {/* Progress toward goal */}
          {goal > 0 && (
            <View style={styles.progressBlock}>
              <View style={styles.progressTopRow}>
                <Text style={styles.progressDonated}>{formatCompact(donated)}</Text>
                <Text style={styles.progressGoal}>de {formatCompact(goal)} meta</Text>
              </View>
              <View style={styles.progressTrack}>
                <View style={[styles.progressFill, goalReached && styles.progressFillDone, { width: `${fillWidth}%` }]} />
              </View>
              <View style={styles.progressBottomRow}>
                {goalReached ? (
                  <View style={styles.metaBadge}>
                    <Text style={styles.metaBadgeText}>🎉 ¡Meta superada! {displayProgress}%</Text>
                  </View>
                ) : (
                  <Text style={styles.progressMeta}>{displayProgress}% recaudado</Text>
                )}
                <Text style={styles.progressMeta}>{campaign.donationCount} donantes ❤</Text>
              </View>
              {goalReached && (
                <Text style={styles.progressOver}>
                  Gracias por superar la meta — cada donación extra ayuda a más familias.
                </Text>
              )}
            </View>
          )}
        </View>
      </View>

      <View style={styles.body}>
      {/* Quick-pick donate */}
      <View style={styles.donateCard}>
        <Text style={styles.donateLabel}>Elige un monto para donar</Text>
        <View style={styles.amountGrid}>
          {SUGGESTED_AMOUNTS.map((amt) => {
            const active = selectedAmount === amt;
            return (
              <TouchableOpacity
                key={amt}
                style={[styles.amountChip, active && styles.amountChipActive]}
                onPress={() => {
                  setSelectedAmount(active ? null : amt);
                  setCustomAmount('');
                }}
                activeOpacity={0.85}
              >
                <Text style={[styles.amountChipText, active && styles.amountChipTextActive]}>{amt} cUSD</Text>
              </TouchableOpacity>
            );
          })}
        </View>
        <View style={styles.customAmountRow}>
          <TextInput
            value={customAmount}
            onChangeText={(value) => {
              setCustomAmount(value);
              setSelectedAmount(null);
            }}
            placeholder="Otro monto"
            keyboardType="numeric"
            style={styles.customAmountInput}
            placeholderTextColor="#94A3B8"
          />
          <Text style={styles.customAmountSuffix}>cUSD</Text>
        </View>
        <Text style={[styles.balanceHint, exceedsBalance && styles.balanceError]}>
          Saldo disponible: {balancesLoading ? 'Cargando...' : `${availableCusd.toFixed(2)} cUSD`} · Mínimo: 1 cUSD
        </Text>
        <TouchableOpacity
          style={[styles.donateButton, !canDonate && styles.donateButtonDisabled]}
          onPress={onDonate}
          activeOpacity={0.9}
          disabled={!canDonate}
        >
          <Icon name="heart" size={17} color="#FFFFFF" />
          <Text style={styles.donateButtonText}>{donateLabel}</Text>
        </TouchableOpacity>
        <View style={styles.trustRow}>
          <Icon name="shield" size={13} color={colors.primaryDark} />
          <Text style={styles.trustText}>100% directo · sin comisiones · prueba pública</Text>
        </View>
        {!!campaign.vaultAddress && (
          <TouchableOpacity
            style={styles.publicAccountLink}
            onPress={() => openAddress(campaign.vaultAddress)}
            activeOpacity={0.85}
          >
            <Icon name="external-link" size={14} color={colors.primaryDark} />
            <Text style={styles.publicAccountText}>Ver cuenta pública de ayuda</Text>
          </TouchableOpacity>
        )}
      </View>

      <View style={styles.statsGrid}>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Recaudado</Text>
          <Text style={styles.statValue}>{formatAmount(campaign.totalDonated)}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Entregado</Text>
          <Text style={styles.statValue}>{formatAmount(campaign.totalReleased)}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Donantes</Text>
          <Text style={styles.statValue}>{campaign.donationCount}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Pruebas</Text>
          <Text style={styles.statValue}>{proofCount}</Text>
        </View>
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Entregas con prueba</Text>
          {campaign.releaseCount > 0 && (
            <View style={styles.countPill}>
              <Text style={styles.countPillText}>{campaign.releaseCount}</Text>
            </View>
          )}
        </View>
        <Text style={styles.sectionHint}>Cada compra y entrega queda registrada con prueba pública.</Text>
        {(campaign.releases || []).map((release: any) => {
          const published = normalizeStatus(release.status) === 'proof_published';
          const c = avatarColor(release.volunteerName);
          return (
            <View key={release.publicId} style={styles.releaseCard}>
              <View style={styles.releaseHeader}>
                <View style={[styles.avatar, { backgroundColor: c.bg }]}>
                  <Text style={[styles.avatarText, { color: c.fg }]}>{initials(release.volunteerName)}</Text>
                </View>
                <View style={styles.releaseHeaderInfo}>
                  <Text style={styles.releaseVolunteer} numberOfLines={1}>{release.volunteerName}</Text>
                  {!!release.releasedAt && <Text style={styles.timeText}>{timeAgo(release.releasedAt)}</Text>}
                </View>
                <View style={styles.amountPill}>
                  <Text style={styles.amountPillText}>{formatAmount(release.amount)}</Text>
                </View>
              </View>
              <Text style={styles.releasePurpose}>{release.purpose}</Text>
              {!!release.publicNote && <Text style={styles.note}>{release.publicNote}</Text>}
              <View style={styles.chipRow}>
                <View style={[styles.statusBadge, published ? styles.statusBadgeDone : styles.statusBadgePending]}>
                  <Icon
                    name={published ? 'check-circle' : 'clock'}
                    size={12}
                    color={published ? colors.successText : colors.textSecondary}
                  />
                  <Text style={[styles.statusText, published ? styles.statusTextDone : styles.statusTextPending]}>
                    {published ? 'prueba publicada' : 'prueba en camino'}
                  </Text>
                </View>
                {(release.proofLinks || []).map((proof: any) => (
                  <TouchableOpacity
                    key={`${release.publicId}-${proof.url}`}
                    style={styles.chip}
                    onPress={() => Linking.openURL(proof.url)}
                    activeOpacity={0.85}
                  >
                    <Icon name="external-link" size={12} color={colors.primaryDark} />
                    <Text style={styles.chipText}>{proof.title || proof.platform || 'Ver prueba'}</Text>
                  </TouchableOpacity>
                ))}
                {!!release.transactionHash && (
                  <TouchableOpacity
                    style={styles.chip}
                    onPress={() => openTransaction(release.transactionHash)}
                    activeOpacity={0.85}
                  >
                    <Icon name="link" size={12} color={colors.primaryDark} />
                    <Text style={styles.chipText}>{shortHash(release.transactionHash)}</Text>
                  </TouchableOpacity>
                )}
              </View>
            </View>
          );
        })}
        {(!campaign.releases || campaign.releases.length === 0) && (
          <View style={styles.emptyCard}>
            <Icon name="package" size={22} color={colors.primaryDark} />
            <Text style={styles.emptyCardText}>Las primeras entregas aparecerán aquí con monto, voluntario y prueba pública.</Text>
          </View>
        )}
      </View>

      <View style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Gracias a quienes ya ayudaron</Text>
          {campaign.donationCount > 0 && (
            <View style={styles.countPill}>
              <Text style={styles.countPillText}>{campaign.donationCount}</Text>
            </View>
          )}
        </View>
        <Text style={styles.sectionHint}>Cada donación llega completa a la zona afectada. ❤</Text>
        {donations.map((donation: any) => {
          const name = donation.donorDisplayName || 'Donante Confío';
          const c = avatarColor(name);
          return (
            <View key={donation.publicId} style={styles.donorRow}>
              <View style={[styles.avatar, { backgroundColor: c.bg }]}>
                <Text style={[styles.avatarText, { color: c.fg }]}>{initials(donation.donorDisplayName)}</Text>
              </View>
              <View style={styles.donorInfo}>
                <Text style={styles.donorName} numberOfLines={1}>{name}</Text>
                <View style={styles.donorMetaRow}>
                  {!!donation.donatedAt && <Text style={styles.timeText}>{timeAgo(donation.donatedAt)}</Text>}
                  {!!donation.donatedAt && !!donation.transactionHash && <Text style={styles.dot}>·</Text>}
                  {!!donation.transactionHash && (
                    <TouchableOpacity onPress={() => openTransaction(donation.transactionHash)} activeOpacity={0.85}>
                      <Text style={styles.donorTxText}>Ver transacción</Text>
                    </TouchableOpacity>
                  )}
                </View>
              </View>
              <View style={styles.amountPill}>
                <Text style={styles.amountPillText}>{formatAmount(donation.amount)}</Text>
              </View>
            </View>
          );
        })}
        {donations.length === 0 && (
          <View style={styles.emptyCard}>
            <Icon name="heart" size={22} color={colors.primaryDark} />
            <Text style={styles.emptyCardText}>Sé la primera persona en donar y abrir el camino para más ayuda.</Text>
          </View>
        )}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>{volunteerSectionTitle}</Text>
        <Text style={styles.sectionSubtitle}>{volunteerSectionSubtitle}</Text>
        {application ? (
          <View style={styles.applicationCard}>
            <Icon name="user-check" size={18} color={colors.primaryDark} />
            <Text style={styles.applicationText}>Tu solicitud está en estado: {application.status}</Text>
          </View>
        ) : (
          <>
            <TextInput
              value={serviceArea}
              onChangeText={setServiceArea}
              placeholder={volunteerServiceAreaPlaceholder}
              style={styles.input}
              placeholderTextColor="#94A3B8"
            />
            <TextInput
              value={notes}
              onChangeText={setNotes}
              placeholder={volunteerNotesPlaceholder}
              style={[styles.input, styles.textArea]}
              multiline
              placeholderTextColor="#94A3B8"
            />
            <TouchableOpacity style={styles.primaryButton} onPress={onApply} disabled={applying}>
              {applying ? <ActivityIndicator color="#FFFFFF" /> : <Text style={styles.primaryButtonText}>{volunteerCtaLabel}</Text>}
            </TouchableOpacity>
          </>
        )}
      </View>
      </View>
      </ScrollView>
    </View>
  );
};

const softShadow = {
  shadowColor: '#0F172A',
  shadowOffset: { width: 0, height: 4 },
  shadowOpacity: 0.08,
  shadowRadius: 12,
  elevation: 3,
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.neutral },
  safeTop: { backgroundColor: '#34D399' },
  scroll: { flex: 1, backgroundColor: colors.neutral },
  content: { paddingBottom: 36 },
  body: { paddingHorizontal: 16 },
  loadingContent: { flex: 1, padding: 16 },
  loadingBody: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  centerContent: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  topBar: { width: '100%', alignItems: 'flex-start', marginBottom: 8 },
  emptyTopBar: { position: 'absolute', top: 16, left: 16 },
  backButton: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, alignItems: 'center', justifyContent: 'center' },
  backButtonLight: { backgroundColor: 'rgba(255,255,255,0.18)', borderColor: 'rgba(255,255,255,0.28)' },

  hero: { backgroundColor: '#34D399', borderBottomLeftRadius: 28, borderBottomRightRadius: 28, overflow: 'hidden', paddingHorizontal: 20, paddingTop: 8, paddingBottom: 30 },
  heroTopBar: { alignItems: 'flex-start', marginBottom: 12 },
  heroBody: {},
  kickerRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 10 },
  heroFlag: { fontSize: 22 },
  kicker: { fontSize: 12, fontWeight: '700', letterSpacing: 0.4, color: 'rgba(255,255,255,0.9)' },
  title: { fontSize: 26, lineHeight: 32, fontWeight: '800', color: '#FFFFFF', marginBottom: 8 },
  description: { fontSize: 14, lineHeight: 21, color: 'rgba(255,255,255,0.9)' },

  progressBlock: { marginTop: 20 },
  progressTopRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 },
  progressDonated: { fontSize: 22, fontWeight: '800', color: '#FFFFFF' },
  progressGoal: { fontSize: 13, color: 'rgba(255,255,255,0.85)' },
  progressTrack: { height: 10, borderRadius: 6, backgroundColor: 'rgba(255,255,255,0.25)', overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 6, backgroundColor: '#FFFFFF' },
  progressFillDone: { backgroundColor: '#FCD34D' },
  progressBottomRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 },
  progressMeta: { fontSize: 12, color: 'rgba(255,255,255,0.85)' },
  metaBadge: { backgroundColor: 'rgba(255,255,255,0.22)', borderRadius: 20, paddingHorizontal: 10, paddingVertical: 4 },
  metaBadgeText: { fontSize: 12, fontWeight: '800', color: '#FFFFFF' },
  progressOver: { marginTop: 8, fontSize: 12, lineHeight: 17, color: 'rgba(255,255,255,0.9)' },

  donateCard: { backgroundColor: colors.background, borderRadius: 16, padding: 16, marginTop: -16, marginBottom: 18, ...softShadow },
  donateLabel: { fontSize: 13, color: colors.textSecondary, marginBottom: 10 },
  amountGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 12 },
  amountChip: { width: '48%', borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingVertical: 12, alignItems: 'center' },
  amountChipActive: { borderWidth: 2, borderColor: colors.primaryDark, backgroundColor: colors.primarySoft },
  amountChipText: { fontSize: 15, fontWeight: '700', color: colors.textFlat },
  amountChipTextActive: { color: colors.primaryDark },
  customAmountRow: { height: 48, borderWidth: 1, borderColor: colors.borderMedium, borderRadius: 10, flexDirection: 'row', alignItems: 'center', backgroundColor: colors.neutral, marginBottom: 8 },
  customAmountInput: { flex: 1, paddingHorizontal: 12, fontSize: 16, fontWeight: '800', color: colors.textFlat },
  customAmountSuffix: { paddingHorizontal: 12, fontSize: 13, fontWeight: '800', color: colors.primaryDark },
  balanceHint: { fontSize: 12, color: colors.textSecondary, marginBottom: 12 },
  balanceError: { color: colors.danger },
  donateButton: { height: 50, borderRadius: 12, backgroundColor: colors.primaryDark, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 8 },
  donateButtonDisabled: { opacity: 0.5 },
  donateButtonText: { color: colors.white, fontSize: 16, fontWeight: '800' },
  trustRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 10 },
  trustText: { fontSize: 12, color: colors.textSecondary },
  publicAccountLink: { marginTop: 12, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  publicAccountText: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },

  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 18 },
  stat: { width: '48%', backgroundColor: colors.background, borderRadius: 12, padding: 14, ...softShadow },
  statLabel: { fontSize: 12, color: colors.textSecondary, marginBottom: 6 },
  statValue: { fontSize: 17, fontWeight: '800', color: colors.textFlat },

  section: { marginTop: 18 },
  sectionTitle: { fontSize: 18, fontWeight: '800', color: colors.textFlat },
  sectionSubtitle: { fontSize: 14, lineHeight: 20, color: colors.textSecondary, marginTop: -4, marginBottom: 12 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  sectionHint: { fontSize: 13, lineHeight: 18, color: colors.textSecondary, marginTop: 2, marginBottom: 12 },
  countPill: { backgroundColor: colors.primarySoft, borderRadius: 12, paddingHorizontal: 8, paddingVertical: 2, minWidth: 24, alignItems: 'center' },
  countPillText: { fontSize: 12, fontWeight: '800', color: colors.primaryDark },

  releaseCard: { backgroundColor: colors.background, borderRadius: 14, padding: 14, marginBottom: 10, ...softShadow },
  releaseHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 },
  releaseHeaderInfo: { flex: 1 },
  releaseVolunteer: { fontSize: 15, fontWeight: '800', color: colors.textFlat },
  releasePurpose: { fontSize: 14, lineHeight: 20, color: colors.textFlat },
  amountPill: { backgroundColor: colors.primarySoft, borderRadius: 20, paddingHorizontal: 10, paddingVertical: 5 },
  amountPillText: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 12 },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: colors.neutral, borderRadius: 20, paddingHorizontal: 10, paddingVertical: 5, borderWidth: 1, borderColor: colors.border },
  chipText: { fontSize: 12, fontWeight: '700', color: colors.primaryDark },
  donorMetaRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 2 },
  dot: { fontSize: 12, color: colors.textSecondary },
  emptyCard: { backgroundColor: colors.background, borderRadius: 14, padding: 18, alignItems: 'center', gap: 10, ...softShadow },
  emptyCardText: { fontSize: 14, lineHeight: 20, color: colors.textSecondary, textAlign: 'center' },

  row: { backgroundColor: colors.background, borderRadius: 12, padding: 14, marginBottom: 10, ...softShadow },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, marginBottom: 6 },
  rowTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.textFlat },
  rowText: { fontSize: 14, lineHeight: 20, color: colors.textSecondary },
  note: { fontSize: 13, lineHeight: 19, color: colors.textSecondary, marginTop: 6 },
  amount: { fontSize: 14, fontWeight: '800', color: colors.primaryDark },
  metaRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, gap: 10 },
  statusBadge: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 9, paddingVertical: 4, borderRadius: 20 },
  statusBadgeDone: { backgroundColor: colors.successLight },
  statusBadgePending: { backgroundColor: colors.neutralDark },
  statusText: { fontSize: 12, fontWeight: '600' },
  statusTextDone: { color: colors.successText },
  statusTextPending: { color: colors.textSecondary },
  timeText: { fontSize: 12, color: colors.textSecondary },
  txLink: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 10 },
  txLinkText: { fontSize: 12, fontWeight: '700', color: colors.primaryDark },
  proofButton: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 },
  proofText: { fontSize: 13, fontWeight: '700', color: colors.primaryDark },

  donorRow: { flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: colors.background, borderRadius: 12, padding: 12, marginBottom: 8, ...softShadow },
  avatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.primaryLight, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontSize: 13, fontWeight: '800', color: colors.primaryDark },
  donorInfo: { flex: 1 },
  donorName: { fontSize: 14, fontWeight: '700', color: colors.textFlat },
  donorTxLink: { marginTop: 3, alignSelf: 'flex-start' },
  donorTxText: { fontSize: 12, fontWeight: '700', color: colors.primaryDark },

  applicationCard: { flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: colors.primarySoft, borderRadius: 12, borderWidth: 1, borderColor: colors.primaryMuted, padding: 14 },
  applicationText: { flex: 1, fontSize: 14, fontWeight: '600', color: colors.primaryDark, textTransform: 'capitalize' },

  emptyFlag: { fontSize: 30 },
  emptyTitle: { fontSize: 18, fontWeight: '800', color: colors.textFlat, marginTop: 12 },
  emptyText: { fontSize: 14, lineHeight: 20, color: colors.textSecondary },
  input: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.borderMedium, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 12, marginBottom: 10, fontSize: 15, color: colors.textFlat },
  textArea: { minHeight: 88, textAlignVertical: 'top' },
  primaryButton: { height: 48, borderRadius: 12, backgroundColor: colors.secondary, alignItems: 'center', justifyContent: 'center' },
  primaryButtonText: { color: colors.white, fontSize: 15, fontWeight: '800' },
});
