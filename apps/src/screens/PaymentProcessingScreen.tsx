import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Dimensions,
  Animated,
  Easing,
  SafeAreaView,
  BackHandler,
  ScrollView,
  Alert,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { useMutation } from '@apollo/client';
import { PAY_INVOICE } from '../apollo/queries';
import { colors } from '../config/theme';
import { GET_INVOICES } from '../apollo/queries'; // Added this import for cache update
import { AccountManager } from '../utils/accountManager';

type PaymentProcessingRouteProp = RouteProp<{
  PaymentProcessing: {
    transactionData: {
      type: 'payment';
      amount: string;
      currency: string;
      merchant: string;
      action: string;
      address?: string;
      message?: string;
      invoiceId?: string;
    };
  };
}, 'PaymentProcessing'>;

const { width } = Dimensions.get('window');

export const PaymentProcessingScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<PaymentProcessingRouteProp>();
  const [currentStep, setCurrentStep] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [isValid, setIsValid] = useState(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [paymentResponse, setPaymentResponse] = useState<any>(null);

  // GraphQL mutation for paying invoice
  const [payInvoice] = useMutation(PAY_INVOICE, {
    update: (cache, { data }) => {
      if (data?.payInvoice?.success) {
        console.log('PaymentProcessingScreen: Updating Apollo cache after successful payment');
        
        // Update the GET_INVOICES query cache to reflect the new status
        try {
          const existingInvoices = cache.readQuery({ query: GET_INVOICES });
          if (existingInvoices && typeof existingInvoices === 'object' && 'invoices' in existingInvoices && Array.isArray(existingInvoices.invoices)) {
            const updatedInvoices = existingInvoices.invoices.map((invoice: any) => {
              if (invoice.invoiceId === transactionData.invoiceId) {
                return {
                  ...invoice,
                  status: 'PAID',
                  paidByUser: data.payInvoice.invoice.paidByUser,
                  paidAt: data.payInvoice.invoice.paidAt,
                  paymentTransactions: data.payInvoice.paymentTransaction ? [data.payInvoice.paymentTransaction] : []
                };
              }
              return invoice;
            });
            
            cache.writeQuery({
              query: GET_INVOICES,
              data: { invoices: updatedInvoices }
            });
            console.log('PaymentProcessingScreen: Cache updated successfully');
          }
        } catch (error) {
          console.log('PaymentProcessingScreen: Cache update error (non-critical):', error);
        }
      }
    }
  });

  // Helper function to format currency for display
  const formatCurrency = (currency: string): string => {
    if (currency === 'CUSD') return 'cUSD';
    if (currency === 'CONFIO') return 'CONFIO';
    if (currency === 'USDC') return 'USDC';
    return currency; // fallback
  };
  
  const { transactionData } = route.params;

  // Debug logging to track when this screen is accessed
  console.log('PaymentProcessingScreen: Screen mounted with data:', transactionData);

  // Safety check - if no transaction data, go back
  useEffect(() => {
    if (!transactionData || !transactionData.amount || !transactionData.merchant) {
      console.warn('PaymentProcessingScreen: Invalid transaction data, navigating back');
      navigation.goBack();
      return;
    }
    
    // Additional check to ensure this is a payment transaction
    if (transactionData.type !== 'payment') {
      console.warn('PaymentProcessingScreen: Invalid transaction type, navigating back');
      navigation.goBack();
      return;
    }
    
    // Mark as valid if all checks pass
    setIsValid(true);
    console.log('PaymentProcessingScreen: Transaction data validated successfully');
  }, [transactionData, navigation]);

  // Animation values
  const spinValue = new Animated.Value(0);
  const pulseValue = new Animated.Value(1);

  // Processing steps
  const processingSteps = [
    {
      icon: 'shield',
      text: 'Verificando transacción',
      color: '#3B82F6',
      bgColor: '#DBEAFE'
    },
    {
      icon: 'zap',
      text: 'Procesando en blockchain',
      color: '#10B981',
      bgColor: '#D1FAE5'
    },
    {
      icon: 'check-circle',
      text: 'Confirmando...',
      color: '#22C55E',
      bgColor: '#DCFCE7'
    }
  ];

  // Start spinning animation
  useEffect(() => {
    const spinAnimation = Animated.loop(
      Animated.timing(spinValue, {
        toValue: 1,
        duration: 2000,
        easing: Easing.linear,
        useNativeDriver: true,
      })
    );
    spinAnimation.start();

    return () => spinAnimation.stop();
  }, []);

  // Start pulse animation
  useEffect(() => {
    const pulseAnimation = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseValue, {
          toValue: 1.2,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(pulseValue, {
          toValue: 1,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ])
    );
    pulseAnimation.start();

    return () => pulseAnimation.stop();
  }, []);

  // Process payment when screen loads
  useEffect(() => {
    if (!isValid || !transactionData.invoiceId) {
      return;
    }

    const processPayment = async () => {
      try {
        console.log('PaymentProcessingScreen: Starting payment processing for invoice:', transactionData.invoiceId);
        
        // Debug: Check current active account context before payment
        try {
          const accountManager = AccountManager.getInstance();
          const activeContext = await accountManager.getActiveAccountContext();
          console.log('PaymentProcessingScreen - Active account context before payment:', {
            type: activeContext.type,
            index: activeContext.index,
            accountId: `${activeContext.type}_${activeContext.index}`
          });
        } catch (error) {
          console.log('PaymentProcessingScreen - Could not get active account context:', error);
        }
        
        // Step 1: Verifying transaction
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 2: Processing in blockchain
        setCurrentStep(1);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 3: Call the actual payment mutation
        setCurrentStep(2);
        console.log('PaymentProcessingScreen: Calling payInvoice mutation...');
        const { data } = await payInvoice({
          variables: {
            invoiceId: transactionData.invoiceId
          }
        });

        console.log('PaymentProcessingScreen: Mutation response:', data);

        if (data?.payInvoice?.success) {
          console.log('PaymentProcessingScreen: Payment successful:', data.payInvoice);
          setIsComplete(true);
          setPaymentResponse(data.payInvoice); // Store payment response
        } else if (data?.payInvoice) {
          // Payment might have succeeded but with a different response format
          console.log('PaymentProcessingScreen: Payment response received:', data.payInvoice);
          setIsComplete(true);
          setPaymentResponse(data.payInvoice); // Store payment response
        } else {
          const errors = data?.payInvoice?.errors || ['Error desconocido'];
          console.error('PaymentProcessingScreen: Payment failed:', errors);
          setPaymentError(errors.join(', '));
        }
      } catch (error) {
        console.error('PaymentProcessingScreen: Payment error:', error);
        setPaymentError('Error al procesar el pago. Inténtalo de nuevo.');
      }
    };

    processPayment();
  }, [isValid, transactionData.invoiceId, payInvoice]);



  // Navigate to success screen after completion or handle errors
  useEffect(() => {
    if (isComplete || paymentError) {
      const timer = setTimeout(() => {
        if (paymentError) {
          // Show error alert and navigate to home instead of going back
          Alert.alert(
            'Error en el Pago',
            paymentError,
            [
              {
                text: 'Entendido',
                onPress: () => {
                  // Navigate to home screen instead of going back
                  (navigation as any).navigate('BottomTabs', { screen: 'Home' });
                }
              }
            ]
          );
        } else {
          // Navigate to payment success screen
          const successData = {
            type: 'payment',
            amount: transactionData.amount,
            currency: transactionData.currency,
            recipient: transactionData.merchant,
            merchant: transactionData.merchant,
            recipientAddress: '', // Will be filled by backend
            merchantAddress: '', // Will be filled by backend
            message: transactionData.message || '',
            address: transactionData.address || '',
            transactionHash: paymentResponse?.paymentTransaction?.transactionHash || 'pending'
          };
          
          console.log('PaymentProcessingScreen: Navigating to PaymentSuccess with data:', successData);
          
          (navigation as any).navigate('PaymentSuccess', {
            transactionData: successData
          });
        }
      }, 2000);

      return () => clearTimeout(timer);
    }
  }, [isComplete, paymentError, navigation, transactionData, paymentResponse]);

  // Prevent back navigation during processing
  useEffect(() => {
    const onBackPress = () => {
      // Block back navigation during processing to prevent double payments
      console.log('PaymentProcessingScreen: Back button blocked during processing');
      return true; // Return true to prevent default back behavior
    };

    // Add event listener for hardware back button
    const subscription = BackHandler.addEventListener('hardwareBackPress', onBackPress);

    // Cleanup function to remove event listener
    return () => {
      subscription.remove();
    };
  }, []);

  // Cleanup effect to reset state when screen unmounts
  useEffect(() => {
    return () => {
      console.log('PaymentProcessingScreen: Screen unmounting, cleaning up state');
      setCurrentStep(0);
      setIsComplete(false);
    };
  }, []);

  const spin = spinValue.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  // Don't render anything if not valid
  if (!isValid) {
    return null;
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Processing Header */}
        <View style={[styles.header, { backgroundColor: colors.primary }]}>
          <View style={styles.headerContent}>
            {/* Processing Animation */}
            <View style={styles.processingIcon}>
              {!isComplete ? (
                <>
                  <Animated.View style={[styles.spinner, { transform: [{ rotate: spin }] }]}>
                    <Icon name="loader" size={48} color={colors.primary} />
                  </Animated.View>
                  <Animated.View 
                    style={[
                      styles.pulseEffect, 
                      { 
                        backgroundColor: colors.primary,
                        opacity: 0.2,
                        transform: [{ scale: pulseValue }]
                      }
                    ]} 
                  />
                </>
              ) : (
                <Icon name="check-circle" size={48} color={colors.primary} />
              )}
            </View>
            
            <Text style={styles.headerTitle}>
              {isComplete ? '¡Casi listo!' : transactionData.action}
            </Text>
            
            <Text style={styles.amountText}>
              ${transactionData.amount} {formatCurrency(transactionData.currency)}
            </Text>
            
            <Text style={styles.merchantText}>
              En {transactionData.merchant}
            </Text>
          </View>
        </View>

        {/* Processing Steps */}
        <View style={styles.content}>
        <View style={styles.stepsCard}>
          <View style={styles.stepsContainer}>
            {processingSteps.map((step, index) => (
              <View key={index} style={styles.stepRow}>
                {/* Step Icon */}
                <View style={[
                  styles.stepIcon,
                  { 
                    backgroundColor: index <= currentStep ? step.bgColor : '#F3F4F6',
                    transform: [{ scale: index === currentStep ? 1.1 : 1 }]
                  }
                ]}>
                  <Icon 
                    name={step.icon as any} 
                    size={24} 
                    color={index <= currentStep ? step.color : '#9CA3AF'} 
                  />
                </View>

                {/* Step Text */}
                <View style={styles.stepTextContainer}>
                  <Text style={[
                    styles.stepText,
                    { color: index <= currentStep ? '#1F2937' : '#9CA3AF' }
                  ]}>
                    {step.text}
                  </Text>
                  {index === currentStep && !isComplete && (
                    <View style={styles.loadingDots}>
                      <View style={styles.dot} />
                      <View style={styles.dot} />
                      <View style={styles.dot} />
                    </View>
                  )}
                </View>

                {/* Checkmark */}
                {index < currentStep && (
                  <Icon name="check-circle" size={20} color="#22C55E" />
                )}
                {index === currentStep && isComplete && (
                  <Icon name="check-circle" size={20} color="#22C55E" />
                )}
              </View>
            ))}
          </View>

          {/* Progress Bar */}
          <View style={styles.progressContainer}>
            <View style={styles.progressBar}>
              <View 
                style={[
                  styles.progressFill,
                  { 
                    backgroundColor: colors.primary,
                    width: `${((currentStep + 1) / processingSteps.length) * 100}%`
                  }
                ]} 
              />
            </View>
            <View style={styles.progressLabels}>
              <Text style={styles.progressLabel}>0%</Text>
              <Text style={styles.progressLabel}>50%</Text>
              <Text style={styles.progressLabel}>100%</Text>
            </View>
          </View>
        </View>

        {/* Security Message */}
        <View style={styles.securityCard}>
          <View style={styles.securityContent}>
            <Icon name="shield" size={20} color={colors.primary} />
            <Text style={styles.securityText}>
              <Text style={styles.securityBold}>Transacción segura</Text> • Protegido por blockchain
            </Text>
          </View>
        </View>

        {/* Processing Info */}
        <View style={styles.infoCard}>
          <View style={styles.infoContent}>
            <Icon name="clock" size={16} color="#059669" />
            <View style={styles.infoTextContainer}>
              <Text style={styles.infoTitle}>¿Sabías que...?</Text>
              <Text style={styles.infoText}>
                Confío cubre las comisiones de red para que puedas transferir dinero completamente gratis. 
                ¡Apoyamos a la comunidad venezolana! 🇻🇪
              </Text>
            </View>
          </View>
        </View>

        {/* Completion message */}
        {isComplete && (
          <View style={styles.completionCard}>
            <View style={styles.completionContent}>
              <Icon name="check-circle" size={32} color="#22C55E" />
              <Text style={styles.completionTitle}>¡Transacción completada!</Text>
              <Text style={styles.completionText}>Redirigiendo a confirmación...</Text>
            </View>
          </View>
        )}

        {/* Error message */}
        {paymentError && (
          <View style={styles.errorCard}>
            <View style={styles.errorContent}>
              <Icon name="alert-circle" size={32} color="#EF4444" />
              <Text style={styles.errorTitle}>Error en el pago</Text>
              <Text style={styles.errorText}>{paymentError}</Text>
              <Text style={styles.errorSubtext}>Redirigiendo de vuelta...</Text>
            </View>
          </View>
        )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  scrollView: {
    flex: 1,
  },
  header: {
    paddingTop: 48,
    paddingBottom: 48,
    paddingHorizontal: 16,
  },
  headerContent: {
    alignItems: 'center',
  },
  processingIcon: {
    width: 96,
    height: 96,
    backgroundColor: 'white',
    borderRadius: 48,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
    position: 'relative',
  },
  spinner: {
    position: 'absolute',
  },
  pulseEffect: {
    position: 'absolute',
    width: 96,
    height: 96,
    borderRadius: 48,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 8,
  },
  amountText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 16,
  },
  merchantText: {
    fontSize: 18,
    color: 'rgba(255,255,255,0.9)',
  },
  content: {
    flex: 1,
    paddingHorizontal: 16,
    marginTop: -32,
    paddingBottom: 40,
  },
  stepsCard: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 32,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  stepsContainer: {
    gap: 24,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  stepIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  stepTextContainer: {
    flex: 1,
  },
  stepText: {
    fontSize: 16,
    fontWeight: '500',
  },
  loadingDots: {
    flexDirection: 'row',
    marginTop: 4,
    gap: 4,
  },
  dot: {
    width: 8,
    height: 8,
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  progressContainer: {
    marginTop: 32,
  },
  progressBar: {
    width: '100%',
    height: 8,
    backgroundColor: '#E5E7EB',
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 4,
  },
  progressLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  progressLabel: {
    fontSize: 12,
    color: '#6B7280',
  },
  securityCard: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 24,
    marginTop: 24,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  securityContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  securityText: {
    fontSize: 14,
    color: '#6B7280',
    marginLeft: 8,
  },
  securityBold: {
    fontWeight: '600',
    color: '#059669',
  },
  infoCard: {
    backgroundColor: '#ECFDF5',
    borderRadius: 16,
    padding: 16,
    marginTop: 16,
  },
  infoContent: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  infoTextContainer: {
    flex: 1,
    marginLeft: 8,
  },
  infoTitle: {
    fontSize: 12,
    color: '#065F46',
    fontWeight: '600',
    marginBottom: 4,
  },
  infoText: {
    fontSize: 12,
    color: '#047857',
  },
  completionCard: {
    backgroundColor: '#F0FDF4',
    borderRadius: 16,
    padding: 16,
    marginTop: 16,
    borderWidth: 1,
    borderColor: '#BBF7D0',
  },
  completionContent: {
    alignItems: 'center',
  },
  completionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#166534',
    marginTop: 8,
    marginBottom: 4,
  },
  completionText: {
    fontSize: 12,
    color: '#15803D',
  },
  errorCard: {
    backgroundColor: '#FEF2F2',
    borderRadius: 16,
    padding: 16,
    marginTop: 16,
    borderWidth: 1,
    borderColor: '#FECACA',
  },
  errorContent: {
    alignItems: 'center',
  },
  errorTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#DC2626',
    marginTop: 8,
    marginBottom: 4,
  },
  errorText: {
    fontSize: 14,
    color: '#DC2626',
    textAlign: 'center',
    marginBottom: 4,
  },
  errorSubtext: {
    fontSize: 12,
    color: '#EF4444',
  },
}); 