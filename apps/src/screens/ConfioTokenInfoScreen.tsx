import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, Linking } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery, gql } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors } from '../config/theme';
import { useCurrency } from '../hooks/useCurrency';
import { MainStackParamList } from '../types/navigation';

const GET_STATS_SUMMARY = gql`
  query GetStatsSummary {
    statsSummary {
      totalUsers
      protectedSavings
      totalValueLocked
      presaleCusdRaised
      statsSource
      cusdAssetPeraUrl
    }
  }
`;

const CUSD_RESERVE_PERA_URL =
  'https://explorer.perawallet.app/address/AVHAIQVVHNWAD7W2LQ5URTQYWKO3OXMWXW2NU4CXIQBHLWFA7XC57LDSEY/';

export const ConfioTokenInfoScreen = () => {
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();
  const { currency } = useCurrency();
  const { data } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'cache-first',
    notifyOnNetworkStatusChange: true,
  });

  const formatWholeNumber = (n: number | null | undefined) => {
    if (n == null) return '-';
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

  const sections = [
    {
      title: '¿Qué es $CONFIO?',
      icon: 'help-circle',
      content: '$CONFIO es la moneda de gobernanza de la app de Confío. Cada moneda representa tu participación en el futuro de una economía estable sin inflación en Latinoamérica.',
    },
    {
      title: '¿Por qué están bloqueadas?',
      icon: 'lock',
      content: 'Las monedas están bloqueadas temporalmente para asegurar un crecimiento sostenible. Cuando se liberen, podrás usarlas para votar en decisiones importantes, acceder a beneficios exclusivos y más.',
    },
    {
      title: 'El Futuro de $CONFIO',
      icon: 'trending-up',
      content: 'Imagina cuando millones en Venezuela, Argentina, Bolivia y toda Latinoamérica puedan construir su vida sin miedo a la inflación. Tu participación temprana será recompensada cuando el ecosistema crezca.',
    },
    {
      title: 'Cómo Ganar Más $CONFIO',
      icon: 'gift',
      bullets: [
        'Invita amigos con tu código y gana el equivalente a US$5 en $CONFIO por cada referido elegible',
      ],
    },
  ];

  const s = data?.statsSummary;
  const liveLabel = s?.statsSource === 'algorand' ? 'en blockchain' : 'actualizado';
  const openPeraLink = (url?: string | null) => {
    if (!url) return;
    Linking.openURL(url).catch(() => {});
  };
  const stats = [
    {
      label: 'Usuarios en Confío',
      value: formatWholeNumber(s?.totalUsers ?? 0),
      growth: 'total',
    },
    {
      label: 'Ahorros Protegidos',
      value: `${formatWholeNumber(s?.totalValueLocked ?? s?.protectedSavings ?? 0)} cUSD`,
      growth: liveLabel,
      description: 'USDC de respaldo que protege los cUSD de los usuarios.',
      links: [
        { label: 'Ver cUSD', url: s?.cusdAssetPeraUrl },
        { label: 'Ver respaldo', url: CUSD_RESERVE_PERA_URL },
      ],
    },
    {
      label: 'Preventa de $CONFIO',
      value: `${formatWholeNumber(s?.presaleCusdRaised ?? 0)} cUSD`,
      growth: 'total',
      description: 'cUSD aportados por la comunidad en la preventa.',
    },
  ];

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Moneda $CONFIO</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Hero Section */}
        <View style={styles.heroSection}>
          <View style={styles.tokenIcon}>
            <Image 
              source={require('../assets/png/CONFIO.png')} 
              style={styles.tokenImage}
              resizeMode="contain"
            />
          </View>
          <Text style={styles.heroTitle}>Tu Inversión en el Futuro</Text>
          <Text style={styles.heroSubtitle}>
            Sé parte de la economía estable sin inflación en Latinoamérica
          </Text>
        </View>

        {/* Vision Card */}
        <View style={styles.visionCard}>
          <Icon name="zap" size={24} color={colors.violet} />
          <Text style={styles.visionTitle}>Nuestra Visión</Text>
          <Text style={styles.visionText}>
            "Imagina cuando toda Venezuela, Argentina, Bolivia y el resto de Latinoamérica use la app de Confío. 
            Cuando millones de familias puedan construir su vida sin miedo a la inflación, 
            con una moneda estable y una economía predecible. Ese es el futuro que estamos construyendo juntos."
          </Text>
          <Text style={styles.visionAuthor}>- Julian Moon, Fundador</Text>
        </View>

        {/* Growth Stats */}
        <View style={styles.statsContainer}>
          <Text style={styles.statsTitle}>Crecimiento Exponencial</Text>
          <View style={styles.statsGrid}>
            {stats.map((stat, index) => (
              <View key={index} style={styles.statCard}>
                <View style={styles.statMainRow}>
                  <View style={styles.statTextBlock}>
                    <Text style={styles.statLabel}>{stat.label}</Text>
                    {'description' in stat && stat.description ? (
                      <Text style={styles.statDescription}>{stat.description}</Text>
                    ) : null}
                  </View>
                  <View style={styles.statValueBlock}>
                    <Text style={styles.statValue} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.78}>
                      {stat.value}
                    </Text>
                    <View style={styles.growthBadge}>
                      <Icon name="trending-up" size={12} color={colors.primary} />
                      <Text style={styles.growthText}>{stat.growth}</Text>
                    </View>
                  </View>
                </View>
                {'links' in stat && stat.links?.length ? (
                  <View style={styles.statLinksRow}>
                    {stat.links.map((link) => (
                      <TouchableOpacity
                        key={link.label}
                        style={[styles.statLinkButton, !link.url && styles.statLinkButtonDisabled]}
                        onPress={() => openPeraLink(link.url)}
                        disabled={!link.url}
                      >
                        <Icon name="external-link" size={13} color={link.url ? colors.primary : '#9CA3AF'} />
                        <Text style={[styles.statLinkText, !link.url && styles.statLinkTextDisabled]}>
                          {link.label}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                ) : null}
              </View>
            ))}
          </View>
        </View>

        {/* Info Sections */}
        {sections.map((section, index) => (
          <View key={index} style={styles.sectionCard}>
            <View style={styles.sectionHeader}>
              <Icon name={section.icon} size={20} color={colors.primary} />
              <Text style={styles.sectionTitle}>{section.title}</Text>
            </View>
            {section.content && (
              <Text style={styles.sectionContent}>{section.content}</Text>
            )}
            {section.bullets && (
              <View style={styles.bulletList}>
                {section.bullets.map((bullet, idx) => (
                  <View key={idx} style={styles.bulletItem}>
                    <Text style={styles.bulletPoint}>•</Text>
                    <Text style={styles.bulletText}>{bullet}</Text>
                  </View>
                ))}
              </View>
            )}
          </View>
        ))}

        {/* Timeline */}
        <View style={styles.timelineSection}>
          <Text style={styles.timelineTitle}>Roadmap 2025-2026</Text>
        <View style={styles.timeline}>
          <View style={styles.timelineItem}>
            <View style={[styles.timelineDot, styles.timelineDotActive]} />
            <View style={styles.timelineContent}>
              <Text style={styles.timelineDate}>Q4 2025 · 🇻🇪</Text>
              <Text style={styles.timelineText}>Lanzamiento en Venezuela: P2P completo. Fundador pivotó el primer mercado principal hacia Argentina tras rechazo de entrada en Venezuela.</Text>
            </View>
          </View>
          <View style={styles.timelineItem}>
            <View style={styles.timelineDot} />
            <View style={styles.timelineContent}>
              <Text style={styles.timelineDate}>Q1 2026 · 🚀</Text>
              <Text style={styles.timelineText}>Alianzas Onramp, recargas automáticas y primera preventa oficial de $CONFIO.</Text>
            </View>
          </View>
          <View style={styles.timelineItem}>
            <View style={styles.timelineDot} />
            <View style={styles.timelineContent}>
              <Text style={styles.timelineDate}>Q2 2026 · 🇦🇷</Text>
              <Text style={styles.timelineText}>Lanzamiento en Argentina con métodos de pago locales.</Text>
            </View>
          </View>
          <View style={styles.timelineItem}>
            <View style={styles.timelineDot} />
            <View style={styles.timelineContent}>
              <Text style={styles.timelineDate}>Q3 2026 · 💎</Text>
              <Text style={styles.timelineText}>Segunda preventa de $CONFIO durante el crecimiento en Argentina.</Text>
            </View>
          </View>
          <View style={styles.timelineItem}>
            <View style={styles.timelineDot} />
            <View style={styles.timelineContent}>
              <Text style={styles.timelineDate}>Q4 2026 · 🇧🇴</Text>
              <Text style={styles.timelineText}>Expansión a Bolivia y consolidación regional.</Text>
            </View>
          </View>
        </View>
      </View>

        {/* CTA */}
        <View style={styles.ctaSection}>
          <Text style={styles.ctaTitle}>¿Listo para ser parte del cambio?</Text>
          <Text style={styles.ctaSubtitle}>
            Gana más $CONFIO invitando amigos y guiándolos en su primera operación
          </Text>
          <TouchableOpacity 
            style={styles.ctaButton}
            onPress={() => navigation.navigate('Achievements')}
          >
            <Text style={styles.ctaButtonText}>Ver programa de referidos</Text>
            <Icon name="arrow-right" size={20} color="#fff" />
          </TouchableOpacity>
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
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
  },
  headerSpacer: {
    width: 40,
  },
  scrollView: {
    flex: 1,
  },
  heroSection: {
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
  tokenSymbol: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#fff',
  },
  heroTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 8,
    textAlign: 'center',
  },
  heroSubtitle: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
  },
  visionCard: {
    marginHorizontal: 16,
    marginBottom: 24,
    backgroundColor: colors.violetLight,
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.violet,
  },
  visionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
    marginTop: 12,
    marginBottom: 12,
  },
  visionText: {
    fontSize: 15,
    color: colors.dark,
    textAlign: 'center',
    lineHeight: 24,
    fontStyle: 'italic',
  },
  visionAuthor: {
    fontSize: 14,
    color: '#6B7280',
    marginTop: 12,
    fontWeight: '600',
  },
  statsContainer: {
    paddingHorizontal: 16,
    marginBottom: 24,
  },
  statsTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 16,
    textAlign: 'center',
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
    color: '#6B7280',
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
  statLinksRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 12,
  },
  statLinkButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingVertical: 7,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: '#E8F7F0',
  },
  statLinkButtonDisabled: {
    backgroundColor: '#F3F4F6',
  },
  statLinkText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.primary,
  },
  statLinkTextDisabled: {
    color: '#9CA3AF',
  },
  sectionCard: {
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
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.dark,
  },
  sectionContent: {
    fontSize: 14,
    color: '#4B5563',
    lineHeight: 20,
  },
  bulletList: {
    marginTop: 8,
  },
  bulletItem: {
    flexDirection: 'row',
    marginBottom: 8,
  },
  bulletPoint: {
    fontSize: 14,
    color: colors.primary,
    marginRight: 8,
    fontWeight: 'bold',
  },
  bulletText: {
    flex: 1,
    fontSize: 14,
    color: '#4B5563',
  },
  timelineSection: {
    marginHorizontal: 16,
    marginBottom: 24,
  },
  timelineTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 20,
    textAlign: 'center',
  },
  timeline: {
    paddingLeft: 20,
  },
  timelineItem: {
    flexDirection: 'row',
    marginBottom: 24,
    position: 'relative',
  },
  timelineDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: '#E5E7EB',
    marginRight: 16,
    marginTop: 2,
  },
  timelineDotCompleted: {
    backgroundColor: colors.primary,
  },
  timelineDotActive: {
    backgroundColor: colors.violet,
  },
  timelineContent: {
    flex: 1,
  },
  timelineDate: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
    fontWeight: '600',
  },
  timelineText: {
    fontSize: 14,
    color: colors.dark,
  },
  ctaSection: {
    marginHorizontal: 16,
    marginBottom: 24,
    backgroundColor: colors.primaryLight,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
  },
  ctaTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
    marginBottom: 8,
    textAlign: 'center',
  },
  ctaSubtitle: {
    fontSize: 14,
    color: '#4B5563',
    marginBottom: 20,
    textAlign: 'center',
  },
  ctaButton: {
    flexDirection: 'row',
    backgroundColor: colors.primary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 24,
    alignItems: 'center',
    gap: 8,
  },
  ctaButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  bottomPadding: {
    height: 40,
  },
});
