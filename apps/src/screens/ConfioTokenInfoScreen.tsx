import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Image } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { Header } from '../navigation/Header';
import { useCurrency } from '../hooks/useCurrency';
import { MainStackParamList } from '../types/navigation';
import { GET_STATS_SUMMARY } from '../apollo/queries';
import { TrustPillars } from '../components/ConfioNarrative';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';

export const ConfioTokenInfoScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { data } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'cache-first',
    notifyOnNetworkStatusChange: true,
  });

  const formatWholeNumber = (n: number | null | undefined) => {
    if (n == null) return '—';
    const rounded = Math.round(n);
    try {
      return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
        useGrouping: true,
      })
        .format(rounded)
        .replace(/,/g, currency.thousandsSeparator);
    } catch {
      return `${rounded}`.replace(/\B(?=(\d{3})+(?!\d))/g, currency.thousandsSeparator);
    }
  };

  const s = data?.statsSummary;
  const dollarSavingsTotal =
    s?.totalValueLocked == null ||
    s?.cusdBscReserve == null ||
    s?.usdyReserve == null
      ? null
      : s.totalValueLocked + s.cusdBscReserve + s.usdyReserve;
  const usersNew7d = Math.max(0, Math.round(s?.usersNew7d ?? 0));
  const presaleRaised7d = Math.max(0, s?.presaleCusdRaised7d ?? 0);
  const usersGrowth = usersNew7d > 0
    ? `+${formatWholeNumber(usersNew7d)} esta semana`
    : 'acumulado';
  const presaleGrowth = presaleRaised7d > 0
    ? `+$${formatWholeNumber(presaleRaised7d)} esta semana`
    : 'acumulado';
  const stats: Array<{
    label: string;
    value: string;
    growth: string;
    growthHighlight?: boolean;
    description?: string;
    route: 'LatamCommunity' | 'ProtectedSavings' | 'ConfioPresale';
  }> = [
    {
      label: 'Usuarios registrados',
      value: formatWholeNumber(s?.totalUsers),
      growth: usersGrowth,
      growthHighlight: usersNew7d > 0,
      description: 'Personas con teléfono verificado y acceso con Apple o Google.',
      route: 'LatamCommunity',
    },
    {
      label: 'Ahorros en dólares',
      value: dollarSavingsTotal == null
        ? '—'
        : `$${formatWholeNumber(dollarSavingsTotal)}`,
      growth: 'reservas verificables',
      growthHighlight: false,
      description: 'Reservas en USDT, USDC y USDY detrás de Confío Dollar y Confío Dollar+. No respaldan $CONFIO.',
      route: 'ProtectedSavings',
    },
    {
      label: 'Preventa de $CONFIO',
      value: s?.presaleCusdRaised == null ? '—' : `$${formatWholeNumber(s.presaleCusdRaised)}`,
      growth: presaleGrowth,
      growthHighlight: presaleRaised7d > 0,
      description: 'Dólares aportados por la comunidad en la preventa.',
      route: 'ConfioPresale',
    },
  ];

  // Milestones, not calendar promises: only shipped work carries a year.
  const timeline: Array<{ status: 'done' | 'now' | 'next'; tag: string; title: string; text: string }> = [
    {
      status: 'done',
      tag: '2025',
      title: 'Nace Confío',
      text: 'Una billetera donde tus claves son tuyas, con dólares digitales y envíos entre personas.',
    },
    {
      status: 'done',
      tag: '2026',
      title: 'El dinero local se conecta',
      text: 'Recargas y retiros con métodos de pago locales en varios países de Latinoamérica.',
    },
    {
      status: 'done',
      tag: '2026',
      title: 'Ahorrar e invertir en la misma app',
      text: 'Confío Dollar+ con Ondo Finance y acciones de EE. UU. para usuarios elegibles.',
    },
    {
      status: 'done',
      tag: '2026',
      title: '$CONFIO llega a BNB Smart Chain',
      text: 'Suministro fijo y una preventa continua que cualquiera puede verificar.',
    },
    {
      status: 'now',
      tag: 'Ahora',
      title: 'Del uso a la costumbre',
      text: 'Más personas cobrando, pagando y ahorrando en Confío todos los días. Más comercios y empresas.',
    },
    {
      status: 'next',
      tag: 'Lo que sigue',
      title: 'Reputación y acuerdos',
      text: 'Que la confianza que construyes viaje contigo, y que más promesas se cumplan con reglas verificables.',
    },
  ];

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Moneda $CONFIO"
        backgroundColor={colors.secondary}
        isLight
        showBackButton
      />

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Hero — violet brand field, same family as Preventa/Distribución */}
        <View style={styles.heroSection}>
          <BrandFieldBackground id="tokenInfoField" fromColor={colors.secondary} toColor={colors.secondaryDark} ringCy="22%" ringR={80} ringWidth={20} />
          <View style={styles.heroInner}>
            <View style={styles.tokenIcon}>
              <Image
                source={require('../assets/png/CONFIO.png')}
                style={styles.tokenImage}
                resizeMode="contain"
              />
            </View>
            <Text style={styles.heroTitle}>¿Por qué se llama Confío?</Text>
            <Text style={styles.heroSubtitle}>
              Porque la confianza ya existe. Nuestro trabajo es que se mueva contigo.
            </Text>
          </View>
        </View>

        {/* Manifesto */}
        <View style={styles.section}>
          <Text style={styles.manifestoTitle}>La confianza ya existe.</Text>
          <Text style={styles.manifestoText}>
            En Latinoamérica trabajamos, vendemos, prestamos y nos ayudamos todos los días.
            La confianza está en nuestras relaciones, en nuestra palabra y en cada vez que cumplimos.
          </Text>
          <Text style={styles.manifestoText}>
            El problema es que casi nunca nos pertenece. Tu dinero depende de una institución.
            Tu reputación queda atrapada en una plataforma. Tus acuerdos dependen de intermediarios
            que pueden cambiar las reglas.
          </Text>
          <Text style={styles.manifestoEmphasis}>
            No hay que inventar la confianza. Hay que darle infraestructura.
          </Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionHeading}>Dinero · Reputación · Acuerdos</Text>
          <View style={styles.pillarsCard}>
            <TrustPillars variant="full" />
          </View>
        </View>

        {/* Founder quote */}
        <View style={styles.quoteCard}>
          <Icon name="message-circle" size={22} color={colors.secondary} />
          <Text style={styles.quoteText}>
            "No porque tengas que confiar ciegamente en nosotros, sino porque estamos construyendo
            un sistema donde puedas volver a confiar en tu propio dinero."
          </Text>
          <Text style={styles.quoteAuthor}>— Julian Moon, fundador de Confío</Text>
        </View>

        {/* Proof, not promises */}
        <View style={styles.section}>
          <Text style={styles.sectionHeading}>Confío hoy</Text>
          <View style={styles.statsGrid}>
            {stats.map((stat, index) => (
              <TouchableOpacity
                key={index}
                style={styles.statCard}
                activeOpacity={0.75}
                onPress={() => navigation.navigate(stat.route)}
              >
                <View style={styles.statMainRow}>
                  <View style={styles.statTextBlock}>
                    <Text style={styles.statLabel}>{stat.label}</Text>
                    {stat.description ? (
                      <Text style={styles.statDescription}>{stat.description}</Text>
                    ) : null}
                  </View>
                  <View style={styles.statValueBlock}>
                    <Text style={styles.statValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.78}>
                      {stat.value}
                    </Text>
                    <View style={styles.growthBadge}>
                      {stat.growthHighlight !== false && (
                        <Icon name="trending-up" size={12} color={colors.primary} />
                      )}
                      <Text
                        style={[
                          styles.growthText,
                          stat.growthHighlight === false && styles.growthTextMuted,
                        ]}
                      >
                        {stat.growth}
                      </Text>
                    </View>
                  </View>
                  <Icon
                    name="chevron-right"
                    size={18}
                    color={colors.text.light}
                    style={styles.statChevron}
                  />
                </View>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* Timeline */}
        <View style={styles.section}>
          <Text style={styles.sectionHeading}>De una idea a una red latinoamericana</Text>
          <View>
            {timeline.map((item, index) => {
              const isLast = index === timeline.length - 1;
              return (
                <View key={item.title} style={styles.timelineItem}>
                  <View style={styles.timelineRail}>
                    <View
                      style={[
                        styles.timelineDot,
                        item.status === 'done' && styles.timelineDotDone,
                        item.status === 'now' && styles.timelineDotNow,
                      ]}
                    >
                      {item.status === 'done' && <Icon name="check" size={10} color={colors.white} />}
                    </View>
                    {!isLast && (
                      <View style={[styles.timelineLine, item.status === 'done' && styles.timelineLineDone]} />
                    )}
                  </View>
                  <View style={[styles.timelineContent, !isLast && styles.timelineContentSpaced]}>
                    <Text
                      style={[
                        styles.timelineTag,
                        item.status === 'now' && styles.timelineTagNow,
                      ]}
                    >
                      {item.tag}
                    </Text>
                    <Text style={styles.timelineTitle}>{item.title}</Text>
                    <Text style={styles.timelineText}>{item.text}</Text>
                  </View>
                </View>
              );
            })}
          </View>
        </View>

        {/* CTA */}
        <View style={styles.ctaSection}>
          <Text style={styles.ctaTitle}>Súmate desde el principio</Text>
          <Text style={styles.ctaSubtitle}>
            $CONFIO es la moneda de la comunidad que construye Confío. Conoce la preventa o gana
            $CONFIO invitando a tus amigos.
          </Text>
          <Button
            title="Ver la preventa"
            onPress={() => navigation.navigate('ConfioPresale')}
            icon={<Icon name="star" size={20} color={colors.white} />}
            style={{ backgroundColor: colors.secondary, borderRadius: 24, paddingHorizontal: 24, marginBottom: 12, alignSelf: 'stretch' }}
          />
          <TouchableOpacity
            style={styles.secondaryButton}
            onPress={() => navigation.navigate('Achievements')}
          >
            <Icon name="gift" size={16} color={colors.secondary} />
            <Text style={styles.secondaryButtonText}>Programa de referidos</Text>
          </TouchableOpacity>
          <Text style={styles.ctaFinePrint}>
            Las recompensas se registran hoy y se reclaman cuando $CONFIO se lance en un DEX.
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
    lineHeight: 24,
  },
  section: {
    paddingHorizontal: 20,
    paddingTop: 32,
  },
  manifestoTitle: {
    fontSize: 26,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'center',
    marginBottom: 16,
  },
  manifestoText: {
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 25,
    marginBottom: 12,
  },
  manifestoEmphasis: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.secondaryDark,
    textAlign: 'center',
    lineHeight: 26,
    marginTop: 4,
  },
  sectionHeading: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 16,
    textAlign: 'center',
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
  quoteCard: {
    marginHorizontal: 20,
    marginTop: 32,
    backgroundColor: colors.violetLight,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
  },
  quoteText: {
    fontSize: 16,
    color: colors.dark,
    textAlign: 'center',
    lineHeight: 25,
    fontStyle: 'italic',
    marginTop: 12,
  },
  quoteAuthor: {
    fontSize: 14,
    color: colors.text.secondary,
    marginTop: 12,
    fontWeight: '600',
  },
  statsGrid: {
    flexDirection: 'column',
    gap: 12,
  },
  statCard: {
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 16,
  },
  statMainRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  statTextBlock: {
    flex: 1,
    minWidth: 0,
  },
  statLabel: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.dark,
  },
  statDescription: {
    fontSize: 12,
    color: colors.text.secondary,
    lineHeight: 17,
    marginTop: 4,
  },
  statValueBlock: {
    alignItems: 'flex-end',
    justifyContent: 'center',
    minWidth: 124,
    flexShrink: 0,
  },
  statValue: {
    fontSize: 22,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'right',
    includeFontPadding: false,
  },
  growthBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 6,
  },
  growthText: {
    fontSize: 12,
    color: colors.primary,
    fontWeight: '600',
  },
  growthTextMuted: {
    color: colors.text.secondary,
    fontWeight: '500',
  },
  statChevron: {
    marginLeft: 4,
  },
  timelineItem: {
    flexDirection: 'row',
  },
  timelineRail: {
    alignItems: 'center',
    width: 20,
    marginRight: 14,
  },
  timelineDot: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: colors.white,
    borderWidth: 2,
    borderColor: colors.border,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 1,
  },
  timelineDotDone: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  timelineDotNow: {
    borderColor: colors.secondary,
    borderWidth: 6,
  },
  timelineLine: {
    flex: 1,
    width: 2,
    marginVertical: 2,
    backgroundColor: colors.border,
  },
  timelineLineDone: {
    backgroundColor: colors.primaryLight,
  },
  timelineContent: {
    flex: 1,
  },
  timelineContentSpaced: {
    paddingBottom: 20,
  },
  timelineTag: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.text.secondary,
    marginBottom: 2,
  },
  timelineTagNow: {
    color: colors.secondary,
  },
  timelineTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 2,
  },
  timelineText: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
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
    fontSize: 15,
    color: colors.text.secondary,
    marginBottom: 20,
    textAlign: 'center',
    lineHeight: 22,
  },
  secondaryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderWidth: 1,
    borderColor: colors.secondary,
    borderRadius: 24,
    alignSelf: 'stretch',
  },
  secondaryButtonText: {
    fontSize: 15,
    color: colors.secondary,
    fontWeight: '600',
  },
  ctaFinePrint: {
    fontSize: 12,
    color: colors.text.light,
    textAlign: 'center',
    lineHeight: 18,
    marginTop: 16,
  },
  bottomPadding: {
    height: 40,
  },
});
