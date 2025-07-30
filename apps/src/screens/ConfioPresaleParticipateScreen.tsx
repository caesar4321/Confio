import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, SafeAreaView, Image, TextInput, Alert } from 'react-native';
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

type ConfioPresaleParticipateScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ConfioPresaleParticipateScreen = () => {
  const navigation = useNavigation<ConfioPresaleParticipateScreenNavigationProp>();
  const { selectedCountry } = useCountry();
  
  const [amount, setAmount] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  
  // Use the app's selected country for formatting
  const countryCode = selectedCountry?.[2] || 'VE';
  const formatWithLocale = (num: number, options = {}) => 
    formatNumber(num, countryCode, { minimumFractionDigits: 2, maximumFractionDigits: 2, ...options });

  const presalePrice = 0.25; // cUSD per CONFIO
  const minAmount = 10; // Minimum 10 cUSD
  const maxAmount = 1000; // Maximum 1000 cUSD for Fase 1

  const calculateTokens = (cUsdAmount: number) => {
    return cUsdAmount / presalePrice;
  };

  const parsedAmount = parseFloat(amount) || 0;
  const tokensReceived = calculateTokens(parsedAmount);
  const isValidAmount = parsedAmount >= minAmount && parsedAmount <= maxAmount;

  const executeSwap = async () => {
    setIsLoading(true);
    
    // Simulate swap transaction
    setTimeout(() => {
      setIsLoading(false);
      Alert.alert(
        '¡Intercambio Exitoso!',
        `Has intercambiado ${amount} cUSD por ${formatWithLocale(tokensReceived, { minimumFractionDigits: 2 })} $CONFIO.\n\nLas monedas están en tu cuenta pero permanecerán bloqueadas mientras construimos juntos.`,
        [
          {
            text: 'Ver Mi Cuenta',
            onPress: () => {
              navigation.navigate('BottomTabs', { screen: 'Home' });
            },
          },
        ]
      );
      setAmount('');
    }, 3000);
  };

  const handleSwap = async () => {
    if (!isValidAmount) {
      Alert.alert('Error', `Monto debe estar entre ${minAmount} y ${formatWithLocale(maxAmount)} cUSD`);
      return;
    }

    Alert.alert(
      'Confirmar Intercambio',
      `¿Intercambiar ${amount} cUSD por ${formatWithLocale(tokensReceived, { minimumFractionDigits: 2 })} $CONFIO?`,
      [
        {
          text: 'Cancelar',
          style: 'cancel',
        },
        {
          text: 'Confirmar',
          onPress: () => executeSwap(),
        },
      ]
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Intercambiar por $CONFIO</Text>
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
          <Text style={styles.heroTitle}>Preventa Fase 1</Text>
          <Text style={styles.heroSubtitle}>
            Raíces Fuertes - Donde todo comienza 🌱
          </Text>
          
          <View style={styles.priceBadge}>
            <Text style={styles.priceText}>0.25 cUSD por $CONFIO</Text>
          </View>
        </View>

        {/* Current Status */}
        <View style={styles.statusSection}>
          <View style={styles.statusCard}>
            <Text style={styles.statusTitle}>¡Fase 1 Activa!</Text>
            <Text style={styles.statusDescription}>
              ¡La Fase 1 está activa! Puedes intercambiar cUSD por $CONFIO al precio más bajo de la historia. 
              Oferta limitada mientras tengamos monedas disponibles.
            </Text>
            <View style={styles.progressContainer}>
              <Text style={styles.progressLabel}>Recaudado en Fase 1</Text>
              <Text style={styles.progressAmount}>{formatWithLocale(650000, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} cUSD</Text>
              <Text style={styles.progressGoal}>Meta: {formatWithLocale(1000000, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} cUSD</Text>
              
              <View style={styles.progressBarContainer}>
                <View style={styles.progressBar}>
                  <View style={[styles.progressFill, { width: '65%' }]} />
                </View>
                <Text style={styles.progressPercentage}>65% completado</Text>
              </View>
              
              <View style={styles.participantStats}>
                <Icon name="users" size={14} color={colors.primary} />
                <Text style={styles.participantText}>
                  <Text style={styles.participantCount}>1,234</Text> personas ya participaron
                </Text>
              </View>
            </View>
          </View>
        </View>

        {/* Swap Interface */}
        <View style={styles.swapSection}>
          <Text style={styles.sectionTitle}>Intercambiar cUSD por $CONFIO</Text>
          
          <View style={styles.swapCard}>
            <View style={styles.inputContainer}>
              <Text style={styles.inputLabel}>Cantidad de cUSD</Text>
              <View style={styles.inputWrapper}>
                <TextInput
                  style={styles.textInput}
                  value={amount}
                  onChangeText={setAmount}
                  placeholder="Ej: 100"
                  keyboardType="numeric"
                  placeholderTextColor="#9CA3AF"
                />
                <Text style={styles.inputSuffix}>cUSD</Text>
              </View>
              <Text style={styles.inputHelper}>
                Mínimo: {minAmount} cUSD • Máximo: {formatWithLocale(maxAmount)} cUSD
              </Text>
            </View>

            {parsedAmount > 0 && (
              <View style={styles.resultContainer}>
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>Recibirás:</Text>
                  <Text style={styles.resultValue}>
                    {formatWithLocale(tokensReceived, { minimumFractionDigits: 2 })} $CONFIO
                  </Text>
                </View>
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>Precio por moneda:</Text>
                  <Text style={styles.resultValue}>0.25 cUSD</Text>
                </View>
                {!isValidAmount && (
                  <Text style={styles.errorText}>
                    Monto debe estar entre {minAmount} y {formatWithLocale(maxAmount)} cUSD
                  </Text>
                )}
              </View>
            )}
          </View>
        </View>

        {/* Swap Execution */}
        <View style={styles.swapSection}>
          <TouchableOpacity 
            style={[
              styles.swapButton,
              (!isValidAmount || parsedAmount === 0) && styles.swapButtonDisabled
            ]}
            onPress={handleSwap}
            disabled={!isValidAmount || parsedAmount === 0 || isLoading}
          >
            {isLoading ? (
              <Text style={styles.swapButtonText}>Procesando Intercambio...</Text>
            ) : (
              <>
                <Icon name="refresh-cw" size={20} color="#fff" />
                <Text style={styles.swapButtonText}>Intercambiar Ahora</Text>
              </>
            )}
          </TouchableOpacity>
          
          <View style={styles.lockingNotice}>
            <Icon name="lock" size={16} color="#f59e0b" />
            <Text style={styles.lockingText}>
              <Text style={styles.lockingBold}>Importante:</Text> Las monedas $CONFIO permanecerán bloqueadas hasta que Confío alcance adopción masiva. 
              Esto protege el valor y asegura que construyamos juntos el futuro financiero de Latinoamérica.
            </Text>
          </View>
          
          <View style={styles.riskDisclosure}>
            <Icon name="alert-triangle" size={14} color="#ef4444" />
            <Text style={styles.riskText}>
              <Text style={styles.riskBold}>Inversión de alto riesgo:</Text> Como cualquier negocio nuevo, 
              el éxito no está garantizado. Participa con responsabilidad.
            </Text>
          </View>
        </View>

        {/* Benefits */}
        <View style={styles.benefitsSection}>
          <Text style={styles.sectionTitle}>Beneficios de Participar</Text>
          
          <View style={styles.benefitsList}>
            <View style={styles.benefitItem}>
              <Icon name="star" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Precio más bajo:</Text> 0.25 cUSD por moneda vs precios futuros más altos
              </Text>
            </View>
            
            <View style={styles.benefitItem}>
              <Icon name="users" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Comunidad fundadora:</Text> Serás parte de la base que construye el futuro
              </Text>
            </View>
            
            <View style={styles.benefitItem}>
              <Icon name="shield" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Transparencia total:</Text> Fundador comprometido, sin estafas ni sorpresas
              </Text>
            </View>
            
            <View style={styles.benefitItem}>
              <Icon name="zap" size={20} color={colors.secondary} />
              <Text style={styles.benefitText}>
                <Text style={styles.benefitBold}>Acceso prioritario:</Text> Serás de los primeros cuando lancemos nuevas funciones
              </Text>
            </View>
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
    marginBottom: 16,
    lineHeight: 24,
  },
  priceBadge: {
    backgroundColor: colors.secondary,
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 25,
  },
  priceText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  priceComparison: {
    marginTop: 20,
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 16,
    width: '100%',
    borderWidth: 2,
    borderColor: colors.primary,
  },
  priceComparisonTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    color: colors.dark,
    textAlign: 'center',
    marginBottom: 12,
  },
  priceComparisonRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  priceComparisonItem: {
    flex: 1,
    alignItems: 'center',
  },
  priceComparisonLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
  },
  priceComparisonValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
  },
  priceComparisonValueHighlight: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.primary,
  },
  priceComparisonSubtext: {
    fontSize: 11,
    color: '#6B7280',
  },
  priceComparisonNote: {
    fontSize: 12,
    color: colors.primary,
    textAlign: 'center',
    marginTop: 12,
    fontWeight: '600',
  },
  statusSection: {
    paddingHorizontal: 20,
    paddingVertical: 24,
  },
  statusCard: {
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
  statusTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.dark,
    marginBottom: 12,
  },
  statusDescription: {
    fontSize: 14,
    color: '#6B7280',
    lineHeight: 22,
    marginBottom: 20,
  },
  progressContainer: {
    alignItems: 'center',
  },
  progressLabel: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 4,
  },
  progressAmount: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.primary,
    marginBottom: 2,
  },
  progressGoal: {
    fontSize: 14,
    color: '#6B7280',
    marginBottom: 16,
  },
  progressBarContainer: {
    width: '100%',
    alignItems: 'center',
  },
  progressBar: {
    width: '100%',
    height: 12,
    backgroundColor: '#E5E7EB',
    borderRadius: 6,
    marginBottom: 8,
    overflow: 'hidden',
  },
  progressFill: {
    height: 12,
    backgroundColor: colors.primary,
    borderRadius: 6,
  },
  progressPercentage: {
    fontSize: 12,
    color: colors.primary,
    fontWeight: '600',
  },
  participantStats: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 12,
  },
  participantText: {
    fontSize: 13,
    color: '#6B7280',
  },
  participantCount: {
    fontWeight: 'bold',
    color: colors.primary,
  },
  swapSection: {
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
  swapCard: {
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
  inputContainer: {
    marginBottom: 20,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.dark,
    marginBottom: 8,
  },
  inputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    paddingHorizontal: 16,
    backgroundColor: '#fff',
  },
  textInput: {
    flex: 1,
    paddingVertical: 16,
    fontSize: 16,
    color: colors.dark,
  },
  inputSuffix: {
    fontSize: 16,
    color: '#6B7280',
    fontWeight: '600',
    marginLeft: 8,
  },
  inputHelper: {
    fontSize: 12,
    color: '#6B7280',
    marginTop: 4,
  },
  resultContainer: {
    backgroundColor: colors.violetLight,
    borderRadius: 12,
    padding: 16,
  },
  resultRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  resultLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  resultValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.secondary,
  },
  errorText: {
    fontSize: 12,
    color: '#ef4444',
    marginTop: 8,
    textAlign: 'center',
  },
  swapButton: {
    flexDirection: 'row',
    backgroundColor: colors.primary,
    paddingHorizontal: 32,
    paddingVertical: 18,
    borderRadius: 24,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginBottom: 16,
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 5,
  },
  swapButtonDisabled: {
    backgroundColor: '#D1D5DB',
    shadowOpacity: 0,
    elevation: 0,
  },
  swapButtonText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#fff',
  },
  lockingNotice: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#fef3c7',
    borderColor: '#f59e0b',
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 20,
    gap: 12,
  },
  lockingText: {
    flex: 1,
    fontSize: 13,
    color: '#92400e',
    lineHeight: 18,
  },
  lockingBold: {
    fontWeight: 'bold',
    color: '#78350f',
  },
  riskDisclosure: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#fef2f2',
    borderColor: '#ef4444',
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginHorizontal: 20,
    marginTop: 12,
    gap: 8,
  },
  riskText: {
    flex: 1,
    fontSize: 12,
    color: '#7f1d1d',
    lineHeight: 16,
  },
  riskBold: {
    fontWeight: 'bold',
    color: '#991b1b',
  },
  benefitsSection: {
    paddingHorizontal: 20,
    paddingBottom: 24,
  },
  benefitsList: {
    gap: 16,
  },
  benefitItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  benefitText: {
    flex: 1,
    fontSize: 14,
    color: '#6B7280',
    lineHeight: 20,
  },
  benefitBold: {
    fontWeight: 'bold',
    color: colors.dark,
  },
  bottomPadding: {
    height: 40,
  },
});