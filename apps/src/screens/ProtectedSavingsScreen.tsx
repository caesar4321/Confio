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
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery } from '@apollo/client';
import { colors } from '../config/theme';
import { useCurrency } from '../hooks/useCurrency';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';
import { CUSD_RESERVE_PERA_URL } from '../config/algorand';
import cUSDLogo from '../assets/png/cUSD.png';

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

  const openUrl = (url?: string | null) => {
    if (!url) return;
    Linking.openURL(url).catch(() => {});
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Ahorros Protegidos</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView style={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* Hero */}
        <View style={styles.hero}>
          <Image source={cUSDLogo} style={styles.heroLogo} resizeMode="contain" />
          <Text style={styles.heroTitle}>Confío Dollar (cUSD)</Text>
          <Text style={styles.heroSubtitle}>
            Tu dólar digital, 100% respaldado en blockchain.
          </Text>
          <View style={styles.heroStatPill}>
            <Icon name="shield" size={14} color={colors.primary} />
            <Text style={styles.heroStatText}>
              {tvlLabel} USDC en reserva
            </Text>
          </View>
          <Text style={styles.heroFootnote}>
            Hoy: USDC · A futuro: mTBILL
          </Text>
        </View>

        {/* What is cUSD */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="help-circle" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>¿Qué es Confío Dollar?</Text>
          </View>
          <Text style={styles.sectionBody}>
            Confío Dollar (cUSD) es nuestro dólar digital. Cada cUSD que ves
            en la app está respaldado por exactamente $1 USDC en reserva,
            custodiado en una bóveda pública en la red Algorand.
          </Text>
          <Text style={styles.sectionBody}>
            Es estable, transferible al instante y siempre verificable. No
            depende de la inflación local: $1 cUSD = $1 USD, hoy y siempre.
          </Text>
        </View>

        {/* Reserve verifiable */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="eye" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>Reserva 100% verificable</Text>
          </View>
          <Text style={styles.sectionBody}>
            No tienes que confiar en nuestra palabra. Las reservas USDC que
            respaldan cada cUSD se pueden verificar públicamente en{' '}
            <Text style={styles.inlineEmphasis}>Pera Explorer</Text>, el
            visualizador oficial de la red Algorand. Cualquier persona en el
            mundo puede consultar los saldos en tiempo real.
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
                color={s?.cusdAssetPeraUrl ? colors.primary : '#9CA3AF'}
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
          </View>
          <Text style={styles.tipText}>
            Tip: En Pera Explorer puedes ver la dirección de la bóveda, el
            balance USDC y cada transacción que entra o sale.
          </Text>
        </View>

        {/* Yield roadmap */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="trending-up" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>Rendimiento</Text>
          </View>

          <View style={styles.yieldBadgeRow}>
            <View style={styles.yieldBadge}>
              <Text style={styles.yieldBadgeNow}>0%</Text>
              <Text style={styles.yieldBadgeLabel}>HOY</Text>
            </View>
            <Icon name="arrow-right" size={20} color="#9CA3AF" />
            <View style={[styles.yieldBadge, styles.yieldBadgeNext]}>
              <Text style={styles.yieldBadgeNext1}>hasta 3%</Text>
              <Text style={styles.yieldBadgeLabel}>ANUAL · PRÓXIMAMENTE</Text>
            </View>
          </View>

          <Text style={styles.sectionBody}>
            Hoy las reservas USDC no generan rendimiento para ti. Estamos
            explorando un modelo donde las reservas se inviertan en
            instrumentos institucionales conservadores (por ejemplo{' '}
            <Text style={styles.inlineEmphasis}>mTBILL</Text>, que sigue los
            bonos del Tesoro de EE.UU.), y una parte del rendimiento vuelva a
            quienes mantienen cUSD en la app.
          </Text>

          <View style={styles.splitCard}>
            <Text style={styles.splitTitle}>Cómo se repartiría (ejemplo)</Text>
            <View style={styles.splitRow}>
              <View style={[styles.splitDot, { backgroundColor: '#9CA3AF' }]} />
              <Text style={styles.splitLabel}>Rendimiento bruto de la reserva</Text>
              <Text style={styles.splitValue}>~4%</Text>
            </View>
            <View style={styles.splitRow}>
              <View style={[styles.splitDot, { backgroundColor: colors.violet }]} />
              <Text style={styles.splitLabel}>Para sostener Confío</Text>
              <Text style={styles.splitValue}>1%</Text>
            </View>
            <View style={styles.splitRow}>
              <View style={[styles.splitDot, { backgroundColor: colors.primary }]} />
              <Text style={[styles.splitLabel, styles.splitLabelStrong]}>
                Para ti, por mantener cUSD
              </Text>
              <Text style={[styles.splitValue, styles.splitValueStrong]}>3%</Text>
            </View>
          </View>

          <Text style={styles.disclaimer}>
            * Cifras ilustrativas. El modelo de rendimiento está en exploración
            y aún no está activo. Las tasas reales dependerán de las
            condiciones del mercado y la regulación local. Esto no constituye
            una oferta de inversión.
          </Text>
        </View>

        {/* Community power */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Icon name="users" size={20} color={colors.primary} />
            <Text style={styles.sectionTitle}>
              Más fuerza, mejores condiciones
            </Text>
          </View>
          <Text style={styles.sectionBody}>
            Cuanto más grande sea la reserva USDC respaldando a cUSD, más
            fuerza tiene Confío para negociar con nuestros socios financieros:
            mejores tasas, comisiones más bajas y condiciones más favorables
            para toda la comunidad latina.
          </Text>
          <Text style={styles.sectionBody}>
            Cada cUSD que tienes en la app suma. Recargar es un acto de
            comunidad: te protege de la inflación local y nos hace más fuertes
            a todos.
          </Text>
        </View>

        {/* CTA */}
        <View style={styles.ctaSection}>
          <TouchableOpacity
            style={styles.ctaButton}
            onPress={() => navigation.navigate('TopUp')}
            activeOpacity={0.9}
          >
            <Icon name="plus-circle" size={20} color="#fff" />
            <Text style={styles.ctaText}>Recargar</Text>
          </TouchableOpacity>
          <Text style={styles.ctaHint}>
            Convierte tu moneda local en cUSD y únete a la reserva.
          </Text>
        </View>

        <View style={styles.bottomPadding} />
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    backgroundColor: colors.primary,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 12,
    paddingBottom: 20,
    paddingHorizontal: 20,
  },
  backButton: { padding: 8 },
  headerTitle: { fontSize: 18, fontWeight: 'bold', color: '#fff' },
  headerSpacer: { width: 40 },
  scroll: { flex: 1 },
  hero: {
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 16,
  },
  heroLogo: { width: 64, height: 64, marginBottom: 12 },
  heroTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.dark,
    textAlign: 'center',
  },
  heroSubtitle: {
    fontSize: 14,
    color: '#6B7280',
    textAlign: 'center',
    marginTop: 6,
    paddingHorizontal: 16,
    lineHeight: 20,
  },
  heroStatPill: {
    marginTop: 14,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: '#E8F7F0',
  },
  heroStatText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  heroFootnote: {
    marginTop: 6,
    fontSize: 11,
    color: '#9CA3AF',
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
    color: '#374151',
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
    backgroundColor: '#E8F7F0',
  },
  linkButtonDisabled: {
    backgroundColor: '#F3F4F6',
  },
  linkText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  linkTextDisabled: {
    color: '#9CA3AF',
  },
  tipText: {
    fontSize: 12,
    color: '#6B7280',
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
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: '#F3F4F6',
    minWidth: 90,
  },
  yieldBadgeNext: {
    backgroundColor: '#E8F7F0',
  },
  yieldBadgeNow: {
    fontSize: 20,
    fontWeight: '800',
    color: '#6B7280',
  },
  yieldBadgeNext1: {
    fontSize: 20,
    fontWeight: '800',
    color: colors.primary,
  },
  yieldBadgeLabel: {
    fontSize: 9,
    fontWeight: '700',
    color: '#6B7280',
    marginTop: 2,
    letterSpacing: 0.4,
  },
  splitCard: {
    backgroundColor: '#fff',
    borderRadius: 10,
    padding: 12,
    marginTop: 4,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  splitTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#6B7280',
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
    color: '#374151',
  },
  splitLabelStrong: {
    fontWeight: '700',
    color: colors.dark,
  },
  splitValue: {
    fontSize: 13,
    color: '#374151',
    fontWeight: '600',
  },
  splitValueStrong: {
    color: colors.primary,
    fontWeight: '800',
  },
  disclaimer: {
    fontSize: 11,
    color: '#6B7280',
    lineHeight: 16,
    marginTop: 4,
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
    backgroundColor: colors.primary,
    paddingHorizontal: 24,
    paddingVertical: 14,
    borderRadius: 999,
  },
  ctaText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
  ctaHint: {
    marginTop: 10,
    fontSize: 12,
    color: '#6B7280',
    textAlign: 'center',
  },
  bottomPadding: { height: 32 },
});
