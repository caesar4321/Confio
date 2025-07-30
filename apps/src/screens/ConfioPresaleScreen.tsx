import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Platform, Image, SafeAreaView, Alert, ActivityIndicator } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useQuery } from '@apollo/client';
import { GET_ALL_PRESALE_PHASES, GET_ACTIVE_PRESALE } from '../apollo/queries';
import { formatNumber } from '../utils/numberFormatting';
import { useCountry } from '../contexts/CountryContext';

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

type ConfioPresaleScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ConfioPresaleScreen = () => {
  const navigation = useNavigation<ConfioPresaleScreenNavigationProp>();
  const { selectedCountry } = useCountry();
  
  // Fetch presale phases from server
  const { data, loading, error } = useQuery(GET_ALL_PRESALE_PHASES, {
    fetchPolicy: 'cache-and-network',
  });
  
  // Also fetch active presale to check if any phase is active
  const { data: activePresaleData } = useQuery(GET_ACTIVE_PRESALE, {
    fetchPolicy: 'cache-and-network',
  });

  // Use server data
  const presalePhases = data?.allPresalePhases ? data.allPresalePhases.map((phase: any) => ({
    phase: `Fase ${phase.phaseNumber}`,
    title: phase.name,
    price: `${parseFloat(phase.pricePerToken).toFixed(2)} cUSD`,
    unit: '$CONFIO',
    goal: phase.goalAmount >= 1000000 ? `$${phase.goalAmount / 1000000}M` : `$${phase.goalAmount / 1000}K`,
    target: phase.targetAudience,
    location: phase.locationEmoji,
    status: phase.status || 'upcoming',
    description: phase.description.split('.')[0], // Take first sentence
    vision: phase.visionPoints || []
  })) : [];

  const getStatusColor = (status: string) => {
    switch(status) {
      case 'coming_soon': return colors.secondary;
      case 'active': return colors.primary;
      case 'upcoming': return colors.accent;
      case 'completed': return '#17a2b8';
      case 'paused': return '#dc3545';
      default: return '#9CA3AF';
    }
  };

  const getStatusText = (status: string) => {
    switch(status) {
      case 'coming_soon': return 'Próximamente';
      case 'active': return 'Activa';
      case 'upcoming': return 'Siguiente';
      case 'completed': return 'Completada';
      case 'paused': return 'Pausada';
      default: return 'Pendiente';
    }
  };

  const handleJoinWaitlist = () => {
    Alert.alert(
      'Lista de Espera',
      'Te notificaremos cuando la preventa esté disponible. ¡Mantente atento!',
      [{ text: 'Entendido', style: 'default' }]
    );
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Preventa $CONFIO</Text>
          <View style={styles.headerSpacer} />
        </View>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.secondary} />
          <Text style={styles.loadingText}>Cargando fases de preventa...</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (error || !data?.allPresalePhases || data.allPresalePhases.length === 0) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Preventa $CONFIO</Text>
          <View style={styles.headerSpacer} />
        </View>
        <View style={styles.errorContainer}>
          <Icon name="alert-circle" size={48} color={colors.secondary} />
          <Text style={styles.errorText}>No se pudieron cargar las fases de preventa</Text>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.errorButton}>
            <Text style={styles.errorButtonText}>Volver</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Preventa $CONFIO</Text>
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
          <Text style={styles.heroTitle}>Preventa Exclusiva de $CONFIO</Text>
          <Text style={styles.heroSubtitle}>
            Sé parte del futuro financiero que estamos construyendo para nuestra gente
          </Text>
          
          <View style={styles.comingSoonBadge}>
            <Text style={styles.comingSoonText}>🚀 Lanzamiento Q1 2026</Text>
          </View>
        </View>

        {/* Vision & Future */}
        <View style={styles.benefitsSection}>
          <Text style={styles.sectionTitle}>El Futuro que Construimos Juntos</Text>
          
          <View style={styles.benefitsList}>
            <View style={styles.benefitItem}>
              <Icon name="heart" size={24} color={colors.secondary} />
              <View style={styles.benefitContent}>
                <Text style={styles.benefitTitle}>Tu Dinero, Siempre Seguro</Text>
                <Text style={styles.benefitDescription}>
                  Una moneda digital que proteges tú mismo, sin bancos que te limiten o te cobren comisiones abusivas
                </Text>
              </View>
            </View>
            
            <View style={styles.benefitItem}>
              <Icon name="zap" size={24} color={colors.secondary} />
              <View style={styles.benefitContent}>
                <Text style={styles.benefitTitle}>Pagos en Segundos</Text>
                <Text style={styles.benefitDescription}>
                  Envía dinero a tu familia o cobra por tu trabajo al instante, sin esperas ni papeleos
                </Text>
              </View>
            </View>
            
            <View style={styles.benefitItem}>
              <Icon name="sunrise" size={24} color={colors.secondary} />
              <View style={styles.benefitContent}>
                <Text style={styles.benefitTitle}>Un Nuevo Amanecer Financiero</Text>
                <Text style={styles.benefitDescription}>
                  Crecemos paso a paso, país por país, construyendo la economía del futuro desde nuestras raíces
                </Text>
              </View>
            </View>
          </View>
        </View>

        {/* Presale Phases */}
        <View style={styles.phasesSection}>
          <Text style={styles.sectionTitle}>Fases de la Preventa</Text>
          
          {presalePhases.map((phase, index) => (
            <View key={index} style={styles.phaseCard}>
              <View style={styles.phaseHeader}>
                <View style={styles.phaseInfo}>
                  <Text style={styles.phaseNumber}>{phase.phase}</Text>
                  <Text style={styles.phaseTitle}>{phase.title}</Text>
                </View>
                <View style={[styles.statusBadge, { backgroundColor: getStatusColor(phase.status) }]}>
                  <Text style={styles.statusText}>{getStatusText(phase.status)}</Text>
                </View>
              </View>
              
              <Text style={styles.phaseDescription}>{phase.description}</Text>
              
              <View style={styles.phaseDetails}>
                <View style={styles.priceInfo}>
                  <Text style={styles.priceLabel}>Precio</Text>
                  <Text style={styles.priceValue}>{phase.price}</Text>
                  <Text style={styles.priceUnit}>por {phase.unit}</Text>
                </View>
                <View style={styles.goalInfo}>
                  <Text style={styles.goalLabel}>Meta</Text>
                  <Text style={styles.goalValue}>{phase.goal}</Text>
                </View>
                <View style={styles.targetInfo}>
                  <Text style={styles.targetLabel}>Objetivo</Text>
                  <Text style={styles.targetValue}>{phase.target}</Text>
                </View>
              </View>
              
              <View style={styles.locationContainer}>
                <Text style={styles.locationText}>{phase.location}</Text>
              </View>
              
              <View style={styles.visionTags}>
                {phase.vision.map((item, idx) => (
                  <View key={idx} style={styles.visionTag}>
                    <Text style={styles.visionTagText}>{item}</Text>
                  </View>
                ))}
              </View>
            </View>
          ))}
        </View>

        {/* CTA Section */}
        <View style={styles.ctaSection}>
          <Text style={styles.ctaTitle}>¿Listo para hacer historia?</Text>
          <Text style={styles.ctaSubtitle}>
            Únete a miles de personas que ya creen en un futuro financiero mejor
          </Text>
          
          {activePresaleData?.activePresalePhase ? (
            <TouchableOpacity 
              style={styles.ctaButton}
              onPress={() => navigation.navigate('ConfioPresaleParticipate')}
            >
              <Icon name="star" size={20} color="#fff" />
              <Text style={styles.ctaButtonText}>Participar en la Preventa</Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity 
              style={styles.ctaButton}
              onPress={handleJoinWaitlist}
            >
              <Icon name="bell" size={20} color="#fff" />
              <Text style={styles.ctaButtonText}>Notificar</Text>
            </TouchableOpacity>
          )}
          
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
    marginBottom: 16,
    lineHeight: 24,
  },
  comingSoonBadge: {
    backgroundColor: colors.secondary,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  comingSoonText: {
    color: '#fff',
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
    color: '#6B7280',
    lineHeight: 20,
  },
  phasesSection: {
    paddingHorizontal: 20,
    paddingBottom: 32,
  },
  phaseCard: {
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
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  phaseDescription: {
    fontSize: 14,
    color: '#6B7280',
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
    color: '#9CA3AF',
    marginBottom: 4,
  },
  priceValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.secondary,
  },
  priceUnit: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 2,
  },
  goalInfo: {
    flex: 1,
  },
  goalLabel: {
    fontSize: 12,
    color: '#9CA3AF',
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
    color: '#9CA3AF',
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
    color: '#6B7280',
    marginBottom: 24,
    textAlign: 'center',
    lineHeight: 24,
  },
  ctaButton: {
    flexDirection: 'row',
    backgroundColor: colors.secondary,
    paddingHorizontal: 32,
    paddingVertical: 16,
    borderRadius: 24,
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  ctaButtonText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#fff',
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
    color: '#6B7280',
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
    color: '#6B7280',
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
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
});