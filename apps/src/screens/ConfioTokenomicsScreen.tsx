import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, SafeAreaView, Image } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { formatNumber } from '../utils/numberFormatting';
import { useCountry } from '../contexts/CountryContext';
import CONFIOLogo from '../assets/png/CONFIO.png';

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

type ConfioTokenomicsScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ConfioTokenomicsScreen = () => {
  const navigation = useNavigation<ConfioTokenomicsScreenNavigationProp>();
  const { selectedCountry } = useCountry();
  
  // Use the app's selected country for formatting, fallback to Venezuela
  const countryCode = selectedCountry?.[2] || 'VE';
  const formatWithLocale = (num: number, options = {}) => 
    formatNumber(num, countryCode, { minimumFractionDigits: 0, maximumFractionDigits: 0, ...options });

  const totalSupply = 1000000000; // 1 billion
  const founderTokens = 950000000; // 95% - Majority control
  const presaleTokens = 50000000;  // 5% - Community investment opportunity

  const tokenomicsData = [
    {
      category: 'Fundador y Equipo',
      percentage: '95%',
      amount: formatWithLocale(founderTokens),
      description: 'Mayoría absoluta del fundador, como cualquier startup exitosa',
      color: colors.secondary,
      icon: 'user'
    },
    {
      category: 'Preventa Comunitaria',
      percentage: '5%',
      amount: formatWithLocale(presaleTokens),
      description: 'Oportunidad de inversión para la comunidad, no para VCs',
      color: colors.primary,
      icon: 'users'
    }
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
      color: '#ef4444'
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
      color: '#f59e0b'
    },
    {
      title: 'Confío es Diferente',
      subtitle: 'Para gente común',
      benefits: [
        'Cualquier persona puede participar',
        'Interfaz simple y en español',
        'Fundador comprometido y transparente',
        'Inversión desde montos pequeños',
        'Oportunidad que nunca has tenido'
      ],
      icon: 'heart',
      color: colors.primary
    }
  ];

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Distribución $CONFIO</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Hero Section */}
        <View style={styles.heroSection}>
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
                <View style={styles.distributionInfo}>
                  <Icon name={item.icon as any} size={24} color={item.color} />
                  <View style={styles.distributionText}>
                    <Text style={styles.distributionCategory}>{item.category}</Text>
                    <Text style={styles.distributionDescription}>{item.description}</Text>
                  </View>
                </View>
                <View style={styles.distributionStats}>
                  <Text style={[styles.distributionPercentage, { color: item.color }]}>
                    {item.percentage}
                  </Text>
                  <Text style={styles.distributionAmount}>{item.amount} monedas</Text>
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
              Por primera vez en la historia, puedes invertir en un proyecto prometedor sin ser millonario, 
              sin entender tecnología complicada, y sin conexiones especiales. 
              Solo necesitas creer en el futuro financiero de nuestra gente.
            </Text>
          </View>
        </View>

        {/* Comparison Section */}
        <View style={styles.comparisonSection}>
          <Text style={styles.sectionTitle}>¿Por Qué la Gente Común Nunca Puede Invertir?</Text>
          
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
            <Text style={styles.futureTitle}>Como Cualquier Startup Exitosa</Text>
            <Text style={styles.futureDescription}>
              El fundador mantiene el 95% (como Apple, Facebook, etc. en sus inicios), 
              mientras que el 5% se ofrece a la comunidad en condiciones que normalmente 
              solo tienen los VCs. Una oportunidad única para invertir en el futuro 
              financiero de Latinoamérica.
            </Text>
          </View>
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
    backgroundColor: colors.secondary,
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
    backgroundColor: colors.violetLight,
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
    color: colors.dark,
    marginBottom: 8,
    textAlign: 'center',
  },
  heroSubtitle: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 24,
  },
  supplySection: {
    paddingHorizontal: 20,
    paddingVertical: 24,
  },
  supplyCard: {
    backgroundColor: '#fff',
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
    color: '#6B7280',
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
    color: '#6B7280',
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
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
  },
  distributionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  distributionInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    marginRight: 16,
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
    color: '#6B7280',
    lineHeight: 20,
  },
  distributionStats: {
    alignItems: 'flex-end',
  },
  distributionPercentage: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  distributionAmount: {
    fontSize: 12,
    color: '#6B7280',
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
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 22,
  },
  comparisonSection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  comparisonCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#E5E7EB',
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
    color: '#6B7280',
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
    color: '#6B7280',
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
    color: '#6B7280',
    textAlign: 'center',
    lineHeight: 22,
  },
  bottomPadding: {
    height: 40,
  },
});