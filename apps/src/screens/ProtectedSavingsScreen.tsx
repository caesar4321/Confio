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
import {Header} from '../navigation/Header';
import Icon from 'react-native-vector-icons/Feather';
import {useNavigation} from '@react-navigation/native';
import {NativeStackNavigationProp} from '@react-navigation/native-stack';
import {gql, useQuery} from '@apollo/client';
import {colors} from '../config/theme';
import {useCurrency} from '../hooks/useCurrency';
import {useRampCountry} from '../hooks/useRampCountry';
import {useNumberFormat} from '../utils/numberFormatting';
import {MainStackParamList} from '../types/navigation';
import {GET_STATS_SUMMARY} from '../apollo/queries';
import {CUSD_RESERVE_PERA_URL} from '../config/algorand';
import {bscscanTokenHoldingsUrl} from '../utils/bscscan';

// cUSD+ reserve verification chain (BSC vault deployed 2026-07-10):
// vault token page → live USDY holdings → Ondo's issuer page → third-party
// attestations. The Ondo USDY page is the CANONICAL home of the attestation
// reports (Tokenholder Protections section); the Dropbox folders below are
// the direct links Ondo's onboarding team provided (2026-07) — if they ever
// rot, the USDY page always carries the current ones.
const CUSD_PLUS_TOKEN_BSCSCAN_URL =
  'https://bscscan.com/token/0x3C29417eb4314155e63d4C7D4507852b87763Ed1';
const CUSD_PLUS_VAULT_ASSETS_URL = bscscanTokenHoldingsUrl(
  '0x3C29417eb4314155e63d4C7D4507852b87763Ed1',
);
const ONDO_USDY_URL = 'https://app.ondo.finance/assets/usdy';
const USDY_ATTESTATION_DAILY_URL =
  'https://www.dropbox.com/scl/fo/375wdvar3rbc7o23nxsgp/AOFY8jhpENaNx9WAw-WPnbY?rlkey=4icqn1z9bez725wywr30fx52a&st=bsxeh8j5&dl=0';
const USDY_ATTESTATION_MONTHLY_URL =
  'https://www.dropbox.com/scl/fo/fk5t99zyihshuak3u1u9v/AMYiYSUwvoL6osa2FX_G_M8?rlkey=0ttmb4ifhdg4ebvhbh8aa3juc&st=fyoof4cu&dl=0';
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
      savingsEnabled
      cusdDepositsPaused
    }
  }
