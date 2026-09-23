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
import { useAccount } from '../contexts/AccountContext';
import { LoadingOverlay } from '../components/LoadingOverlay';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { Header } from '../navigation/Header';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';
import { CONFIO_DOCUMENTS, TrustPillars, openConfioDocument } from '../components/ConfioNarrative';

type ConfioPresaleScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ConfioPresaleScreen = () => {
  const navigation = useNavigation<ConfioPresaleScreenNavigationProp>();
  const { selectedCountry } = useCountry();
  const { activeAccount } = useAccount();
  // The server prepares purchases for personal accounts only
  // (personal_account_required), so business owners and employees get the
  // switch instruction here instead of a flow that fails at the last step.
  const isPersonalAccount = (activeAccount?.type || '').toLowerCase() === 'personal';
  const apollo = useApolloClient();
  // One continuous presale: moving curve price + recaudado milestones
  const { data, loading, error } = useQuery(GET_PRESALE_CURVE_STATS, {
    fetchPolicy: 'cache-and-network',
  });

  // activePresalePhase is a legacy field name: it gates purchase availability, not price rounds.
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
  // Which chain settles a purchase. Drives whether the Algorand opt-in
  // pre-flight runs at all (it does not exist on BSC).
  const isBscFlow = data?.presaleChain === 'bsc';
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

  // Where the live price sits between the curve's endpoints. Floor at 2% so
  // the marker never disappears into the bar's rounded start.
  const curvePosition = finalPrice > startPrice
    ? Math.min(Math.max((currentPrice - startPrice) / (finalPrice - startPrice), 0.02), 1)
    : 0.02;

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
                Desbloqueamos los tokens de la preventa. Si participaste, ya puedes reclamarlos.
              </Text>
              <View style={styles.heroBadge}>
                <Text style={styles.heroBadgeText}>🔓 Tokens desbloqueados</Text>
              </View>
              <View style={styles.claimInfoCard}>
                <Text style={styles.claimInfoTitle}>Listos para reclamar</Text>
                <Text style={styles.claimInfoAmount}>{formatNumber(claimable, (selectedCountry?.[2] || 'VE'), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $CONFIO</Text>
              </View>
            </>
          ) : (
            <>
              <Text style={styles.heroTitle}>Sé parte de Confío desde el principio</Text>
              <Text style={styles.heroSubtitle}>
                $CONFIO es la moneda de la comunidad que está construyendo Confío.
              </Text>
              <View style={styles.heroBadge}>
                <Text style={styles.heroBadgeText}>
                  {activePresaleData?.activePresalePhase
                    ? `Preventa abierta · $${formatPrice(currentPrice)}`
                    : 'Acceso anticipado'}
                </Text>
              </View>
            </>
          )}
          </View>
        </View>

        {isClaimsUnlocked && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>¿Cómo reclamar tus $CONFIO?</Text>
            <View style={styles.stepsList}>
              {[
                { icon: 'unlock', title: '1. Toca "Reclamar mis $CONFIO"', text: 'Verás la cantidad asignada a tu billetera.' },
                { icon: 'edit-2', title: '2. Confirma tu reclamo', text: 'Autorizas la transacción desde tu billetera.' },
                { icon: 'check-circle', title: '3. Recibe tus monedas', text: 'Tu balance se actualiza cuando la red confirma la transacción.' },
              ].map(step => (
                <View key={step.title} style={styles.stepItem}>
                  <Icon name={step.icon} size={24} color={colors.secondary} />
                  <View style={styles.stepContent}>
                    <Text style={styles.stepTitle}>{step.title}</Text>
                    <Text style={styles.stepText}>{step.text}</Text>
                  </View>
                </View>
              ))}
            </View>
          </View>
        )}

        {/* Why Confío — the name is the thesis */}
        <View style={styles.section}>
          <Text style={styles.eyebrow}>¿Por qué se llama Confío?</Text>
          <Text style={styles.manifestoTitle}>La confianza ya existe.</Text>
          <Text style={styles.manifestoLine}>
            Está en quien siempre paga. En el cliente que vuelve. En la familia que se ayuda.
          </Text>
          <Text style={styles.manifestoLine}>
            Pero hoy vive encerrada en un banco, en una plataforma o en un país.
          </Text>
          <Text style={styles.manifestoEmphasis}>
            Confío no quiere crearla desde cero. Quiere que se mueva contigo.
          </Text>
          <View style={styles.pillarsCard}>
            <TrustPillars variant="compact" />
          </View>
          <TouchableOpacity
            style={styles.inlineLink}
            onPress={() => navigation.navigate('ConfioTokenInfo')}
          >
            <Text style={styles.inlineLinkText}>Conocer la visión completa</Text>
            <Icon name="arrow-right" size={16} color={colors.secondary} />
          </TouchableOpacity>
        </View>

        {/* What $CONFIO is — and is not */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>¿Qué es $CONFIO?</Text>
          <View style={styles.isCard}>
            {[
              'La moneda de la comunidad Confío',
              'Recompensas por invitar y usar Confío',
              'Utilidades futuras, cuando se publiquen',
            ].map(item => (
              <View key={item} style={styles.isRow}>
                <View style={[styles.isIcon, styles.isIconYes]}>
                  <Icon name="check" size={14} color={colors.primaryDark} />
                </View>
                <Text style={styles.isText}>{item}</Text>
              </View>
            ))}
            <View style={styles.isDivider} />
            <Text style={styles.isNotLabel}>No es</Text>
            {[
              'Acciones ni participación en la empresa',
              'El respaldo de tus dólares en Confío',
              'Una promesa de ganancia o de liquidez',
            ].map(item => (
              <View key={item} style={styles.isRow}>
                <View style={[styles.isIcon, styles.isIconNo]}>
                  <Icon name="x" size={14} color={colors.text.secondary} />
                </View>
                <Text style={styles.isText}>{item}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* Price curve — one continuous presale, hide once claims are unlocked */}
        {!isClaimsUnlocked && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Un precio que nadie decide a mano</Text>
            <View style={styles.curveCard}>
              <Text style={styles.curvePriceLabel}>Precio actual</Text>
              <Text style={styles.curvePriceValue}>${formatPrice(currentPrice)}</Text>
              <Text style={styles.curvePriceUnit}>por $CONFIO</Text>

              <View style={styles.curveTrack}>
                <View style={[styles.curveTrackFill, { width: `${curvePosition * 100}%` }]} />
                <View style={[styles.curveMarker, { left: `${curvePosition * 100}%` }]} />
              </View>
              <View style={styles.curveEndpoints}>
                <Text style={styles.curveEndpointValue}>${formatPrice(startPrice)}</Text>
                <Text style={styles.curveEndpointValue}>${formatPrice(finalPrice)}</Text>
              </View>

              <Text style={styles.curveExplainer}>
                Un contrato público en BNB Smart Chain calcula el precio según lo vendido.
                Sin rondas ni cambios manuales: cada compra lo hace avanzar.
              </Text>

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

              <TouchableOpacity
                accessibilityRole="link"
                style={styles.contractLink}
                onPress={() => openConfioDocument(CONFIO_DOCUMENTS.presaleVault)}
              >
                <Icon name="shield" size={14} color={colors.secondary} />
                <Text style={styles.contractLinkText}>Ver el contrato en blockchain</Text>
                <Icon name="external-link" size={14} color={colors.secondary} />
              </TouchableOpacity>
            </View>
            <Text style={styles.footnote}>
              74 millones de $CONFIO en preventa. ${formatPrice(finalPrice)} es el final de la curva, no un precio de mercado garantizado.
            </Text>
          </View>
        )}

        {/* When do I get my tokens */}
        {!isClaimsUnlocked && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>¿Cuándo recibo mis $CONFIO?</Text>
            <View style={styles.flowRow}>
              {[
                { icon: 'shopping-bag', label: 'Participas' },
                { icon: 'bookmark', label: 'Se registra tu asignación' },
                { icon: 'unlock', label: 'Reclamas al lanzar en DEX' },
              ].map((step, index, all) => (
                <React.Fragment key={step.label}>
                  <View style={styles.flowStep}>
                    <View style={styles.flowIcon}>
                      <Icon name={step.icon} size={20} color={colors.secondary} />
                    </View>
                    <Text style={styles.flowLabel}>{step.label}</Text>
                  </View>
                  {index < all.length - 1 && (
                    <Icon name="chevron-right" size={18} color={colors.text.light} style={styles.flowArrow} />
                  )}
                </React.Fragment>
              ))}
            </View>
            <Text style={styles.footnote}>
              Tu asignación queda reservada para tu billetera en el contrato. Se podrá reclamar cuando se lance oficialmente en un DEX y se habilite el reclamo.
            </Text>
          </View>
        )}

        {/* CTA Section */}
        <View style={styles.ctaSection}>
          <Text style={styles.ctaTitle}>
            {isClaimsUnlocked ? 'Reclama tus $CONFIO' : 'Entra temprano a lo que ya estamos construyendo'}
          </Text>
          <Text style={styles.ctaSubtitle}>
            {isClaimsUnlocked
              ? 'Reclama las monedas que compraste en la preventa.'
              : 'No compras una promesa de ganancia. Te sumas desde el principio a una red de confianza para Latinoamérica.'}
          </Text>

          {!isClaimsUnlocked && activePresaleData?.activePresalePhase && !isPersonalAccount ? (
            <View style={styles.accountNotice}>
              <Icon name="user" size={18} color={colors.secondary} />
              <Text style={styles.accountNoticeText}>
                La preventa es solo para cuentas personales. Cambia a tu cuenta personal para participar.
              </Text>
            </View>
          ) : !isClaimsUnlocked && activePresaleData?.activePresalePhase ? (
            <Button
              title="Participar en la Preventa"
              loading={busy}
              onPress={() => {
                if (!checkEligibility()) return;
                // Navigate immediately. This button used to run the ENTIRE
                // Algorand opt-in pre-flight first (open a socket, and on the
                // server possibly send an MBR funding tx and wait for its
                // confirmation) — and then the destination screen ran the very
                // same ensureOptedIn again. That double round trip is the wait
                // users feel here; the destination owns it, with a real
                // spinner and the same error alert. On BSC there is nothing to
                // opt into at all, so the wait is pure waste.
                navigation.navigate('ConfioPresaleParticipate');
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
                style={styles.tokenomicsButton}
                onPress={() => navigation.navigate('ConfioTokenomics')}
              >
                <Icon name="pie-chart" size={16} color={colors.secondary} />
                <Text style={styles.tokenomicsButtonText}>Distribución, reglas y riesgos</Text>
              </TouchableOpacity>
              <Text style={styles.ctaFinePrint}>
                Puedes perder parte o todo lo que aportes. No disponible para residentes de EE. UU. ni para ciudadanos o residentes de Corea del Sur.
              </Text>
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
    fontSize: 26,
    fontWeight: 'bold',
    color: colors.white,
    marginBottom: 8,
    textAlign: 'center',
    lineHeight: 32,
  },
  heroSubtitle: {
    fontSize: 16,
    color: 'rgba(255,255,255,0.85)',
    textAlign: 'center',
    marginBottom: 16,
    lineHeight: 24,
  },
  heroBadge: {
    backgroundColor: 'rgba(255,255,255,0.18)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.3)',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  heroBadgeText: {
    textAlign: 'center',
    color: colors.white,
    fontSize: 14,
    fontWeight: 'bold',
  },
  section: {
    paddingHorizontal: 20,
    paddingTop: 32,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 16,
    textAlign: 'center',
  },
  stepsList: {
    gap: 20,
  },
  stepItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 16,
  },
  stepContent: {
    flex: 1,
  },
  stepTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 4,
  },
  stepText: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
  },
  eyebrow: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    textAlign: 'center',
    marginBottom: 8,
  },
  manifestoTitle: {
    fontSize: 26,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'center',
    marginBottom: 12,
  },
  manifestoLine: {
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 8,
  },
  manifestoEmphasis: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
    textAlign: 'center',
    lineHeight: 24,
    marginTop: 4,
    marginBottom: 20,
  },
  pillarsCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  inlineLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
  },
  inlineLinkText: {
    fontSize: 15,
    color: colors.secondary,
    fontWeight: '600',
  },
  isCard: {
    backgroundColor: colors.neutral,
    borderRadius: 16,
    padding: 20,
    gap: 12,
  },
  isRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  isIcon: {
    width: 24,
    height: 24,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  isIconYes: {
    backgroundColor: colors.primaryLight,
  },
  isIconNo: {
    backgroundColor: colors.neutralDark,
  },
  isText: {
    flex: 1,
    fontSize: 15,
    color: colors.dark,
    lineHeight: 21,
  },
  isDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: 4,
  },
  isNotLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  curveCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
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
    marginBottom: 20,
  },
  curveTrack: {
    alignSelf: 'stretch',
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.violetLight,
    justifyContent: 'center',
  },
  curveTrackFill: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    borderRadius: 4,
    backgroundColor: colors.secondary,
  },
  curveMarker: {
    position: 'absolute',
    width: 18,
    height: 18,
    marginLeft: -9,
    borderRadius: 9,
    backgroundColor: colors.white,
    borderWidth: 4,
    borderColor: colors.secondary,
  },
  curveEndpoints: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignSelf: 'stretch',
    marginTop: 10,
    marginBottom: 16,
  },
  curveEndpointValue: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  curveExplainer: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 16,
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
  contractLink: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 16,
    paddingVertical: 4,
  },
  contractLinkText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.secondary,
  },
  footnote: {
    fontSize: 12,
    color: colors.text.light,
    textAlign: 'center',
    lineHeight: 18,
    marginTop: 12,
    paddingHorizontal: 8,
  },
  flowRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  flowStep: {
    flex: 1,
    alignItems: 'center',
  },
  flowIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.violetLight,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  flowLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.dark,
    textAlign: 'center',
    lineHeight: 18,
  },
  flowArrow: {
    marginTop: 15,
  },
  ctaSection: {
    marginTop: 32,
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
  accountNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    alignSelf: 'stretch',
    backgroundColor: colors.violetLight,
    borderRadius: 12,
    padding: 14,
    marginBottom: 16,
  },
  accountNoticeText: {
    flex: 1,
    fontSize: 14,
    color: colors.dark,
    lineHeight: 20,
  },
  ctaFinePrint: {
    fontSize: 12,
    color: colors.text.light,
    textAlign: 'center',
    lineHeight: 18,
    marginTop: 16,
  },
  claimNoticeText: {
    marginTop: 8,
    color: colors.error.icon,
    fontSize: 14,
    textAlign: 'center',
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
