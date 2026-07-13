import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Linking,
  Image,
} from 'react-native';
import { Header } from '../navigation/Header';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { gql, useQuery } from '@apollo/client';
import { colors } from '../config/theme';
import { useCurrency } from '../hooks/useCurrency';
import { useNumberFormat } from '../utils/numberFormatting';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';
import { CUSD_RESERVE_PERA_URL } from '../config/algorand';
import cUSDLogo from '../assets/png/cUSD.png';
import cUSDPlusLogo from '../assets/png/cUSDPlus.png';
import OndoLogo from '../assets/png/Ondo.png';

// Live yield split (design law: no hardcoded rates in copy). Both sides are
// SERVER-derived from Ondo's on-chain oracle; when the rate isn't live yet
// (pre-launch honest 0%) the split falls back to example copy, labeled so.
const GET_APY_SPLIT = gql`
  query CusdPlusApySplit {
    cusdPlusSummary {
      grossApyPct
      netApyPct
    }
  }
`;

const formatWhole = (n: number | null | undefined, sep: string) => {
  if (n == null) return '—';
  const r = Math.round(n);
  try {
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
      .format(r)
      .replace(/,/g, sep);
  } catch {
    return `${r}`;
  }
};

export const ProtectedSavingsScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { data } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'cache-and-network',
    nextFetchPolicy: 'cache-first',
  });
  const s = data?.statsSummary;
  const tvl = s?.totalValueLocked ?? s?.protectedSavings;
  const tvlLabel = formatWhole(tvl, currency.thousandsSeparator);
  // statsSummary.usdyReserve is live (deployed 2026-07-04; 0 until the BSC
  // vault ships and the server folds its USDY balance in);
  // 0 is the honest present-tense value until the reserve exists.
  const usdyReserve = (s as any)?.usdyReserve ?? 0;
  const usdyLabel = formatWhole(usdyReserve, currency.thousandsSeparator);

  const { formatNumber } = useNumberFormat();
  const { data: apyData } = useQuery(GET_APY_SPLIT, {
    fetchPolicy: 'cache-and-network',
    nextFetchPolicy: 'cache-first',
  });
  const grossApy = apyData?.cusdPlusSummary?.grossApyPct ?? 0;
  const netApy = apyData?.cusdPlusSummary?.netApyPct ?? 0;
  const apyLive = grossApy > 0 && netApy > 0;
  const pct = (v: number) => `~${formatNumber(v, { maximumFractionDigits: 1 })}%`;

  const openUrl = (url?: string | null) => {
    if (!url) return;
    Linking.openURL(url).catch(() => {});
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Ahorros Protegidos"
        backgroundColor={colors.primary}
        isLight
        showBackButton
      />

      <ScrollView style={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* Hero */}
        <View style={styles.hero}>
          <View style={styles.heroLogoRow}>
            <Image source={cUSDLogo} style={styles.heroLogo} resizeMode="contain" />
            <Image
              source={cUSDPlusLogo}
              style={[styles.heroLogo, styles.heroLogoOverlap]}
              resizeMode="contain"
            />
          </View>
          <Text style={styles.heroTitle}>Confío Dollar y Confío Dollar+</Text>
          <Text style={styles.heroSubtitle}>
            Tus dólares digitales, 100% respaldados y verificables en blockchain.
          </Text>
          <View style={styles.heroPillsRow}>
            <View style={styles.heroStatPill}>
              <Icon name="shield" size={14} color={colors.primary} />
              <Text style={styles.heroStatText}>
                {tvlLabel} USDC en reserva
              </Text>
            </View>
            <View style={styles.heroStatPill}>
              <Icon name="trending-up" size={14} color={colors.primary} />
              <Text style={styles.heroStatText}>
                {usdyLabel} USDY en reserva
              </Text>
            </View>
          </View>
          <Text style={styles.heroFootnote}>
            cUSD: respaldado por USDC · cUSD+: respaldado por USDY (Tesoro EE.UU.)
          </Text>
        </View>

        {/* What is cUSD */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="help-circle" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>¿Qué son cUSD y cUSD+?</Text>
          </View>
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>Confío Dollar (cUSD)</Text> es
            tu dólar para usar: enviar, pagar, guardar. Cada cUSD tiene un
            respaldo equivalente en USDC dentro de una reserva verificable:
            $1 cUSD = $1 USD, hoy y siempre.
          </Text>
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>Confío Dollar+ (cUSD+)</Text>{' '}
            es tu dólar para ahorrar: está respaldado 1:1 por USDY, un token
            garantizado por bonos del Tesoro de EE.UU., y genera rendimiento
            todos los días. Ambos son tuyos — la blockchain permite comprobar
            públicamente que el respaldo existe.
          </Text>
        </View>

        {/* Reserve verifiable */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="eye" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>Reserva 100% verificable</Text>
          </View>
          <Text style={styles.sectionBody}>
            No tienes que confiar en nuestra palabra. El respaldo de cUSD se
            verifica en <Text style={styles.inlineEmphasis}>Pera Explorer</Text>{' '}
            (red Algorand) y el de cUSD+ en{' '}
            <Text style={styles.inlineEmphasis}>BscScan</Text> (red BNB Chain).
            Cualquier persona en el mundo puede consultar los saldos en tiempo
            real.
          </Text>
          <View style={styles.linksRow}>
            <TouchableOpacity
              style={[styles.linkButton, !s?.cusdAssetPeraUrl && styles.linkButtonDisabled]}
              onPress={() => openUrl(s?.cusdAssetPeraUrl)}
              disabled={!s?.cusdAssetPeraUrl}
            >
              <Icon
                name="external-link"
                size={13}
                color={s?.cusdAssetPeraUrl ? colors.primary : colors.text.light}
              />
              <Text
                style={[
                  styles.linkText,
                  !s?.cusdAssetPeraUrl && styles.linkTextDisabled,
                ]}
              >
                Ver cUSD en circulación
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() => openUrl(CUSD_RESERVE_PERA_URL)}
            >
              <Icon name="external-link" size={13} color={colors.primary} />
              <Text style={styles.linkText}>Ver respaldo USDC</Text>
            </TouchableOpacity>
            {/* TODO(cusd+): BscScan URLs at deploy — cUSD+ token page and the
                USDY reserve address holdings */}
            <TouchableOpacity style={[styles.linkButton, styles.linkButtonDisabled]} disabled>
              <Icon name="external-link" size={13} color={colors.text.light} />
              <Text style={[styles.linkText, styles.linkTextDisabled]}>Ver cUSD+ en circulación</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.linkButton, styles.linkButtonDisabled]} disabled>
              <Icon name="external-link" size={13} color={colors.text.light} />
              <Text style={[styles.linkText, styles.linkTextDisabled]}>Ver respaldo USDY</Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.tipText}>
            Tip: En cada explorador puedes ver la dirección de respaldo, su
            balance y cada transacción que entra o sale.
          </Text>
        </View>

        {/* Two dollars, two jobs — the real yield model (cUSD+ is a
            separate opt-in product; cUSD reserves are NEVER invested) */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="trending-up" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>Dos dólares, dos trabajos</Text>
          </View>

          <View style={styles.yieldBadgeRow}>
            <View style={styles.yieldBadge}>
              <Text style={styles.yieldBadgeNow}>cUSD</Text>
              <Text style={styles.yieldBadgeLabel}>PARA USAR</Text>
              <Text style={styles.yieldBadgeSub}>siempre $1</Text>
            </View>
            <Icon name="plus" size={20} color={colors.text.light} />
            <View style={[styles.yieldBadge, styles.yieldBadgeNext]}>
              <Text style={styles.yieldBadgeNext1}>cUSD+</Text>
              <Text style={styles.yieldBadgeLabel}>PARA AHORRAR</Text>
              <Text style={styles.yieldBadgeSub}>rendimiento diario</Text>
            </View>
          </View>

          <Text style={styles.sectionBody}>
            Las reservas USDC que respaldan tu cUSD{' '}
            <Text style={styles.inlineEmphasis}>nunca se invierten</Text> — se
            quedan 100% en USDC, verificables. El rendimiento vive en un
            producto separado y opcional:{' '}
            <Text style={styles.inlineEmphasis}>Confío Dollar+ (cUSD+)</Text>,
            respaldado 1:1 por USDY, un token garantizado por bonos del Tesoro
            de EE.UU.
          </Text>

          {/* Rates are LIVE from the server (Ondo's on-chain oracle) when
              available; the static example only stands in pre-launch, and
              says so in the title. */}
          <View style={styles.splitCard}>
            <Text style={styles.splitTitle}>
              {apyLive ? 'Cómo funciona cUSD+ (hoy)' : 'Cómo funciona cUSD+ (ejemplo)'}
            </Text>
            <View style={styles.splitRow}>
              <View style={[styles.splitDot, { backgroundColor: colors.text.light }]} />
              <Text style={styles.splitLabel}>Rendimiento de los bonos del Tesoro</Text>
              <Text style={styles.splitValue}>{apyLive ? pct(grossApy) : '~3.5%'}</Text>
            </View>
            <View style={styles.splitRow}>
              <View style={[styles.splitDot, { backgroundColor: colors.violet }]} />
              <Text style={styles.splitLabel}>Comisión Confío (15% del rendimiento)</Text>
              <Text style={styles.splitValue}>
                {apyLive ? pct(grossApy - netApy) : '~0.5%'}
              </Text>
            </View>
            <View style={styles.splitRow}>
              <View style={[styles.splitDot, { backgroundColor: colors.primary }]} />
              <Text style={[styles.splitLabel, styles.splitLabelStrong]}>
                Para ti, todos los días
              </Text>
              <Text style={[styles.splitValue, styles.splitValueStrong]}>
                {apyLive ? pct(netApy) : '~3%'}
              </Text>
            </View>
          </View>

          <View style={styles.partnerInline}>
            <Text style={styles.partnerInlineText}>En alianza con</Text>
            <Image source={OndoLogo} style={styles.partnerInlineLogo} />
            <Text style={styles.partnerInlineBrand}>Ondo Finance</Text>
          </View>

          <TouchableOpacity
            style={styles.ahorrosLink}
            onPress={() => navigation.navigate('Ahorros')}
            activeOpacity={0.85}
          >
            <Text style={styles.ahorrosLinkText}>Conocer Ahorros e Inversiones</Text>
            <Icon name="arrow-right" size={15} color={colors.primary} />
          </TouchableOpacity>

          <Text style={styles.disclaimer}>
            * Cifras ilustrativas: la tasa varía día a día con los bonos del
            Tesoro y no es fija ni garantizada. El respaldo USDY es
            verificable públicamente, igual que el de cUSD. Esto no constituye
            asesoría de inversión.
          </Text>
        </View>

        {/* The backing assets themselves — completes the trust chain:
            cUSD → USDC → Circle/dollars · cUSD+ → USDY → Ondo/Treasuries */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="layers" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>¿Y qué son USDC y USDY?</Text>
          </View>
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>USDC</Text> es el dólar digital
            más usado del mundo, emitido por{' '}
            <Text style={styles.inlineEmphasis}>Circle</Text>, una empresa
            regulada en EE.UU. Cada USDC está respaldado 1:1 por efectivo y
            bonos del Tesoro en custodios estadounidenses, con auditorías
            públicas mensuales.
          </Text>
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>USDY</Text> es un token de{' '}
            <Text style={styles.inlineEmphasis}>Ondo Finance</Text> respaldado
            por bonos del Tesoro de EE.UU. Esos bonos pagan interés todos los
            días — ese interés es el rendimiento que recibe tu cUSD+.
          </Text>
          <View style={styles.chainCard}>
            <Text style={styles.chainLine}>cUSD → USDC → dólares reales</Text>
            <Text style={styles.chainLine}>cUSD+ → USDY → bonos del Tesoro de EE.UU.</Text>
          </View>
        </View>

        {/* CTA */}
        <View style={styles.ctaSection}>
          <TouchableOpacity
            style={styles.ctaButton}
            onPress={() => navigation.navigate('TopUp')}
            activeOpacity={0.9}
          >
            <Icon name="dollar-sign" size={20} color={colors.white} />
            <Text style={styles.ctaText}>Recargar</Text>
          </TouchableOpacity>
          <Text style={styles.ctaHint}>
            Convierte tu moneda local en dólares digitales respaldados.
          </Text>
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
  scroll: { flex: 1 },
  hero: {
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 16,
  },
  heroLogoRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  heroLogo: { width: 64, height: 64 },
  heroLogoOverlap: { marginLeft: -14 },
  heroTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.dark,
    textAlign: 'center',
  },
  heroSubtitle: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    marginTop: 6,
    paddingHorizontal: 16,
    lineHeight: 20,
  },
  heroPillsRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 8,
    marginTop: 14,
  },
  heroStatPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.primarySoft,
  },
  heroStatText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  heroFootnote: {
    marginTop: 6,
    fontSize: 11,
    color: colors.text.light,
    fontWeight: '500',
  },
  section: {
    marginHorizontal: 16,
    marginBottom: 16,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 16,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 10,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.dark,
  },
  sectionBody: {
    fontSize: 14,
    color: colors.text.primary,
    lineHeight: 21,
    marginBottom: 8,
  },
  inlineEmphasis: {
    fontWeight: '700',
    color: colors.dark,
  },
  linksRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 4,
  },
  linkButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: colors.primarySoft,
  },
  linkButtonDisabled: {
    backgroundColor: colors.neutralDark,
  },
  linkText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  linkTextDisabled: {
    color: colors.text.light,
  },
  tipText: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 10,
    fontStyle: 'italic',
    lineHeight: 17,
  },
  yieldBadgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    marginBottom: 12,
  },
  yieldBadge: {
    flex: 1,
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: colors.neutralDark,
  },
  yieldBadgeNext: {
    backgroundColor: colors.primarySoft,
  },
  yieldBadgeNow: {
    fontSize: 20,
    fontWeight: '800',
    color: colors.text.secondary,
  },
  yieldBadgeNext1: {
    fontSize: 20,
    fontWeight: '800',
    color: colors.primary,
  },
  yieldBadgeSub: {
    fontSize: 10,
    color: colors.text.secondary,
    marginTop: 1,
  },
  yieldBadgeLabel: {
    fontSize: 9,
    fontWeight: '700',
    color: colors.text.secondary,
    marginTop: 2,
    letterSpacing: 0.4,
  },
  splitCard: {
    backgroundColor: colors.white,
    borderRadius: 10,
    padding: 12,
    marginTop: 4,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  splitTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.text.secondary,
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  splitRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 5,
  },
  splitDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  splitLabel: {
    flex: 1,
    fontSize: 13,
    color: colors.text.primary,
  },
  splitLabelStrong: {
    fontWeight: '700',
    color: colors.dark,
  },
  splitValue: {
    fontSize: 13,
    color: colors.text.primary,
    fontWeight: '600',
  },
  splitValueStrong: {
    color: colors.primary,
    fontWeight: '800',
  },
  disclaimer: {
    fontSize: 11,
    color: colors.text.secondary,
    lineHeight: 16,
    marginTop: 4,
  },
  partnerInline: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginBottom: 10,
  },
  partnerInlineText: { fontSize: 12, color: colors.text.light },
  partnerInlineLogo: { width: 15, height: 15, borderRadius: 4 },
  partnerInlineBrand: { fontSize: 12, fontWeight: '700', color: colors.text.secondary },
  ahorrosLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: colors.primarySoft,
    borderRadius: 10,
    paddingVertical: 11,
    marginBottom: 10,
  },
  ahorrosLinkText: { fontSize: 14, fontWeight: '700', color: colors.primary },
  chainCard: {
    backgroundColor: colors.white,
    borderRadius: 10,
    padding: 12,
    marginTop: 4,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 6,
  },
  chainLine: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.primary,
    textAlign: 'center',
  },
  ctaSection: {
    marginHorizontal: 16,
    marginBottom: 24,
    alignItems: 'center',
  },
  ctaButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    backgroundColor: colors.accent,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: 999,
  },
  ctaText: {
    color: colors.white,
    fontSize: 15,
    fontWeight: '700',
  },
  ctaHint: {
    marginTop: 10,
    fontSize: 12,
    color: colors.text.secondary,
    textAlign: 'center',
  },
  bottomPadding: { height: 32 },
});
