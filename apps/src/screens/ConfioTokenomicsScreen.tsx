import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Image, Linking } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { formatNumber } from '../utils/numberFormatting';
import { useCountry } from '../contexts/CountryContext';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { colors } from '../config/theme';
import { Header } from '../navigation/Header';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';

type ConfioTokenomicsScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ConfioTokenomicsScreen = () => {
  const navigation = useNavigation<ConfioTokenomicsScreenNavigationProp>();
  const { selectedCountry } = useCountry();

  // Use the app's selected country for formatting, fallback to Venezuela
  const countryCode = selectedCountry?.[2] || 'VE';
  const formatWithLocale = (num: number, options = {}) =>
    formatNumber(num, countryCode, { minimumFractionDigits: 0, maximumFractionDigits: 0, ...options });

  const totalSupply = 1000000000; // 1 billion

  const presaleTokens = 74_000_000; // 7.40%
  const rewardsTokens = 7_400_000; // 0.74%
  const culturalTokens = 15_000_000; // 1.50%
  const coBuilderTokens = 10_000_000; // 1.00%
  const founderTokens = 893_600_000; // 89.36%
  const founderAndTeamTokens = founderTokens + coBuilderTokens; // 90.36%

  const pct = (tokens: number) => `${((tokens / totalSupply) * 100).toFixed(2)}%`;

  const tokenomicsData = [
    {
      category: 'Fundador y equipo',
      tokens: founderAndTeamTokens,
      percentage: pct(founderAndTeamTokens),
      description:
        'Reserva del fundador (como en cualquier startup que inicia con 100%) para operar y escalar: nómina, expansión y cumplimiento. Bloqueo total hasta el lanzamiento en DEX; luego se libera mes a mes durante 36 meses. Incluye el 1% destinado al equipo clave, que se libera por partes iguales durante 24 meses tras el lanzamiento en DEX.',
      color: colors.secondary,
      icon: 'shield',
    },
    {
      category: 'Preventa comunitaria',
      tokens: presaleTokens,
      percentage: pct(presaleTokens),
      description:
        '74M CONFIO en una sola preventa continua: el precio comienza en $0.20 y sube automáticamente con cada compra, hasta un máximo de $1.30. Quien participa antes obtiene mejor precio. Los tokens se desbloquean con el lanzamiento en DEX.',
      color: colors.primary,
      icon: 'users',
    },
    {
      category: 'Recompensas en uso',
      tokens: rewardsTokens,
      percentage: pct(rewardsTokens),
      description:
        '0.74% (7.4M CONFIO) para “Invita y gana”. Pago inmediato on-chain en la primera recarga o ahorro real de US$20 ($5 + $5). El monto de tokens se calcula al precio vigente de la preventa.',
      color: colors.accent,
      icon: 'gift',
    },
    {
      category: 'Invitación cultural',
      tokens: culturalTokens,
      percentage: pct(culturalTokens),
      description:
        '1.5% (hasta 2.5% opcional) para agradecer apoyos reales 2023–2026. Bloqueo total hasta el lanzamiento en DEX; luego liberado de forma gradual en 3 meses.',
      color: colors.offRampIcon,
      icon: 'heart',
    },
  ];

  const comparisonData = [
    {
      title: 'Startups Tradicionales',
      subtitle: 'Solo para VCs',
      problems: [
        'Solo VCs y ricos pueden invertir',
        'Persona común excluida totalmente',
        'Mínimos de $50K - $1M+',
        'Requiere conexiones especiales',
        'Proceso complejo y excluyente'
      ],
      icon: 'briefcase',
      color: colors.danger
    },
    {
      title: 'Proyectos Cripto',
      subtitle: 'Solo para expertos en cripto',
      problems: [
        'Necesitas aprender cómo funcionan las carteras digitales',
        'Páginas web muy confusas y difíciles',
        'Muchas estafas que te roban el dinero',
        'Los precios cambian locamente cada día',
        'Hablan en inglés con palabras raras'
      ],
      icon: 'trending-down',
      color: colors.offRampIcon
    },
    {
      title: 'Confío es Diferente',
      subtitle: 'Para gente común',
      benefits: [
        'Cualquier persona puede participar',
        'Interfaz simple y en español',
        'Fundador comprometido y transparente',
        'Participa desde montos pequeños',
        'Reglas públicas que no cambian'
      ],
      icon: 'heart',
      color: colors.primary
    }
  ];

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Distribución $CONFIO"
        backgroundColor={colors.secondary}
        isLight
        showBackButton
      />

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Hero Section */}
        <View style={styles.heroSection}>
          <BrandFieldBackground id="tokenomicsField" fromColor={colors.secondary} toColor={colors.secondaryDark} ringCy="22%" ringR={80} ringWidth={20} />
          <View style={styles.heroInner}>
          <View style={styles.tokenIcon}>
            <Image
              source={CONFIOLogo}
              style={styles.tokenImage}
              resizeMode="contain"
            />
          </View>
          <Text style={styles.heroTitle}>Transparencia Total</Text>
          <Text style={styles.heroSubtitle}>
            Así se distribuyen las {formatWithLocale(totalSupply)} monedas de $CONFIO
          </Text>
          </View>
        </View>

        {/* Total Supply */}
        <View style={styles.supplySection}>
          <View style={styles.supplyCard}>
            <Text style={styles.supplyLabel}>Suministro Total</Text>
            <Text style={styles.supplyValue}>{formatWithLocale(totalSupply)}</Text>
            <Text style={styles.supplyUnit}>$CONFIO</Text>
          </View>
        </View>

        {/* Distribution */}
        <View style={styles.distributionSection}>
          <Text style={styles.sectionTitle}>Distribución de Monedas</Text>

          {tokenomicsData.map((item, index) => (
            <View key={index} style={styles.distributionCard}>
              <View style={styles.distributionHeader}>
                <Icon name={item.icon as any} size={28} color={item.color} />
                <View style={styles.distributionText}>
                  <Text style={styles.distributionCategory}>{item.category}</Text>
                  <Text style={styles.distributionDescription}>{item.description}</Text>
                </View>
              </View>
              <View style={styles.distributionStats}>
                <View style={styles.statBlock}>
                  <Text style={styles.statLabel}>Porcentaje</Text>
                  <Text style={[styles.distributionPercentage, { color: item.color }]}>
                    {item.percentage}
                  </Text>
                </View>
                <View style={styles.statBlock}>
                  <Text style={styles.statLabel}>Tokens</Text>
                  <Text style={styles.distributionAmount}>
                    {formatWithLocale(item.tokens)} CONFIO
                  </Text>
                </View>
              </View>
            </View>
          ))}
        </View>

        {/* Philosophy Section */}
        <View style={styles.philosophySection}>
          <Text style={styles.sectionTitle}>¿Por Qué Este Modelo?</Text>
          <View style={styles.philosophyCard}>
            <Icon name="heart" size={24} color={colors.secondary} />
            <Text style={styles.philosophyTitle}>La Primera Oportunidad Real para Ti</Text>
            <Text style={styles.philosophyDescription}>
              Por primera vez, puedes ser parte de un proyecto desde el principio sin ser millonario,
              sin entender tecnología complicada, y sin conexiones especiales.
              Solo necesitas creer en el futuro financiero de nuestra gente.
            </Text>
          </View>
        </View>

        {/* Comparison Section */}
        <View style={styles.comparisonSection}>
          <Text style={styles.sectionTitle}>¿Por Qué Esto Casi Nunca Llega a la Gente Común?</Text>

          {comparisonData.map((comparison, index) => (
            <View key={index} style={styles.comparisonCard}>
              <View style={styles.comparisonHeader}>
                <Icon name={comparison.icon as any} size={24} color={comparison.color} />
                <View style={styles.comparisonTitleContainer}>
                  <Text style={[styles.comparisonTitle, { color: comparison.color }]}>
                    {comparison.title}
                  </Text>
                  <Text style={styles.comparisonSubtitle}>
                    {comparison.subtitle}
                  </Text>
                </View>
              </View>

              <View style={styles.comparisonList}>
                {(comparison.problems || comparison.benefits)?.map((item, idx) => (
                  <View key={idx} style={styles.comparisonItem}>
                    <Icon
                      name={comparison.benefits ? "check" : "x"}
                      size={16}
                      color={comparison.color}
                    />
                    <Text style={styles.comparisonText}>{item}</Text>
                  </View>
                ))}
              </View>
            </View>
          ))}
        </View>

        {/* Future Plans */}
        <View style={styles.futureSection}>
          <Text style={styles.sectionTitle}>Distribución Justa y Transparente</Text>
          <View style={styles.futureCard}>
            <Icon name="shield" size={24} color={colors.accent} />
            <Text style={styles.futureTitle}>Resumen rápido</Text>
            <Text style={styles.futureDescription}>
              - Suministro total: {formatWithLocale(totalSupply)} CONFIO.{'\n'}
              - Preventa: 74M CONFIO (7.4%) en una sola preventa continua — el precio sube automáticamente con cada compra, de $0.20 a $1.30. Desbloqueo con el lanzamiento en DEX.{'\n'}
              - Fundador y equipo: 90.36% como reserva típica de fundador para operar y expandir. Bloqueo total hasta el lanzamiento en DEX; luego se libera mes a mes durante 36 meses. Incluye 1% para equipo clave que se libera en partes iguales durante 24 meses tras lanzamiento en DEX.{'\n'}
              - Cultura LATAM: 1.5% de agradecimiento. Bloqueo total hasta el lanzamiento en DEX; luego liberado gradualmente en 3 meses.{'\n'}
              - Recompensas: 7.4M CONFIO on-chain en la primera recarga o ahorro real (≥ US$20), calculadas al precio vigente de la preventa.{'\n'}
              - Sin VCs ni pools ocultos. Todo está documentado y visible.{'\n'}
              - $CONFIO es un token de acceso al ecosistema: no representa acciones, dividendos ni derechos sobre ingresos de Confío.
            </Text>
            <TouchableOpacity
              style={styles.linkButton}
              onPress={() =>
                Linking.openURL(
                  'https://medium.com/confio4world/tokenomics-oficial-de-conf%C3%ADo-versi%C3%B3n-2025-comunidad-latam-152815f9bcc9',
                )
              }
            >
              <Text style={styles.linkButtonText}>Ver tokenomics detallado</Text>
              <Icon name="external-link" size={16} color={colors.white} style={{ marginLeft: 6 }} />
            </TouchableOpacity>
          </View>
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
    lineHeight: 24,
  },
  supplySection: {
    paddingHorizontal: 20,
    paddingVertical: 24,
  },
  supplyCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    borderWidth: 2,
    borderColor: colors.secondary,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 3,
  },
  supplyLabel: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: 8,
  },
  supplyValue: {
    fontSize: 32,
    fontWeight: 'bold',
    color: colors.secondary,
    marginBottom: 4,
  },
  supplyUnit: {
    fontSize: 16,
    color: colors.text.secondary,
    fontWeight: '600',
  },
  distributionSection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 20,
    textAlign: 'center',
  },
  distributionCard: {
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
    marginBottom: 12,
  },
  distributionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  distributionText: {
    marginLeft: 12,
    flex: 1,
  },
  distributionCategory: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 4,
  },
  distributionDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 20,
  },
  distributionStats: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 16,
    borderTopWidth: 1,
    borderColor: colors.border,
    paddingTop: 12,
  },
  statBlock: {
    flex: 1,
    paddingRight: 12,
  },
  statLabel: {
    fontSize: 12,
    color: colors.text.light,
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  distributionPercentage: {
    fontSize: 22,
    fontWeight: 'bold',
  },
  distributionAmount: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.dark,
  },
  philosophySection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  philosophyCard: {
    backgroundColor: colors.violetLight,
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
  },
  philosophyTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
    marginVertical: 12,
    textAlign: 'center',
  },
  philosophyDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 22,
  },
  comparisonSection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  comparisonCard: {
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
  comparisonHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  comparisonTitleContainer: {
    marginLeft: 12,
    flex: 1,
  },
  comparisonTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 2,
  },
  comparisonSubtitle: {
    fontSize: 12,
    color: colors.text.secondary,
    fontStyle: 'italic',
  },
  comparisonList: {
    gap: 12,
  },
  comparisonItem: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  comparisonText: {
    fontSize: 14,
    color: colors.text.secondary,
    marginLeft: 12,
    flex: 1,
    lineHeight: 20,
  },
  futureSection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  futureCard: {
    backgroundColor: colors.neutralDark,
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
  },
  futureTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
    marginVertical: 12,
    textAlign: 'center',
  },
  futureDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 22,
  },
  linkButton: {
    marginTop: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.secondary,
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 14,
  },
  linkButtonText: {
    color: colors.white,
    fontSize: 16,
    fontWeight: '600',
  },
  bottomPadding: {
    height: 40,
  },
});
