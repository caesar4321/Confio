import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  SafeAreaView,
  Alert,
  Animated,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { getPaymentMethodIcon } from '../utils/paymentMethodIcons';

type ActiveTradeRouteProp = RouteProp<MainStackParamList, 'ActiveTrade'>;
type ActiveTradeNavigationProp = NativeStackNavigationProp<MainStackParamList, 'ActiveTrade'>;

interface ActiveTrade {
  id: string;
  trader: {
    name: string;
    isOnline: boolean;
    verified: boolean;
    lastSeen: string;
    responseTime: string;
  };
  amount: string;
  crypto: string;
  totalBs: string;
  countryCode: string;
  currencyCode: string;
  paymentMethod: string;
  rate: string;
  step: number;
  timeRemaining: number;
  tradeType: 'buy' | 'sell';
  status?: string;
  hasRating?: boolean;
}

export const ActiveTradeScreen: React.FC = () => {
  const navigation = useNavigation<ActiveTradeNavigationProp>();
  const route = useRoute<ActiveTradeRouteProp>();
  const { trade } = route.params;
  
  // Format crypto token for display
  const formatCrypto = (crypto: string): string => {
    if (crypto === 'CUSD' || crypto === 'cusd') return 'cUSD';
    if (crypto === 'CONFIO' || crypto === 'confio') return 'CONFIO';
    return crypto;
  };
  
  const [activeTradeStep, setActiveTradeStep] = useState(trade.step);
  const [timeRemaining, setTimeRemaining] = useState(trade.timeRemaining);
  const [spinAnim] = useState(new Animated.Value(0));

  // Timer countdown effect
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeRemaining(prev => {
        if (prev <= 0) {
          clearInterval(timer);
          Alert.alert('Tiempo Expirado', 'El tiempo para completar el intercambio ha expirado.');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  // Spinning animation for step 3
  useEffect(() => {
    if (activeTradeStep === 3) {
      const spin = Animated.loop(
        Animated.timing(spinAnim, {
          toValue: 1,
          duration: 1000,
          useNativeDriver: true,
        })
      );
      spin.start();
      return () => spin.stop();
    }
  }, [activeTradeStep, spinAnim]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  const getProgressPercentage = () => {
    const totalTime = 15 * 60; // 15 minutes in seconds
    return ((totalTime - timeRemaining) / totalTime) * 100;
  };

  const handleGoBack = () => {
    // Navigate back to Exchange screen with refresh flag
    navigation.navigate('BottomTabs', { 
      screen: 'Exchange',
      params: { refreshData: true }
    });
  };

  const handleAbandonTrade = () => {
    Alert.alert(
      '¿Abandonar intercambio?',
      'Esta acción cancelará el intercambio y no podrás recuperarlo. ¿Estás seguro?',
      [
        {
          text: 'Cancelar',
          style: 'cancel',
        },
        {
          text: 'Abandonar',
          style: 'destructive',
          onPress: () => {
            // Here you would typically call an API to cancel the trade
            Alert.alert('Intercambio cancelado', 'El intercambio ha sido cancelado.');
            navigation.navigate('BottomTabs', { screen: 'Exchange' });
          },
        },
      ]
    );
  };


  const handleOpenChat = () => {
    navigation.navigate('TradeChat', {
      offer: {
        id: trade.id,
        name: trade.trader.name,
        rate: trade.rate + ' ' + trade.currencyCode,
        limit: '1000',
        available: '500',
        paymentMethods: [trade.paymentMethod],
        responseTime: trade.trader.responseTime,
        completedTrades: 50,
        successRate: 98,
        verified: trade.trader.verified,
        isOnline: trade.trader.isOnline,
        lastSeen: trade.trader.lastSeen,
        countryCode: trade.countryCode,
      },
      crypto: formatCrypto(trade.crypto) as 'cUSD' | 'CONFIO',
      amount: trade.amount,
      tradeType: trade.tradeType,
      tradeId: trade.id,
      tradeCountryCode: trade.countryCode,
      tradeCurrencyCode: trade.currencyCode,
      initialStep: activeTradeStep, // Pass the current step
      tradeStatus: trade.status, // Pass the current status if available
    });
  };

  const handleRateTrader = () => {
    Alert.alert('Calificación', 'Función de calificación en desarrollo');
  };

  // Progress bar component
  const TradeProgressBar: React.FC<{ currentStep: number; totalSteps: number }> = ({ currentStep, totalSteps }) => (
    <View style={styles.progressBarContainer}>
      {Array.from({ length: totalSteps }, (_, i) => (
        <React.Fragment key={i}>
          <View style={[
            styles.progressStep,
            i + 1 <= currentStep ? styles.progressStepActive : styles.progressStepInactive
          ]}>
            {i + 1 <= currentStep ? (
              <Icon name="check" size={16} color="#ffffff" />
            ) : (
              <Text style={[
                styles.progressStepText,
                i + 1 <= currentStep ? styles.progressStepTextActive : styles.progressStepTextInactive
              ]}>
                {i + 1}
              </Text>
            )}
          </View>
          {i < totalSteps - 1 && (
            <View style={[
              styles.progressLine,
              i + 1 < currentStep ? styles.progressLineActive : styles.progressLineInactive
            ]} />
          )}
        </React.Fragment>
      ))}
    </View>
  );

  // Determine if user is buyer or seller
  const isBuyer = trade.tradeType === 'buy';
  const isSeller = trade.tradeType === 'sell';

  const renderStep1 = () => {
    if (isBuyer) {
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Realizar Pago</Text>
          <Text style={styles.stepDescription}>
            Transfiere <Text style={styles.boldText}>{trade.totalBs} {trade.currencyCode}</Text> usando:
          </Text>
          
          <View style={styles.paymentMethodCard}>
            <View style={styles.paymentMethodHeader}>
              <View style={styles.paymentMethodIcon}>
                <Icon 
                  name={getPaymentMethodIcon(null, null, trade.paymentMethod)} 
                  size={18} 
                  color="#fff" 
                />
              </View>
              <View>
                <Text style={styles.paymentMethodName}>{trade.paymentMethod}</Text>
            <Text style={styles.paymentMethodSubtitle}>Método seleccionado</Text>
          </View>
        </View>
      </View>

      {trade.paymentMethod.includes('Efectivo') ? (
        <View style={styles.cashInstructionsCard}>
          <Text style={styles.cashInstructionsTitle}>Instrucciones para pago en efectivo</Text>
          <View style={styles.cashInstructionsList}>
            <Text style={styles.cashInstruction}>• Coordina el punto de encuentro con {trade.trader.name}</Text>
            <Text style={styles.cashInstruction}>• Lleva exactamente: <Text style={styles.boldText}>{trade.totalBs} {trade.currencyCode}</Text></Text>
            <Text style={styles.cashInstruction}>• Encuentro en lugar público y seguro</Text>
            <Text style={styles.cashInstruction}>• Verifica la identidad del vendedor</Text>
          </View>
        </View>
      ) : (
        <View style={styles.bankDetailsCard}>
          <View style={styles.bankDetailsRow}>
            <Text style={styles.bankDetailsLabel}>Banco:</Text>
            <Text style={styles.bankDetailsValue}>{trade.paymentMethod}</Text>
          </View>
          <View style={styles.bankDetailsRow}>
            <Text style={styles.bankDetailsLabel}>Titular:</Text>
            <Text style={styles.bankDetailsValue}>{trade.trader.name} (Nombre completo)</Text>
          </View>
          <View style={styles.bankDetailsRow}>
            <Text style={styles.bankDetailsLabel}>Cédula:</Text>
            <Text style={styles.bankDetailsValue}>V-12.345.678</Text>
          </View>
          <View style={styles.bankDetailsRow}>
            <Text style={styles.bankDetailsLabel}>Cuenta:</Text>
            <Text style={styles.bankDetailsValue}>0102-0000-00000000000</Text>
          </View>
          <View style={styles.bankDetailsRow}>
            <Text style={styles.bankDetailsLabel}>Monto exacto:</Text>
            <Text style={styles.bankDetailsAmount}>{trade.totalBs} {trade.currencyCode}</Text>
          </View>
        </View>
      )}
      
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>¿Ya realizaste el pago?</Text>
                <Text style={styles.infoText}>
                  Usa el chat del intercambio para marcar el pago como completado y comunicarte con el vendedor.
                </Text>
              </View>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    } else {
      // Seller view
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Esperando Pago del Comprador</Text>
          <Text style={styles.stepDescription}>
            {trade.trader.name} debe transferir <Text style={styles.boldText}>{trade.totalBs} {trade.currencyCode}</Text> a tu cuenta.
          </Text>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="clock" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Tiempo de respuesta esperado</Text>
                <Text style={styles.infoText}>
                  El comprador tiene hasta 15 minutos para completar la transferencia.
                </Text>
              </View>
            </View>
          </View>

          <View style={styles.summaryCard}>
            <Text style={styles.summaryTitle}>Detalles del intercambio</Text>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Vas a enviar:</Text>
              <Text style={styles.summaryValue}>{trade.amount} {formatCrypto(trade.crypto)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Vas a recibir:</Text>
              <Text style={styles.summaryValue}>{trade.totalBs} {trade.currencyCode}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Comprador:</Text>
              <Text style={styles.summaryValue}>{trade.trader.name}</Text>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  const renderStep2 = () => {
    if (isBuyer) {
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Confirmar Pago</Text>
          <Text style={styles.stepDescription}>
            Confirma que has completado el pago de <Text style={styles.boldText}>{trade.totalBs} {trade.currencyCode}</Text>
          </Text>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Verificación del vendedor</Text>
                <Text style={styles.infoText}>
                  {trade.trader.name} verificará el pago en su cuenta bancaria. 
                  Por favor sé paciente mientras confirma la transacción.
                </Text>
              </View>
            </View>
          </View>
            
          <View style={styles.warningCard}>
            <View style={styles.warningContent}>
              <Icon name="alert-triangle" size={20} color="#D97706" style={styles.warningIcon} />
              <View>
                <Text style={styles.warningTitle}>Solo confirma si ya pagaste</Text>
                <Text style={styles.warningText}>
                  No marques como pagado si no has completado la transferencia. 
                  Esto puede resultar en la suspensión de tu cuenta.
                </Text>
              </View>
            </View>
          </View>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Siguiente paso</Text>
                <Text style={styles.infoText}>
                  Debes confirmar el pago desde el chat del intercambio para mayor seguridad.
                </Text>
              </View>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#ffffff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    } else {
      // Seller view - they need to confirm they received payment
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>¿Recibiste el Pago?</Text>
          <Text style={styles.stepDescription}>
            Verifica que recibiste <Text style={styles.boldText}>{trade.totalBs} {trade.currencyCode}</Text> en tu cuenta bancaria.
          </Text>
          
          <View style={styles.warningCard}>
            <View style={styles.warningContent}>
              <Icon name="alert-triangle" size={20} color="#D97706" style={styles.warningIcon} />
              <View>
                <Text style={styles.warningTitle}>Verifica antes de confirmar</Text>
                <Text style={styles.warningText}>
                  Solo confirma si realmente recibiste el pago en tu cuenta. 
                  Una vez confirmado, se liberarán los {formatCrypto(trade.crypto)} al comprador.
                </Text>
              </View>
            </View>
          </View>

          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="shield" size={20} color={colors.primary} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Protección del vendedor</Text>
                <Text style={styles.infoText}>
                  Si no recibiste el pago, reporta el problema. Nunca liberes fondos sin haber recibido el pago completo.
                </Text>
              </View>
            </View>
          </View>
          
          <View style={styles.infoCard}>
            <View style={styles.infoContent}>
              <Icon name="info" size={20} color={colors.accent} style={styles.infoIcon} />
              <View>
                <Text style={styles.infoTitle}>Siguiente paso</Text>
                <Text style={styles.infoText}>
                  La liberación de fondos debe realizarse desde el chat del intercambio por seguridad.
                </Text>
              </View>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#ffffff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  const renderStep3 = () => {
    if (isBuyer) {
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Esperando Confirmación</Text>
          <Text style={styles.stepDescription}>
            {trade.trader.name} está verificando tu pago. Esto puede tomar unos minutos.
          </Text>
      
      <View style={styles.loadingCard}>
        <Animated.View 
          style={[
            styles.spinner,
            {
              transform: [{
                rotate: spinAnim.interpolate({
                  inputRange: [0, 1],
                  outputRange: ['0deg', '360deg'],
                })
              }]
            }
          ]}
        />
        <Text style={styles.loadingTitle}>Verificando pago...</Text>
        <Text style={styles.loadingSubtitle}>Tiempo promedio: {trade.trader.responseTime}</Text>
      </View>
      
      <View style={styles.summaryCard}>
        <Text style={styles.summaryTitle}>Resumen de la operación</Text>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Cantidad:</Text>
          <Text style={styles.summaryValue}>{trade.amount} {trade.crypto}</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Pagado:</Text>
          <Text style={styles.summaryValue}>{trade.totalBs} Bs.</Text>
        </View>
        <View style={styles.summaryRow}>
          <Text style={styles.summaryLabel}>Vendedor:</Text>
          <Text style={styles.summaryValue}>{trade.trader.name}</Text>
        </View>
      </View>
      
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    } else {
      // Seller view - processing the release of funds
      return (
        <View style={styles.stepCard}>
          <Text style={styles.stepTitle}>Liberando Fondos</Text>
          <Text style={styles.stepDescription}>
            Estamos procesando la transferencia de {trade.amount} {formatCrypto(trade.crypto)} a {trade.trader.name}.
          </Text>
          
          <View style={styles.loadingCard}>
            <Animated.View 
              style={[
                styles.spinner,
                {
                  transform: [{
                    rotate: spinAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: ['0deg', '360deg'],
                    })
                  }]
                }
              ]}
            />
            <Text style={styles.loadingTitle}>Procesando transacción...</Text>
            <Text style={styles.loadingSubtitle}>Esto puede tomar unos minutos</Text>
          </View>
          
          <View style={styles.summaryCard}>
            <Text style={styles.summaryTitle}>Resumen de la operación</Text>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Enviando:</Text>
              <Text style={styles.summaryValue}>{trade.amount} {formatCrypto(trade.crypto)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Recibido:</Text>
              <Text style={styles.summaryValue}>{trade.totalBs} {trade.currencyCode}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Comprador:</Text>
              <Text style={styles.summaryValue}>{trade.trader.name}</Text>
            </View>
          </View>
          
          <TouchableOpacity style={styles.primaryButton} onPress={handleOpenChat}>
            <Icon name="message-circle" size={16} color="#fff" style={styles.buttonIcon} />
            <Text style={styles.primaryButtonText}>Ir al chat del intercambio</Text>
          </TouchableOpacity>
        </View>
      );
    }
  };

  const renderStep4 = () => {
    // If trade is already completed (rated), show different UI
    if (trade.status === 'COMPLETED' && trade.hasRating) {
      return (
        <View style={styles.stepCard}>
          <View style={styles.successHeader}>
            <View style={styles.successIcon}>
              <Icon name="check" size={32} color="#ffffff" />
            </View>
            <Text style={styles.successTitle}>¡Intercambio Completado!</Text>
            <Text style={styles.successDescription}>
              Este intercambio ha sido completado y calificado
            </Text>
          </View>
          
          <View style={styles.transactionDetailsCard}>
            <Text style={styles.transactionDetailsTitle}>Detalles de la transacción</Text>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>ID de transacción:</Text>
              <Text style={styles.transactionDetailsValue}>0x1a2b3c4d...</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Fecha:</Text>
              <Text style={styles.transactionDetailsValue}>21 Jun 2025, 14:45</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Comerciante:</Text>
              <Text style={styles.transactionDetailsValue}>{trade.trader.name}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Método de pago:</Text>
              <Text style={styles.transactionDetailsValue}>{trade.paymentMethod}</Text>
            </View>
            <View style={styles.transactionDetailsRow}>
              <Text style={styles.transactionDetailsLabel}>Estado:</Text>
              <Text style={[styles.transactionDetailsValue, { color: colors.success }]}>Completado y calificado</Text>
            </View>
          </View>
          
          <View style={styles.successButtons}>
            <TouchableOpacity style={styles.secondaryButton} onPress={handleGoBack}>
              <Text style={styles.secondaryButtonText}>Volver a Intercambios</Text>
            </TouchableOpacity>
          </View>
        </View>
      );
    }
    
    // If trade is not yet rated, show rating button
    return (
      <View style={styles.stepCard}>
        <View style={styles.successHeader}>
          <View style={styles.successIcon}>
            <Icon name="check" size={32} color="#ffffff" />
          </View>
          <Text style={styles.successTitle}>¡Intercambio Completado!</Text>
          <Text style={styles.successDescription}>
            Has recibido <Text style={styles.boldText}>{trade.amount} {formatCrypto(trade.crypto)}</Text> en tu wallet
          </Text>
        </View>
        
        <View style={styles.transactionDetailsCard}>
          <Text style={styles.transactionDetailsTitle}>Detalles de la transacción</Text>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>ID de transacción:</Text>
            <Text style={styles.transactionDetailsValue}>0x1a2b3c4d...</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Fecha:</Text>
            <Text style={styles.transactionDetailsValue}>21 Jun 2025, 14:45</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Comerciante:</Text>
            <Text style={styles.transactionDetailsValue}>{trade.trader.name}</Text>
          </View>
          <View style={styles.transactionDetailsRow}>
            <Text style={styles.transactionDetailsLabel}>Método de pago:</Text>
            <Text style={styles.transactionDetailsValue}>{trade.paymentMethod}</Text>
          </View>
        </View>
        
        <View style={styles.successButtons}>
          <TouchableOpacity style={styles.primaryButton} onPress={() => navigation.navigate('TraderRating', {
            tradeId: trade.id,
            trader: {
              name: trade.trader.name,
              verified: trade.trader.verified,
              completedTrades: 248, // Replace with real data if available
              successRate: 99.2, // Replace with real data if available
            },
            tradeDetails: {
              amount: trade.amount,
              crypto: formatCrypto(trade.crypto),
              totalPaid: trade.totalBs,
              method: trade.paymentMethod,
              date: '21 Jun 2025, 14:45', // Replace with real data if available
              duration: '8 minutos', // Replace with real data if available
            }
          })}>
            <Text style={styles.primaryButtonText}>Calificar a {trade.trader.name}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryButton} onPress={handleGoBack}>
            <Text style={styles.secondaryButtonText}>Volver al Inicio</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={handleGoBack} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="#374151" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Intercambio Activo</Text>
          <View style={styles.headerSpacer} />
          <TouchableOpacity 
            style={styles.abandonButton}
            onPress={handleAbandonTrade}
          >
            <Text style={styles.abandonButtonText}>Abandonar</Text>
          </TouchableOpacity>
        </View>
        
        <TradeProgressBar currentStep={activeTradeStep} totalSteps={4} />
        
        {/* Timer */}
        <View style={styles.timerCard}>
          <View style={styles.timerHeader}>
            <Text style={styles.timerLabel}>Tiempo restante</Text>
            <Text style={styles.timerValue}>{formatTime(timeRemaining)}</Text>
          </View>
          <View style={styles.timerProgressBar}>
            <View 
              style={[
                styles.timerProgressFill, 
                { width: `${Math.max(10, 100 - getProgressPercentage())}%` }
              ]} 
            />
          </View>
          <TouchableOpacity 
            style={styles.viewAllTradesHint}
            onPress={() => navigation.navigate('BottomTabs', { screen: 'Exchange' })}
          >
            <Icon name="list" size={12} color="#2563EB" style={styles.hintIcon} />
            <Text style={styles.hintText}>Ver todos mis intercambios</Text>
          </TouchableOpacity>
        </View>
      </View>
      
      {/* Content */}
      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {activeTradeStep === 1 && renderStep1()}
        {activeTradeStep === 2 && renderStep2()}
        {activeTradeStep === 3 && renderStep3()}
        {activeTradeStep === 4 && renderStep4()}
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  header: {
    backgroundColor: '#fff',
    padding: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 1,
    },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  backButton: {
    marginRight: 12,
    padding: 4,
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  progressBarContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  progressStep: {
    width: 32,
    height: 32,
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
  },
  progressStepActive: {
    backgroundColor: colors.primary,
  },
  progressStepInactive: {
    backgroundColor: '#E5E7EB',
  },
  progressStepText: {
    fontSize: 14,
    fontWeight: '600',
  },
  progressStepTextActive: {
    color: '#ffffff',
  },
  progressStepTextInactive: {
    color: '#6B7280',
  },
  progressLine: {
    flex: 1,
    height: 4,
    marginHorizontal: 8,
  },
  progressLineActive: {
    backgroundColor: colors.primary,
  },
  progressLineInactive: {
    backgroundColor: '#E5E7EB',
  },
  timerCard: {
    backgroundColor: '#DBEAFE',
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  timerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  timerLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1E40AF',
  },
  timerValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1E40AF',
  },
  timerProgressBar: {
    width: '100%',
    height: 8,
    backgroundColor: '#BFDBFE',
    borderRadius: 4,
  },
  timerProgressFill: {
    height: 8,
    backgroundColor: '#2563EB',
    borderRadius: 4,
  },
  content: {
    flex: 1,
    padding: 16,
  },
  stepCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  stepTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  stepDescription: {
    fontSize: 16,
    color: '#6B7280',
    marginBottom: 16,
  },
  boldText: {
    fontWeight: 'bold',
  },
  paymentMethodCard: {
    backgroundColor: '#ECFDF5',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  paymentMethodHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  paymentMethodIcon: {
    width: 40,
    height: 40,
    backgroundColor: colors.primary,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentMethodIconText: {
    color: '#ffffff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  paymentMethodName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#065F46',
  },
  paymentMethodSubtitle: {
    fontSize: 14,
    color: '#059669',
  },
  cashInstructionsCard: {
    backgroundColor: '#FEF3C7',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  cashInstructionsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E',
    marginBottom: 8,
  },
  cashInstructionsList: {
    gap: 4,
  },
  cashInstruction: {
    fontSize: 14,
    color: '#B45309',
  },
  bankDetailsCard: {
    backgroundColor: '#F9FAFB',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  bankDetailsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  bankDetailsLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  bankDetailsValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  bankDetailsAmount: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  infoCard: {
    backgroundColor: '#DBEAFE',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  infoContent: {
    flexDirection: 'row',
  },
  infoIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  infoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1E40AF',
    marginBottom: 4,
  },
  infoText: {
    fontSize: 14,
    color: '#1D4ED8',
    flex: 1,
  },
  warningCard: {
    backgroundColor: '#FEF3C7',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  warningContent: {
    flexDirection: 'row',
  },
  warningIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#92400E',
    marginBottom: 4,
  },
  warningText: {
    fontSize: 14,
    color: '#B45309',
    flex: 1,
  },
  loadingCard: {
    backgroundColor: '#DBEAFE',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
    alignItems: 'center',
  },
  spinner: {
    width: 32,
    height: 32,
    borderWidth: 4,
    borderColor: '#BFDBFE',
    borderTopColor: '#2563EB',
    borderRadius: 16,
    marginBottom: 8,
  },
  loadingTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1E40AF',
    marginBottom: 4,
  },
  loadingSubtitle: {
    fontSize: 14,
    color: '#2563EB',
  },
  summaryCard: {
    backgroundColor: '#F9FAFB',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  summaryTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 8,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  summaryLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  summaryValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  successHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  successIcon: {
    width: 64,
    height: 64,
    backgroundColor: '#10B981',
    borderRadius: 32,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  successTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 8,
  },
  successDescription: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
  },
  transactionDetailsCard: {
    backgroundColor: '#F9FAFB',
    padding: 16,
    borderRadius: 8,
    marginBottom: 16,
  },
  transactionDetailsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 8,
  },
  transactionDetailsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  transactionDetailsLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  transactionDetailsValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  successButtons: {
    gap: 12,
    marginTop: 8,
  },
  primaryButton: {
    backgroundColor: colors.primary,
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    marginBottom: 12,
  },
  primaryButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    backgroundColor: '#F3F4F6',
    paddingVertical: 12,
    borderRadius: 12,
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
  },
  secondaryButtonText: {
    color: '#374151',
    fontSize: 16,
    fontWeight: '600',
  },
  buttonIcon: {
    marginRight: 8,
  },
  viewTradesButton: {
    padding: 4,
  },
  viewAllTradesHint: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 8,
    borderRadius: 8,
    backgroundColor: '#DBEAFE',
  },
  hintIcon: {
    marginRight: 4,
  },
  hintText: {
    fontSize: 12,
    fontWeight: '600',
    color: '#2563EB',
  },
  abandonButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#EF4444',
  },
  abandonButtonText: {
    color: '#EF4444',
    fontSize: 14,
    fontWeight: '600',
  },
  headerSpacer: {
    flex: 1,
  },
  helperText: {
    fontSize: 14,
    color: '#6B7280',
    textAlign: 'center',
    marginTop: 12,
    paddingHorizontal: 24,
    lineHeight: 20,
  },
});
