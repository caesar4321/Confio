import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Platform, Image } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery, gql } from '@apollo/client';
import { useNavigation } from '@react-navigation/native';

const colors = {
  primary: '#34d399',
  primaryLight: '#d1fae5',
  primaryDark: '#10b981',
  secondary: '#8b5cf6',
  secondaryLight: '#e9d5ff',
  accent: '#3b82f6',
  neutral: '#f9fafb',
  neutralDark: '#f3f4f6',
  dark: '#111827',
  violet: '#8b5cf6',
  violetLight: '#ddd6fe',
};

const GET_STATS_SUMMARY = gql`
  query GetStatsSummary {
    statsSummary {
      activeUsers30d
      protectedSavings
      dailyTransactions
    }
  }
`;

export const ConfioTokenInfoScreen = () => {
  const navigation = useNavigation();
  const { data, refetch } = useQuery(GET_STATS_SUMMARY, {
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'cache-first',
    notifyOnNetworkStatusChange: true,
  });

  const formatCompact = (n: number | null | undefined) => {
    if (n == null) return '-';
    const abs = Math.abs(n);
    if (abs >= 1e9) return `${(n / 1e9).toFixed(1).replace(/\.0$/, '')}B`;
    if (abs >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, '')}M`;
    if (abs >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, '')}K`;
    return `${n}`;
  };

  const formatMoney = (n: number | null | undefined) => {
    if (n == null) return '-';
    try {
      return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(n);
    } catch {
      return `${Math.round(n)}`;
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
      title: 'Beneficios para Early Adopters',
      icon: 'star',
      bullets: [
        'Acceso prioritario a nuevas funciones',
        'Poder de voto en decisiones de la plataforma',
        'Recompensas adicionales por referir amigos',
        'Acceso a productos financieros exclusivos',
        'Participación en preventas exclusivas de $CONFIO',
      ],
    },
    {
      title: 'Cómo Ganar Más $CONFIO',
      icon: 'gift',
      bullets: [
        'Completa logros y misiones',
        'Invita amigos con tu código',
        'Realiza intercambios P2P',
        'Verifica tu identidad',
        'Comparte tus logros en redes sociales',
      ],
    },
  ];

  const s = data?.statsSummary;
  const stats = [
    { label: 'Usuarios Activos mensual', value: `${formatCompact(s?.activeUsers30d ?? 0)}`, growth: 'en vivo' },
    { label: 'Ahorros Protegidos', value: `$${formatMoney(s?.protectedSavings ?? 0)} cUSD`, growth: 'en vivo' },
    { label: 'Transacciones Diarias', value: `${formatCompact(s?.dailyTransactions ?? 0)}`, growth: 'en vivo' },
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
                <Text style={styles.statValue}>{stat.value}</Text>
                <Text style={styles.statLabel}>{stat.label}</Text>
                <View style={styles.growthBadge}>
                  <Icon name="trending-up" size={12} color={colors.primary} />
                  <Text style={styles.growthText}>{stat.growth}</Text>
                </View>
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
                <Text style={styles.timelineDate}>Q4 2025</Text>
                <Text style={styles.timelineText}>Lanzamiento en Venezuela</Text>
              </View>
            </View>
            <View style={styles.timelineItem}>
              <View style={styles.timelineDot} />
              <View style={styles.timelineContent}>
                <Text style={styles.timelineDate}>Q1 2026</Text>
                <Text style={styles.timelineText}>Crecimiento en Venezuela y primera preventa de $CONFIO</Text>
              </View>
            </View>
            <View style={styles.timelineItem}>
              <View style={styles.timelineDot} />
              <View style={styles.timelineContent}>
                <Text style={styles.timelineDate}>Q2 2026</Text>
                <Text style={styles.timelineText}>Lanzamiento en Argentina</Text>
              </View>
            </View>
            <View style={styles.timelineItem}>
              <View style={styles.timelineDot} />
              <View style={styles.timelineContent}>
                <Text style={styles.timelineDate}>Q3 2026</Text>
                <Text style={styles.timelineText}>Crecimiento en Argentina y segunda preventa de $CONFIO</Text>
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
    flexDirection: 'row',
    gap: 12,
  },
  statCard: {
    flex: 1,
    backgroundColor: colors.neutral,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
  },
  statValue: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.dark,
  },
  statLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  growthBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: 8,
  },
  growthText: {
    fontSize: 12,
    color: colors.primary,
    fontWeight: '600',
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