`;

const formatWhole = (n: number | null | undefined, sep: string) => {
  if (n == null) return '—';
  const r = Math.round(n);
  try {
    return new Intl.NumberFormat('en-US', {maximumFractionDigits: 0})
      .format(r)
      .replace(/,/g, sep);
  } catch {
    return `${r}`;
  }
};

export const ProtectedSavingsScreen = () => {
  const navigation =
    useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  // Same guard as Home: blocked countries go to Efectivo, not into a ramp
  // flow their country cannot complete.
  const {navigateToRampOrEfectivo} = useRampCountry();
  const {currency} = useCurrency();
  const {data} = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'cache-and-network',
    nextFetchPolicy: 'cache-first',
  });
  const s = data?.statsSummary;
  const tvl = s?.totalValueLocked ?? s?.protectedSavings;
  const tvlLabel = formatWhole(tvl, currency.thousandsSeparator);
  // statsSummary.usdyReserve is the USD VALUE of the USDY the vault holds
  // (server reads balance × oracle price, 2026-07-31), not a token count:
  // USDY accrues in price, so counting tokens would understate the reserve
  // and sit frozen while it actually grows. Same unit as the USDC pill.
  const usdyReserve = (s as any)?.usdyReserve ?? 0;
  const usdyLabel = formatWhole(usdyReserve, currency.thousandsSeparator);

  const {formatNumber} = useNumberFormat();
  const {data: apyData} = useQuery(GET_APY_SPLIT, {
    fetchPolicy: 'cache-and-network',
    nextFetchPolicy: 'cache-first',
  });
  const grossApy = apyData?.cusdPlusSummary?.grossApyPct ?? 0;
  const netApy = apyData?.cusdPlusSummary?.netApyPct ?? 0;
  // cUSD phase-out: while deposits are paused, the generic Recargar CTA
  // steers eligible users to the savings rail (same rule as the Home sheet).
  const steerToSavings =
    (apyData?.cusdPlusSummary?.cusdDepositsPaused ?? true) &&
    (apyData?.cusdPlusSummary?.savingsEnabled ?? true);
  const apyLive = grossApy > 0 && netApy > 0;
  const pct = (v: number) => `~${formatNumber(v, {maximumFractionDigits: 1})}%`;

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
            <Image
              source={cUSDPlusLogo}
              style={styles.heroLogo}
              resizeMode="contain"
            />
          </View>
          <Text style={styles.heroTitle}>Confío Dollar+</Text>
          <Text style={styles.heroSubtitle}>
            Tus dólares digitales, totalmente respaldados y verificables
            públicamente.
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
                US${usdyLabel} en USDY en reserva
              </Text>
            </View>
          </View>
          <Text style={styles.heroFootnote}>
            cUSD+: respaldado por USDY (Tesoro EE.UU.) · cUSD: respaldado por
            USDC
          </Text>
        </View>

        {/* What is cUSD+ (the protagonist); cUSD gets one honest line —
            still circulating, reserves intact — not a co-feature. */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="help-circle" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>¿Qué es cUSD+?</Text>
          </View>
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>Confío Dollar+ (cUSD+)</Text> es
            tu dólar para ahorrar: cada dólar está respaldado 100% por USDY, un
            activo digital de Ondo Finance respaldado por bonos del Tesoro de
            EE.UU., y acumula rendimiento cada día según una tasa anual
            variable. Los registros públicos permiten comprobar que el respaldo
            existe.
          </Text>
          <Text style={styles.sectionBody}>
            ¿Y <Text style={styles.inlineEmphasis}>cUSD</Text>? Sigue en
            circulación y 100% respaldado por USDC en una reserva verificable
            que <Text style={styles.inlineEmphasis}>nunca se invierte</Text> —
            puedes usarlo y retirarlo cuando quieras.
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
            puede comprobar en{' '}
            <Text style={styles.inlineEmphasis}>Pera Explorer</Text> (red
            Algorand) y el de cUSD+ en{' '}
            <Text style={styles.inlineEmphasis}>BscScan</Text> (red BNB Chain).
            Cualquier persona puede consultar los montos y movimientos en tiempo
            real.
          </Text>
          <View style={styles.linksRow}>
            <TouchableOpacity
              style={[
                styles.linkButton,
                !s?.cusdAssetPeraUrl && styles.linkButtonDisabled,
              ]}
              onPress={() => openUrl(s?.cusdAssetPeraUrl)}
              disabled={!s?.cusdAssetPeraUrl}>
              <Icon
                name="external-link"
                size={13}
                color={
                  s?.cusdAssetPeraUrl ? colors.successText : colors.text.light
                }
              />
              <Text
                style={[
                  styles.linkText,
                  !s?.cusdAssetPeraUrl && styles.linkTextDisabled,
                ]}>
                Ver cUSD en circulación
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() => openUrl(CUSD_RESERVE_PERA_URL)}>
              <Icon name="external-link" size={13} color={colors.successText} />
              <Text style={styles.linkText}>Ver respaldo USDC</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() => openUrl(CUSD_PLUS_TOKEN_BSCSCAN_URL)}>
              <Icon name="external-link" size={13} color={colors.successText} />
              <Text style={styles.linkText}>Ver cUSD+ en circulación</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() => openUrl(CUSD_PLUS_VAULT_ASSETS_URL)}>
              <Icon name="external-link" size={13} color={colors.successText} />
              <Text style={styles.linkText}>Ver respaldo USDY</Text>
            </TouchableOpacity>
          </View>
          <Text style={styles.tipText}>
            En cada página puedes ver dónde se guarda la reserva, cuánto
            contiene y cada movimiento que entra o sale.
          </Text>
        </View>

        {/* How the yield works (cUSD's reserve promise lives in the compact
            line above — this section is all cUSD+) */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="trending-up" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>Rendimiento todos los días</Text>
          </View>
          <Text style={styles.sectionBody}>
            La tasa que ves es anual (APY), pero tu ahorro acumula rendimiento
            todos los días. No tienes que esperar un plazo fijo para verlo
            crecer.
          </Text>

          {/* Rates are LIVE from the server (Ondo's on-chain oracle) when
              available; the static example only stands in pre-launch, and
              says so in the title. */}
          <View style={styles.splitCard}>
            <Text style={styles.splitTitle}>
              {apyLive
                ? 'Desglose de la tasa anual (hoy)'
                : 'Desglose de la tasa anual (ejemplo)'}
            </Text>
            <View style={styles.splitRow}>
              <View
                style={[styles.splitDot, {backgroundColor: colors.text.light}]}
              />
              <Text style={styles.splitLabel}>
                Tasa anual de los bonos del Tesoro
              </Text>
              <Text style={styles.splitValue}>
                {apyLive ? pct(grossApy) : '~3.5%'}
              </Text>
            </View>
            <View style={styles.splitRow}>
              <View
                style={[styles.splitDot, {backgroundColor: colors.violet}]}
              />
              <Text style={styles.splitLabel}>
                Comisión Confío (15% del rendimiento generado)
              </Text>
              <Text style={styles.splitValue}>
                {apyLive ? pct(grossApy - netApy) : '~0.5%'}
              </Text>
            </View>
            <View style={styles.splitRow}>
              <View
                style={[styles.splitDot, {backgroundColor: colors.primary}]}
              />
              <Text style={[styles.splitLabel, styles.splitLabelStrong]}>
                Tasa anual para ti
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
            style={styles.savingsLink}
            onPress={() =>
              navigation.navigate('AccountDetail', {
                accountType: 'cusd_plus',
                accountName: 'Confío Dollar+',
                accountSymbol: '$cUSD+',
                // Live figures come from the portfolio inside the screen;
                // this is only the first paint.
                accountBalance: '0.00',
              })
            }
            activeOpacity={0.85}>
            <Text style={styles.savingsLinkText}>Conocer Confío Dollar+</Text>
            <Icon name="arrow-right" size={15} color={colors.primary} />
          </TouchableOpacity>

          <Text style={styles.disclaimer}>
            * Las tasas mostradas son anuales (APY). Varían día a día con los
            bonos del Tesoro y no son fijas ni garantizadas. El respaldo USDY
            es verificable públicamente, igual que el de cUSD. Esto no
            constituye asesoría de inversión.
          </Text>
        </View>

        {/* The backing assets themselves — completes the trust chain:
            cUSD → USDC → Circle/dollars · cUSD+ → USDY → Ondo/Treasuries */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="layers" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>¿Qué es USDY?</Text>
          </View>
          {/* Deepest in-app tier: this paragraph mirrors Ondo's OWN wording
              for the BNB deployment, verbatim-translated, rather than a
              conservative phrasing of our own. Source: "USDY Is Now Live on
              BNB Chain" (ondo.finance/blog/usdy-is-live-on-bnb-chain,
              2026-08-04) — "yield backed by short-term U.S. Treasuries, U.S.
              Treasuries and government securities funds, or cash instruments",
              which matches the Underlying Components list in the Sales Terms
              Token Spec (not the legacy USDY LLC "99.86% Treasuries" figure).
              The short one-liners elsewhere in the app are abbreviations of
              this sentence and must never contradict it. */}
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>USDY</Text> es un activo digital
            de <Text style={styles.inlineEmphasis}>Ondo Finance</Text>{' '}
            respaldado por bonos del Tesoro de EE.UU. de corto plazo, fondos que
            invierten en deuda del gobierno e instrumentos similares al
            efectivo. Su rendimiento se expresa como una tasa anual y se
            acumula cada día — ese es el rendimiento que recibe tu cUSD+.
            (USDC, el respaldo de cUSD, es el dólar digital de Circle, con
            auditorías públicas mensuales.)
          </Text>
          <Text style={styles.sectionBody}>
            Empresas independientes revisan las reservas de USDY. Ondo publica
            reportes diarios y mensuales en su página oficial.
          </Text>
          <View style={styles.linksRow}>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() => openUrl(ONDO_USDY_URL)}>
              <Icon name="external-link" size={13} color={colors.successText} />
              <Text style={styles.linkText}>USDY en Ondo Finance</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() => openUrl(USDY_ATTESTATION_DAILY_URL)}>
              <Icon name="external-link" size={13} color={colors.successText} />
              <Text style={styles.linkText}>Reporte diario de respaldo</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() => openUrl(USDY_ATTESTATION_MONTHLY_URL)}>
              <Icon name="external-link" size={13} color={colors.successText} />
              <Text style={styles.linkText}>Reporte mensual de respaldo</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.chainCard}>
            <Text style={styles.chainLine}>cUSD → USDC → dólares reales</Text>
            <Text style={styles.chainLine}>
              cUSD+ → USDY → bonos del Tesoro de EE.UU.
            </Text>
          </View>
        </View>

        {/* No fine print — the two promises that used to live on the
            savings account screen (moved here 2026-07-30 with the rest of
            the education; the account screen links to this page). */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="check-circle" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>Sin letra chica</Text>
          </View>
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>Retira cuando quieras.</Text>{' '}
            Sin plazos ni penalidades: tu dinero está disponible al instante,
            todos los días.
          </Text>
          <Text style={styles.sectionBody}>
            <Text style={styles.inlineEmphasis}>Sin comisiones ocultas.</Text>{' '}
            La tasa que ves ya descuenta nuestra comisión. Si un movimiento
            tiene costo, lo ves antes de confirmar — nunca después.
          </Text>
        </View>

        {/* CTA */}
        <View style={styles.ctaSection}>
          <TouchableOpacity
            style={styles.ctaButton}
            onPress={() =>
              steerToSavings
                ? navigateToRampOrEfectivo('TopUp', {destination: 'cusd_plus'})
                : navigateToRampOrEfectivo('TopUp')
            }
            activeOpacity={0.9}>
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
  scroll: {flex: 1},
  hero: {
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 16,
  },
  heroLogoRow: {flexDirection: 'row', alignItems: 'center', marginBottom: 12},
  heroLogo: {width: 64, height: 64},
  heroLogoOverlap: {marginLeft: -14},
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
    flexShrink: 1,
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
  // See OndoStocksInfoScreen: primarySoft on the neutral card is a 1.01:1
  // edge and the mint label was 1.82:1, so the chips read as invisible text.
  linkButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: colors.primaryLight,
  },
  linkButtonDisabled: {
    backgroundColor: colors.neutralDark,
  },
  linkText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.successText,
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
  partnerInlineText: {fontSize: 12, color: colors.text.light},
  partnerInlineLogo: {width: 15, height: 15, borderRadius: 4},
  partnerInlineBrand: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.text.secondary,
  },
  savingsLink: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: colors.primarySoft,
    borderRadius: 10,
    paddingVertical: 11,
    marginBottom: 10,
  },
  savingsLinkText: {fontSize: 14, fontWeight: '700', color: colors.primary},
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
  bottomPadding: {height: 32},
});
