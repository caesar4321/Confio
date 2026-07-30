import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Platform, Image, Alert, ActivityIndicator } from 'react-native';
import { Buffer } from 'buffer';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useQuery, useApolloClient, gql } from '@apollo/client';
import { GET_PRESALE_CURVE_STATS, GET_ACTIVE_PRESALE, GET_PRESALE_STATUS, GET_MY_PRESALE_ONCHAIN_INFO } from '../apollo/queries';
import { PresaleWsSession } from '../services/presaleWs';
import algorandService from '../services/algorandService';
import { formatNumber } from '../utils/numberFormatting';
import { useCountry } from '../contexts/CountryContext';
import { LoadingOverlay } from '../components/LoadingOverlay';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { Header } from '../navigation/Header';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';

type ConfioPresaleScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ConfioPresaleScreen = () => {
  const navigation = useNavigation<ConfioPresaleScreenNavigationProp>();
  const { selectedCountry } = useCountry();
  const apollo = useApolloClient();
  // One continuous presale: moving curve price + recaudado milestones
  const { data, loading, error } = useQuery(GET_PRESALE_CURVE_STATS, {
    fetchPolicy: 'cache-and-network',
  });

  // Also fetch active presale to check if any phase is active
  const { data: activePresaleData } = useQuery(GET_ACTIVE_PRESALE, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: presaleStatusData } = useQuery(GET_PRESALE_STATUS, { fetchPolicy: 'cache-and-network' });
  const isClaimsUnlocked = presaleStatusData?.isPresaleClaimsUnlocked === true;
  const [busy, setBusy] = useState(false);
  const [claimNotice, setClaimNotice] = useState('');
  const { data: onchainInfoData, refetch: refetchOnchainInfo } = useQuery(GET_MY_PRESALE_ONCHAIN_INFO, { fetchPolicy: 'cache-and-network', skip: !isClaimsUnlocked });
  const claimable = onchainInfoData?.myPresaleOnchainInfo?.claimable || 0;

  // Use server data — the contract is the authority; nothing is hardcoded
  const curve = data?.presaleCurveStats;
  const currentPrice = curve ? parseFloat(curve.currentPrice) : 0;
  const startPrice = curve ? parseFloat(curve.startPrice) : 0;
  const finalPrice = curve ? parseFloat(curve.finalPrice) : 0;
  const totalRaised = curve ? parseFloat(curve.totalRaisedUsd) : 0;
  const nextMilestone = curve ? parseFloat(curve.nextMilestoneUsd) : 0;
  const participants = curve?.participants || 0;
  const milestoneProgress = nextMilestone > 0 ? Math.min((totalRaised / nextMilestone) * 100, 100) : 0;

  const countryCode = selectedCountry?.[2] || 'VE';
  // Early on the curve moves in the 4th decimal — users must SEE it move.
  const formatPrice = (value: number) =>
    formatNumber(value, countryCode, value < 1
      ? { minimumFractionDigits: 4, maximumFractionDigits: 4 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const formatMilestone = (value: number) => {
    if (value >= 1000000) {
      const millions = value / 1000000;
      return `$${formatNumber(millions, countryCode, { maximumFractionDigits: 1 })} ${millions === 1 ? 'millón' : 'millones'}`;
    }
    return `$${formatNumber(value / 1000, countryCode, { maximumFractionDigits: 0 })} mil`;
  };

  const checkEligibility = () => {
    const iso = selectedCountry?.[2];
    if (iso === 'US') {
      Alert.alert('Restricción', 'Lo sentimos, los residentes de Estados Unidos no pueden participar en la preventa.');
      return false;
    }
    if (iso === 'KR') {
      Alert.alert('Restricción', 'Lo sentimos, los ciudadanos/residentes de Corea del Sur no pueden participar en la preventa.');
      return false;
    }
    return true;
  };

  const handleJoinWaitlist = async () => {
    if (!checkEligibility()) return;

    try {
      const { data } = await apollo.mutate({
        mutation: gql`
          mutation JoinPresaleWaitlist {
            joinPresaleWaitlist {
              success
              message
              alreadyJoined
            }
          }
        `,
      });

      if (data?.joinPresaleWaitlist?.success) {
        Alert.alert(
          'Lista de Espera',
          data.joinPresaleWaitlist.message,
          [{ text: 'Entendido', style: 'default' }]
        );
      } else {
        // If server blocked it (double hardening), show the message
        Alert.alert(
          'Aviso',
          data?.joinPresaleWaitlist?.message || 'No se pudo unir a la lista de espera.',
          [{ text: 'Entendido', style: 'default' }]
        );
      }
    } catch (error: any) {
      Alert.alert(
        'Error',
        error.message || 'No se pudo unir a la lista de espera. Por favor intenta nuevamente.',
        [{ text: 'Entendido', style: 'default' }]
      );
    }
  };

  const handleClaim = async () => {
    try {
      // Guard: no claimable balance
      if (!isClaimsUnlocked || (claimable ?? 0) <= 0) {
        setClaimNotice('No tienes $CONFIO para reclamar');
        return;
      }
      setBusy(true);
      const session = new PresaleWsSession();
      await session.open();
      const pack = await session.claimPrepare();
      const txns = Array.isArray(pack?.transactions) ? pack.transactions : [];
      // Find user witness txn at index 0
      const userWitness = txns.find((t: any) => t?.index === 0 && (t?.needs_signature || !t?.signed));
      if (!userWitness) throw new Error('claim_missing_user_txn');
      const userBytes = Buffer.from(userWitness.transaction, 'base64');
      const signed = await algorandService.signTransactionBytes(userBytes);
      const signedB64 = Buffer.from(signed).toString('base64');
      const sponsors = pack?.sponsor_transactions || [];
      await session.claimSubmit(signedB64, sponsors);
      setBusy(false);
      // Keep success feedback minimal and clear
      Alert.alert('Reclamado');
      setClaimNotice('');
    } catch (e: any) {
      setBusy(false);
      // Do not show alert on error; log to console for debugging      // Show a helpful inline message if it's clearly a no-claimable case
      if ((claimable ?? 0) <= 0) setClaimNotice('No tienes $CONFIO para reclamar');
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation as any}
          title="Preventa $CONFIO"
          backgroundColor={colors.secondary}
          isLight
          showBackButton
        />
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.secondary} />
          <Text style={styles.loadingText}>Cargando preventa...</Text>
        </View>
      </View>
    );
  }

  if (error || !curve) {
    return (
      <View style={styles.container}>
        <Header
          navigation={navigation as any}
          title="Preventa $CONFIO"
          backgroundColor={colors.secondary}
          isLight
          showBackButton
        />
        <View style={styles.errorContainer}>
          <Icon name="alert-circle" size={48} color={colors.secondary} />
          <Text style={styles.errorText}>No se pudo cargar la preventa</Text>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.errorButton}>
            <Text style={styles.errorButtonText}>Volver</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Preventa $CONFIO"
        backgroundColor={colors.secondary}
        isLight
        showBackButton
      />

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        <LoadingOverlay visible={busy} message="Procesando reclamo..." />
        {/* Hero — violet brand field (referral-suite grammar) */}
        <View style={styles.heroSection}>
          <BrandFieldBackground id="presaleField" fromColor={colors.secondary} toColor={colors.secondaryDark} ringCy="22%" ringR={80} ringWidth={20} />
          <View style={styles.heroInner}>
          <View style={styles.tokenIcon}>
            <Image
              source={CONFIOLogo}
              style={styles.tokenImage}
              resizeMode="contain"
            />
          </View>
          {isClaimsUnlocked ? (
            <>
              <Text style={styles.heroTitle}>¡Tus $CONFIO ya están listos! 🎉</Text>
              <Text style={styles.heroSubtitle}>
                Hemos desbloqueado los tokens de la preventa. Si participaste, ya puedes reclamarlos sin pagar comisiones.
              </Text>
              <View style={[styles.comingSoonBadge, { backgroundColor: 'rgba(255,255,255,0.18)' }]}>
                <Text style={styles.comingSoonText}>🔓 Tokens desbloqueados</Text>
              </View>
              <View style={styles.claimInfoCard}>
                <Text style={styles.claimInfoTitle}>Listos para reclamar</Text>
                <Text style={styles.claimInfoAmount}>{formatNumber(claimable, (selectedCountry?.[2] || 'VE'), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $CONFIO</Text>
              </View>
            </>
          ) : (
            <>
              <Text style={styles.heroTitle}>Preventa Exclusiva de $CONFIO</Text>
              <Text style={styles.heroSubtitle}>
                Acceso temprano al ecosistema que estamos construyendo para nuestra gente
              </Text>
              <View style={styles.comingSoonBadge}>
                <Text style={styles.comingSoonText}>🚀 Acceso anticipado</Text>
              </View>
            </>
          )}
          </View>
        </View>

        {/* Vision & Claiming */}
        <View style={styles.benefitsSection}>
          {isClaimsUnlocked ? (
            <>
              <Text style={styles.sectionTitle}>¿Cómo reclamar tus $CONFIO?</Text>
              <View style={styles.benefitsList}>
                <View style={styles.benefitItem}>
                  <Icon name="unlock" size={24} color={colors.secondary} />
                  <View style={styles.benefitContent}>
                    <Text style={styles.benefitTitle}>1. Toca "Reclamar mis $CONFIO"</Text>
                    <Text style={styles.benefitDescription}>Te guiamos con un paso rápido y seguro.</Text>
                  </View>
                </View>
                <View style={styles.benefitItem}>
                  <Icon name="edit-2" size={24} color={colors.secondary} />
                  <View style={styles.benefitContent}>
                    <Text style={styles.benefitTitle}>2. Confirma tu reclamo</Text>
                    <Text style={styles.benefitDescription}>Sin costos ni pasos complicados. Nosotros nos encargamos en segundo plano.</Text>
                  </View>
                </View>
                <View style={styles.benefitItem}>
                  <Icon name="check-circle" size={24} color={colors.secondary} />
                  <View style={styles.benefitContent}>
                    <Text style={styles.benefitTitle}>3. Recibe tus monedas</Text>
                    <Text style={styles.benefitDescription}>En segundos verás tus $CONFIO en tu balance dentro de la app.</Text>
                  </View>
                </View>
              </View>
            </>
          ) : (
            <>
              <Text style={styles.sectionTitle}>El Futuro que Construimos Juntos</Text>
              <View style={styles.benefitsList}>
                <View style={styles.benefitItem}>
                  <Icon name="heart" size={24} color={colors.secondary} />
                  <View style={styles.benefitContent}>
                    <Text style={styles.benefitTitle}>Tu Dinero, Siempre Seguro</Text>
                    <Text style={styles.benefitDescription}>Una moneda digital que proteges tú mismo, sin bancos que te limiten o te cobren comisiones abusivas</Text>
                  </View>
                </View>
                <View style={styles.benefitItem}>
                  <Icon name="zap" size={24} color={colors.secondary} />
                  <View style={styles.benefitContent}>
                    <Text style={styles.benefitTitle}>Pagos en Segundos</Text>
                    <Text style={styles.benefitDescription}>Envía dinero a tu familia o cobra por tu trabajo al instante, sin esperas ni papeleos</Text>
                  </View>
                </View>
                <View style={styles.benefitItem}>
                  <Icon name="sunrise" size={24} color={colors.secondary} />
                  <View style={styles.benefitContent}>
                    <Text style={styles.benefitTitle}>Un Nuevo Amanecer Financiero</Text>
                    <Text style={styles.benefitDescription}>Crecemos paso a paso, país por país, construyendo la economía del futuro desde nuestras raíces</Text>
                  </View>
                </View>
              </View>
            </>
          )}
        </View>

        {/* Price curve — one continuous presale, hide once claims are unlocked */}
        {!isClaimsUnlocked && (
          <View style={styles.phasesSection}>
            <Text style={styles.sectionTitle}>¿Cómo funciona el precio?</Text>
            <View style={styles.curveCard}>
              <Text style={styles.curvePriceLabel}>Precio actual</Text>
              <Text style={styles.curvePriceValue}>{formatPrice(currentPrice)} cUSD</Text>
              <Text style={styles.curvePriceUnit}>por $CONFIO</Text>

              <Text style={styles.curveExplainer}>
                El precio sube automáticamente con cada compra. Sin fases ni fechas:
                el siguiente comprador siempre paga un poco más.
              </Text>

              <View style={styles.curveEndpoints}>
                <View style={styles.curveEndpoint}>
                  <Text style={styles.curveEndpointLabel}>Inicio</Text>
                  <Text style={styles.curveEndpointValue}>{formatPrice(startPrice)}</Text>
                </View>
                <Icon name="trending-up" size={18} color={colors.secondary} />
                <View style={styles.curveEndpoint}>
                  <Text style={styles.curveEndpointLabel}>Máximo</Text>
                  <Text style={styles.curveEndpointValue}>{formatPrice(finalPrice)}</Text>
                </View>
              </View>

              <View style={styles.milestoneBlock}>
                <View style={styles.milestoneRow}>
                  <Text style={styles.milestoneLabel}>Recaudado</Text>
                  <Text style={styles.milestoneValue}>
                    ${formatNumber(totalRaised, countryCode, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </Text>
                </View>
                <View style={styles.milestoneBar}>
                  <View style={[styles.milestoneFill, { width: `${milestoneProgress}%` }]} />
                </View>
                <View style={styles.milestoneRow}>
                  <Text style={styles.milestoneLabel}>Próximo hito</Text>
                  <Text style={styles.milestoneValue}>{formatMilestone(nextMilestone)}</Text>
                </View>
              </View>

              <View style={styles.participantsRow}>
                <Icon name="users" size={14} color={colors.secondary} />
                <Text style={styles.participantsText}>
                  {formatNumber(participants, countryCode, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} personas ya participaron
                </Text>
              </View>
            </View>
          </View>
        )}

        {/* CTA Section */}
        <View style={styles.ctaSection}>
          <Text style={styles.ctaTitle}>¿Listo para hacer historia?</Text>
          <Text style={styles.ctaSubtitle}>
            {isClaimsUnlocked ? 'Reclama las monedas que compraste en la preventa' : 'Únete temprano al ecosistema $CONFIO y sigue su desarrollo desde adentro'}
          </Text>

          {!isClaimsUnlocked && activePresaleData?.activePresalePhase ? (
            <Button
              title="Participar en la Preventa"
              loading={busy}
              onPress={async () => {
                if (!checkEligibility()) return;

                // Check presale eligibility via WebSocket (backup check, V1 migration, etc.)
                try {
                  setBusy(true);
                  const { PresaleWsSession } = await import('../services/presaleWs');
                  const session = new PresaleWsSession();
                  await session.open();
                  const pack = await session.optinPrepare();
                  setBusy(false);

                  // If no transactions, user is eligible - proceed with navigation
                  navigation.navigate('ConfioPresaleParticipate');
                } catch (e: any) {
                  setBusy(false);
                  // Server returned an error (e.g., backup check failure)
                  const errorMessage = e?.message || 'No se pudo verificar elegibilidad';
                  Alert.alert('No disponible', errorMessage);
                }
              }}
              icon={<Icon name="star" size={20} color={colors.white} />}
              style={{ backgroundColor: colors.secondary, borderRadius: 24, paddingHorizontal: 32, marginBottom: 16 }}
              textStyle={{ fontWeight: 'bold' }}
            />
          ) : (!isClaimsUnlocked ? (
            <Button
              title="Notificar"
              onPress={handleJoinWaitlist}
              icon={<Icon name="bell" size={20} color={colors.white} />}
              style={{ backgroundColor: colors.secondary, borderRadius: 24, paddingHorizontal: 32, marginBottom: 16 }}
              textStyle={{ fontWeight: 'bold' }}
            />
          ) : null)}

          {isClaimsUnlocked && (
            <Button
              title="Reclamar mis $CONFIO"
              onPress={async () => { await handleClaim(); refetchOnchainInfo && refetchOnchainInfo(); }}
              loading={busy}
              disabled={(claimable ?? 0) <= 0}
              icon={<Icon name="unlock" size={20} color={colors.white} />}
              style={{ borderRadius: 24, paddingHorizontal: 32, marginTop: 12, marginBottom: 16 }}
              textStyle={{ fontWeight: 'bold' }}
            />
          )}

          {isClaimsUnlocked && claimNotice ? (
            <Text style={styles.claimNoticeText}>{claimNotice}</Text>
          ) : null}

          {!isClaimsUnlocked && (
            <>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => navigation.navigate('ConfioTokenInfo')}
              >
                <Text style={styles.secondaryButtonText}>Ver el Futuro de $CONFIO</Text>
                <Icon name="arrow-right" size={16} color={colors.secondary} />
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.tokenomicsButton}
                onPress={() => navigation.navigate('ConfioTokenomics')}
              >
                <Icon name="pie-chart" size={16} color={colors.secondary} />
                <Text style={styles.tokenomicsButtonText}>Tokenomics Transparentes</Text>
              </TouchableOpacity>
            </>
          )}
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.white,
  },
  claimInfoCard: {
    marginTop: 16,
    backgroundColor: colors.primarySoft,
    borderColor: colors.primaryLight,
    borderWidth: 1,
    padding: 12,
    borderRadius: 12,
    alignItems: 'center',
  },
  claimInfoTitle: {
    fontSize: 12,
    color: '#065F46',
    marginBottom: 4,
  },
  claimInfoAmount: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#065F46',
  },
  scrollView: {
    flex: 1,
  },
  heroSection: {
    backgroundColor: colors.secondary,
    overflow: 'hidden',
  },
  heroInner: {
    alignItems: 'center',
    paddingVertical: 32,
    paddingHorizontal: 20,
  },
  tokenIcon: {
    width: 80,
    height: 80,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  tokenImage: {
    width: 80,
    height: 80,
  },
  heroTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.white,
    marginBottom: 8,
    textAlign: 'center',
  },
  heroSubtitle: {
    fontSize: 16,
    color: 'rgba(255,255,255,0.85)',
    textAlign: 'center',
    marginBottom: 16,
    lineHeight: 24,
  },
  comingSoonBadge: {
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  comingSoonText: {
    color: colors.white,
    fontSize: 14,
    fontWeight: 'bold',
  },
  benefitsSection: {
    paddingHorizontal: 20,
    paddingVertical: 32,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 20,
    textAlign: 'center',
  },
  benefitsList: {
    gap: 20,
  },
  benefitItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 16,
  },
  benefitContent: {
    flex: 1,
  },
  benefitTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 4,
  },
  benefitDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
  },
  phasesSection: {
    paddingHorizontal: 20,
    paddingBottom: 32,
  },
  phaseCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  curveCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
    alignItems: 'center',
  },
  curvePriceLabel: {
    fontSize: 13,
    color: colors.text.secondary,
    marginBottom: 4,
  },
  curvePriceValue: {
    fontSize: 32,
    fontWeight: 'bold',
    color: colors.secondary,
  },
  curvePriceUnit: {
    fontSize: 13,
    color: colors.text.light,
    marginBottom: 12,
  },
  curveExplainer: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 16,
  },
  curveEndpoints: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    alignSelf: 'stretch',
    paddingHorizontal: 24,
    marginBottom: 16,
  },
  curveEndpoint: {
    alignItems: 'center',
  },
  curveEndpointLabel: {
    fontSize: 12,
    color: colors.text.light,
    marginBottom: 2,
  },
  curveEndpointValue: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
  },
  milestoneBlock: {
    alignSelf: 'stretch',
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  milestoneRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  milestoneLabel: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  milestoneValue: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text.primary,
  },
  milestoneBar: {
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.border,
    overflow: 'hidden',
    marginVertical: 8,
  },
  milestoneFill: {
    height: '100%',
    borderRadius: 4,
    backgroundColor: colors.secondary,
  },
  participantsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  participantsText: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  phaseHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  phaseInfo: {
    flex: 1,
  },
  phaseNumber: {
    fontSize: 12,
    color: colors.secondary,
    fontWeight: 'bold',
    marginBottom: 2,
  },
  phaseTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
  },
  statusBadge: {
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statusText: {
    color: colors.white,
    fontSize: 12,
    fontWeight: 'bold',
  },
  phaseDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: 16,
    lineHeight: 20,
  },
  phaseDetails: {
    flexDirection: 'row',
    gap: 20,
    marginBottom: 16,
  },
  priceInfo: {
    flex: 1,
  },
  priceLabel: {
    fontSize: 12,
    color: colors.text.light,
    marginBottom: 4,
  },
  priceValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.secondary,
  },
  priceUnit: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 2,
  },
  goalInfo: {
    flex: 1,
  },
  goalLabel: {
    fontSize: 12,
    color: colors.text.light,
    marginBottom: 4,
  },
  goalValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.primary,
  },
  targetInfo: {
    flex: 1.5,
  },
  targetLabel: {
    fontSize: 12,
    color: colors.text.light,
    marginBottom: 4,
  },
  targetValue: {
    fontSize: 14,
    fontWeight: 'bold',
    color: colors.dark,
  },
  locationContainer: {
    alignItems: 'center',
    marginBottom: 16,
  },
  locationText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.secondary,
    backgroundColor: colors.violetLight,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  visionTags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  visionTag: {
    backgroundColor: colors.neutralDark,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.secondary,
  },
  visionTagText: {
    fontSize: 12,
    color: colors.secondary,
    fontWeight: '500',
  },
  ctaSection: {
    paddingHorizontal: 20,
    paddingVertical: 32,
    alignItems: 'center',
    backgroundColor: colors.neutralDark,
  },
  ctaTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 8,
    textAlign: 'center',
  },
  ctaSubtitle: {
    fontSize: 16,
    color: colors.text.secondary,
    marginBottom: 24,
    textAlign: 'center',
    lineHeight: 24,
  },
  claimNoticeText: {
    marginTop: 8,
    color: colors.error.icon,
    fontSize: 14,
    textAlign: 'center',
  },
  secondaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 12,
  },
  secondaryButtonText: {
    fontSize: 16,
    color: colors.secondary,
    fontWeight: '600',
  },
  tokenomicsButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderWidth: 1,
    borderColor: colors.secondary,
    borderRadius: 20,
    marginTop: 12,
  },
  tokenomicsButtonText: {
    fontSize: 14,
    color: colors.secondary,
    fontWeight: '600',
  },
  bottomPadding: {
    height: 40,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  loadingText: {
    marginTop: 16,
    fontSize: 16,
    color: colors.text.secondary,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    marginTop: 16,
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
    marginBottom: 24,
  },
  errorButton: {
    backgroundColor: colors.secondary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 20,
  },
  errorButtonText: {
    color: colors.white,
    fontSize: 16,
    fontWeight: 'bold',
  },
});
