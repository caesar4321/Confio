import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Platform, Animated, ScrollView, BackHandler, Alert } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect } from '@react-navigation/native';
import { useMutation } from '@apollo/client';
import { PAY_INVOICE, CREATE_SEND_TRANSACTION } from '../apollo/queries';
import { SEND_TOKENS } from '../apollo/mutations';
import { AccountManager } from '../utils/accountManager';
import { EnhancedAuthService } from '../services/enhancedAuthService';

const colors = {
  primary: '#34D399', // emerald-400
  secondary: '#8B5CF6', // violet-500
  accent: '#3B82F6', // blue-500
  background: '#F9FAFB', // gray-50
  neutralDark: '#F3F4F6', // gray-100
  text: {
    primary: '#1F2937', // gray-800
    secondary: '#6B7280', // gray-500
  },
  success: '#10B981', // emerald-500
  warning: '#F59E0B', // amber-500
};

type TransactionType = 'sent' | 'payment';

interface TransactionData {
  type: TransactionType;
  amount: string;
  currency: string;
  recipient?: string;
  merchant?: string;
  action: string;
  isOnConfio?: boolean;
  sendTransactionId?: string;
  recipientAddress?: string;
  recipientPhone?: string;
  recipientUserId?: string;
  invoiceId?: string;
  memo?: string;
  idempotencyKey?: string; // Pass idempotency key from calling screen
  transactionId?: string; // Store transaction ID after successful processing
  tokenType?: string; // For blockchain transactions (CUSD, CONFIO)
}

export const TransactionProcessingScreen = () => {
  console.log('TransactionProcessingScreen: Component mounted');
  const navigation = useNavigation();
  const route = useRoute();
  const insets = useSafeAreaInsets();
  
  const transactionData: TransactionData = (route.params as any)?.transactionData || {
    type: 'sent',
    amount: '125.50',
    currency: 'cUSD',
    recipient: 'María González',
    action: 'Enviando',
    isOnConfio: true
  };

  const [currentStep, setCurrentStep] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [pulseAnim] = useState(new Animated.Value(1));
  const [bounceAnims] = useState([
    new Animated.Value(0),
    new Animated.Value(0),
    new Animated.Value(0)
  ]);

  // Services
  const enhancedAuthService = EnhancedAuthService.getInstance();

  // GraphQL mutations
  const [payInvoice] = useMutation(PAY_INVOICE);
  const [createSendTransaction] = useMutation(CREATE_SEND_TRANSACTION);
  const [sendTokens] = useMutation(SEND_TOKENS);
  
  // Ref to prevent duplicate transaction processing within this session
  const hasProcessedRef = useRef(false);
  
  // Use idempotency key from transactionData, or generate one as fallback
  const idempotencyKey = transactionData.idempotencyKey || (() => {
    // Fallback: generate idempotency key if not provided
    const timestamp = Date.now();
    if (transactionData.type === 'payment' && transactionData.invoiceId) {
      return `pay_${transactionData.invoiceId}_${timestamp}`;
    } else if (transactionData.type === 'sent') {
      // Use recipient identifier (phone, userId, or address)
      let recipientId = 'unknown';
      if (transactionData.recipientUserId) {
        recipientId = transactionData.recipientUserId;
      } else if (transactionData.recipientPhone) {
        recipientId = transactionData.recipientPhone.replace(/\D/g, '').slice(-8);
      } else if (transactionData.recipientAddress) {
        recipientId = transactionData.recipientAddress.slice(-8);
      }
      const amountStr = transactionData.amount.replace('.', '');
      return `send_${recipientId}_${amountStr}_${transactionData.currency}_${timestamp}`;
    } else {
      return `tx_unknown_${timestamp}`;
    }
  })();

  // Processing steps
  const processingSteps = [
    {
      icon: 'shield',
      text: 'Verificando transacción',
      color: colors.accent,
      bgColor: '#DBEAFE'
    },
    {
      icon: 'zap',
      text: 'Procesando en blockchain',
      color: colors.primary,
      bgColor: '#D1FAE5'
    },
    {
      icon: 'check-circle',
      text: 'Confirmando...',
      color: colors.success,
      bgColor: '#D1FAE5'
    }
  ];

  // Prevent back navigation during processing
  useFocusEffect(
    React.useCallback(() => {
      const onBackPress = () => {
        // Block back navigation during processing to prevent transaction interruption
        return true; // Return true to prevent default back behavior
      };

      // Add event listener for hardware back button
      const subscription = BackHandler.addEventListener('hardwareBackPress', onBackPress);

      // Cleanup function to remove event listener
      return () => {
        subscription.remove();
      };
    }, [])
  );

  // Auto-advance through steps
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentStep((prev) => {
        if (prev < processingSteps.length - 1) {
          return prev + 1;
        } else {
          setIsComplete(true);
          clearInterval(timer);
          // Navigate to success screen after completion
          setTimeout(() => {
            console.log('TransactionProcessingScreen: Navigating to TransactionSuccess with data:', transactionData);
            console.log('TransactionProcessingScreen: isOnConfio value:', transactionData.isOnConfio);
            (navigation as any).replace('TransactionSuccess', { transactionData });
          }, 2000);
          return prev;
        }
      });
    }, 1500); // 1.5 seconds per step

    return () => clearInterval(timer);
  }, []);

  // Process transaction when screen loads
  useEffect(() => {
    console.log('TransactionProcessingScreen: useEffect triggered, hasProcessedRef.current:', hasProcessedRef.current);
    console.log('TransactionProcessingScreen: transactionData:', transactionData);
    console.log('TransactionProcessingScreen: Generated idempotencyKey:', idempotencyKey);
    
    // Prevent duplicate processing within this screen session
    if (hasProcessedRef.current) {
      console.log('TransactionProcessingScreen: Transaction already processed in this session, skipping');
      return;
    }
    
    const initializeProcessing = async () => {
      try {
        hasProcessedRef.current = true;
        
        if (transactionData.type === 'payment' && transactionData.invoiceId) {
          console.log('TransactionProcessingScreen: Starting payment processing');
          await processPayment();
        } else if (transactionData.type === 'sent') {
          console.log('TransactionProcessingScreen: Starting send processing');
          await processSend();
        } else {
          console.error('TransactionProcessingScreen: Unknown transaction type or missing data:', {
            type: transactionData.type,
            hasRecipient: !!transactionData.recipient,
            hasRecipientPhone: !!transactionData.recipientPhone,
            hasRecipientUserId: !!transactionData.recipientUserId
          });
        }
      } catch (error) {
        console.error('TransactionProcessingScreen: Error in initializeProcessing:', error);
      }
    };

    const processPayment = async () => {
      try {
        console.log('TransactionProcessingScreen: Processing payment for invoice:', transactionData.invoiceId);
        
        // Debug: Check current active account context before payment
        try {
          const accountManager = AccountManager.getInstance();
          const activeContext = await accountManager.getActiveAccountContext();
          console.log('TransactionProcessingScreen - Active account context before payment:', {
            type: activeContext.type,
            index: activeContext.index,
            accountId: `${activeContext.type}_${activeContext.index}`
          });
        } catch (error) {
          console.log('TransactionProcessingScreen - Could not get active account context:', error);
        }
        
        // Step 1: Verifying transaction
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 2: Processing in blockchain
        setCurrentStep(1);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 3: Call the actual payment mutation with security checks
        setCurrentStep(2);
        console.log('TransactionProcessingScreen: Calling payInvoice mutation with security checks and idempotency key:', idempotencyKey);
        
        // Perform secure payment operation
        const secureResult = await enhancedAuthService.performSecureOperation(
          async () => {
            return await payInvoice({
              variables: {
                invoiceId: transactionData.invoiceId,
                idempotencyKey: idempotencyKey
              }
            });
          },
          'payment',
          parseFloat(transactionData.amount)
        );

        const { data } = secureResult.result;
        console.log('TransactionProcessingScreen: Payment mutation response:', data);
        console.log('TransactionProcessingScreen: Security checks:', secureResult.securityChecks);
        
        if (data?.payInvoice?.success) {
          console.log('TransactionProcessingScreen: Payment successful');
          // The transaction is already marked as confirmed in the backend
          // Just wait for the UI to complete
        } else {
          console.error('TransactionProcessingScreen: Payment failed:', data?.payInvoice?.errors);
          // Handle payment failure
        }
      } catch (error) {
        console.error('TransactionProcessingScreen: Error processing payment:', error);
        // Handle error
      }
    };

    const processSend = async () => {
      try {
        console.log('TransactionProcessingScreen: Processing send transaction to:', transactionData.recipient);
        
        // Check if this is a blockchain send (to Sui address) or Confío user send
        const isBlockchainSend = transactionData.recipientAddress?.startsWith('0x') && 
                                transactionData.recipientAddress.length === 66;
        
        if (isBlockchainSend) {
          console.log('TransactionProcessingScreen: Processing blockchain send to:', transactionData.recipientAddress);
          await processBlockchainSend();
        } else {
          console.log('TransactionProcessingScreen: Processing Confío user send');
          await processConfioSend();
        }
      } catch (error) {
        console.error('TransactionProcessingScreen: Error in processSend:', error);
        Alert.alert(
          'Error',
          'Error al procesar la transacción. Por favor, inténtalo de nuevo.',
          [{ text: 'OK', onPress: () => navigation.goBack() }]
        );
      }
    };

    const processBlockchainSend = async () => {
      try {
        // Step 1: Verifying transaction
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 2: Processing in blockchain
        setCurrentStep(1);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 3: Execute blockchain transaction
        setCurrentStep(2);
        console.log('TransactionProcessingScreen: Executing blockchain send with SEND_TOKENS mutation');
        
        const result = await sendTokens({
          variables: {
            recipient: transactionData.recipientAddress,
            amount: transactionData.amount,
            tokenType: transactionData.tokenType || transactionData.currency.toUpperCase(),
            message: transactionData.memo || ''
          }
        });
        
        console.log('TransactionProcessingScreen: Blockchain send result:', result);
        
        if (result.data?.sendTokens?.success) {
          console.log('TransactionProcessingScreen: Blockchain send successful!');
          console.log('Transaction digest:', result.data.sendTokens.transactionDigest);
          console.log('Gas saved:', result.data.sendTokens.gasSaved);
          
          // Store transaction digest for success screen
          if (transactionData) {
            transactionData.transactionId = result.data.sendTokens.transactionDigest;
          }
        } else {
          const errorMessage = result.data?.sendTokens?.error || 'Error al enviar tokens';
          console.error('TransactionProcessingScreen: Blockchain send failed:', errorMessage);
          Alert.alert(
            'Error al enviar',
            errorMessage,
            [{ text: 'OK', onPress: () => navigation.goBack() }]
          );
          return;
        }
      } catch (error) {
        console.error('TransactionProcessingScreen: Error in blockchain send:', error);
        throw error;
      }
    };

    const processConfioSend = async () => {
      try {
        // Step 1: Verifying transaction
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 2: Processing in blockchain
        setCurrentStep(1);
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Step 3: Call the actual send mutation
        setCurrentStep(2);
        console.log('TransactionProcessingScreen: Calling createSendTransaction mutation with idempotency key:', idempotencyKey);
        
        // Prepare input based on available recipient data - IMPORTANT: The GraphQL schema expects camelCase
        const mutationInput: any = {
          amount: transactionData.amount,
          tokenType: transactionData.currency,
          memo: transactionData.memo || '', // Use provided memo or empty string
          idempotencyKey: idempotencyKey,
          recipientDisplayName: transactionData.recipient
        };
        
        // Use the appropriate recipient identifier
        if (transactionData.recipientUserId && transactionData.isOnConfio) {
          // For Confío users, prefer user ID
          mutationInput.recipientUserId = transactionData.recipientUserId;
          console.log('TransactionProcessingScreen: Using recipient user ID:', transactionData.recipientUserId);
        } else if (transactionData.recipientPhone) {
          // For any user with phone number (Confío or not)
          mutationInput.recipientPhone = transactionData.recipientPhone;
          console.log('TransactionProcessingScreen: Using recipient phone:', transactionData.recipientPhone);
        }
        
        console.log('TransactionProcessingScreen: Sending mutation with input:', JSON.stringify(mutationInput, null, 2));
        
        const mutationVariables = {
          input: mutationInput
        };
        console.log('TransactionProcessingScreen: Full mutation variables:', JSON.stringify(mutationVariables, null, 2));
        
        // Perform secure send operation with device fingerprinting and security checks
        const secureResult = await enhancedAuthService.performSecureOperation(
          async () => {
            return await createSendTransaction({
              variables: mutationVariables
            });
          },
          'send_money',
          parseFloat(transactionData.amount)
        );

        const { data, errors } = secureResult.result;
        console.log('TransactionProcessingScreen: Send mutation raw response:', { data, errors });
        console.log('TransactionProcessingScreen: Response data structure:', JSON.stringify(data, null, 2));
        console.log('TransactionProcessingScreen: Security checks:', secureResult.securityChecks);
        
        // Check for GraphQL errors first
        if (errors && errors.length > 0) {
          console.error('TransactionProcessingScreen: GraphQL errors:', errors);
          const errorMessage = errors.map(e => e.message).join('\n');
          Alert.alert(
            'Error al enviar',
            errorMessage || 'Error al procesar la transacción',
            [{ text: 'OK', onPress: () => navigation.goBack() }]
          );
          return;
        }
        
        // Check the mutation response
        if (data?.createSendTransaction?.sendTransaction) {
          console.log('TransactionProcessingScreen: Send successful!');
          console.log('TransactionProcessingScreen: Transaction object:', data.createSendTransaction.sendTransaction);
          console.log('TransactionProcessingScreen: Transaction ID:', data.createSendTransaction.sendTransaction.id);
          
          // Store the transaction ID for success screen
          if (transactionData) {
            transactionData.transactionId = data.createSendTransaction.sendTransaction.id;
          }
          
          // Log success metrics
          console.log('TransactionProcessingScreen: Transaction created successfully:', {
            id: data.createSendTransaction.sendTransaction.id,
            amount: transactionData.amount,
            recipient: transactionData.recipient,
            recipientUserId: transactionData.recipientUserId,
            recipientPhone: transactionData.recipientPhone
          });
        } else if (data?.createSendTransaction?.errors && data.createSendTransaction.errors.length > 0) {
          console.error('TransactionProcessingScreen: Send failed with mutation errors:', data.createSendTransaction.errors);
          // Show error to user
          Alert.alert(
            'Error al enviar',
            data.createSendTransaction.errors.join('\n'),
            [{ text: 'OK', onPress: () => navigation.goBack() }]
          );
          return;
        } else if (data?.createSendTransaction) {
          // The mutation returned but with unexpected structure
          console.error('TransactionProcessingScreen: Unexpected mutation response structure:', data.createSendTransaction);
          console.error('TransactionProcessingScreen: Keys in response:', Object.keys(data.createSendTransaction));
          
          Alert.alert(
            'Error',
            'La transacción no se pudo completar correctamente. Por favor, inténtalo de nuevo.',
            [{ text: 'OK', onPress: () => navigation.goBack() }]
          );
          return;
        } else {
          console.error('TransactionProcessingScreen: No createSendTransaction in response:', data);
          Alert.alert(
            'Error',
            'Error inesperado al procesar la transacción.',
            [{ text: 'OK', onPress: () => navigation.goBack() }]
          );
          return;
        }
      } catch (error) {
        console.error('TransactionProcessingScreen: Error processing Confío send:', error);
        console.error('TransactionProcessingScreen: Error details:', {
          message: error.message,
          networkError: error.networkError,
          graphQLErrors: error.graphQLErrors,
          stack: error.stack
        });
        
        // Show error to user
        Alert.alert(
          'Error de conexión',
          'No se pudo conectar con el servidor. Por favor, verifica tu conexión e inténtalo de nuevo.',
          [{ text: 'OK', onPress: () => navigation.goBack() }]
        );
        throw error;
      }
    };

    initializeProcessing();
  }, []); // Empty dependency array - only run once on mount

  // Pulse animation for current step
  useEffect(() => {
    if (!isComplete) {
      Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 1.2,
            duration: 1000,
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 1000,
            useNativeDriver: true,
          }),
        ])
      ).start();
    }
  }, [currentStep, isComplete]);

  // Bounce animation for dots
  useEffect(() => {
    if (!isComplete) {
      bounceAnims.forEach((anim, index) => {
        Animated.loop(
          Animated.sequence([
            Animated.timing(anim, {
              toValue: 1,
              duration: 600,
              delay: index * 200,
              useNativeDriver: true,
            }),
            Animated.timing(anim, {
              toValue: 0,
              duration: 600,
              useNativeDriver: true,
            }),
          ])
        ).start();
      });
    }
  }, [currentStep, isComplete]);

  return (
    <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
      {/* Processing Header */}
      <View style={[styles.header, { backgroundColor: colors.primary, paddingTop: insets.top + 8 }]}>
        <View style={styles.headerContent}>
          {/* Processing Animation */}
          <View style={styles.processingCircle}>
            {!isComplete ? (
              <>
                <Animated.View style={[styles.pulseCircle, { transform: [{ scale: pulseAnim }] }]} />
                <Icon name="loader" size={48} color={colors.primary} style={styles.spinner} />
              </>
            ) : (
              <Icon name="check-circle" size={48} color={colors.primary} />
            )}
          </View>
          
          <Text style={styles.headerTitle}>
            {isComplete ? '¡Casi listo!' : transactionData.action}
          </Text>
          
          <Text style={styles.headerAmount}>
            ${transactionData.amount} {transactionData.currency}
          </Text>
          
          <Text style={styles.headerSubtitle}>
            {transactionData.type === 'sent' 
              ? `Para ${transactionData.recipient}`
              : `En ${transactionData.merchant}`
            }
          </Text>
        </View>
      </View>

      {/* Processing Steps */}
      <View style={styles.content}>
        <View style={styles.stepsContainer}>
          {processingSteps.map((step, index) => (
            <View key={index} style={styles.stepRow}>
              {/* Step Icon */}
              {index === currentStep && !isComplete ? (
                <Animated.View style={[
                  styles.stepIcon,
                  { 
                    backgroundColor: index <= currentStep ? step.bgColor : '#F3F4F6',
                    transform: [{ scale: pulseAnim }]
                  }
                ]}>
                  <Icon 
                    name={step.icon as any} 
                    size={24} 
                    color={index <= currentStep ? step.color : '#9CA3AF'} 
                  />
                </Animated.View>
              ) : (
                <View style={[
                  styles.stepIcon,
                  { 
                    backgroundColor: index <= currentStep ? step.bgColor : '#F3F4F6'
                  }
                ]}>
                  <Icon 
                    name={step.icon as any} 
                    size={24} 
                    color={index <= currentStep ? step.color : '#9CA3AF'} 
                  />
                </View>
              )}

              {/* Step Text */}
              <View style={styles.stepTextContainer}>
                <Text style={[
                  styles.stepText,
                  { color: index <= currentStep ? colors.text.primary : '#9CA3AF' }
                ]}>
                  {step.text}
                </Text>
                {index === currentStep && !isComplete && (
                  <View style={styles.dotsContainer}>
                    {bounceAnims.map((anim, dotIndex) => (
                      <Animated.View
                        key={dotIndex}
                        style={[
                          styles.dot,
                          {
                            transform: [{ translateY: anim.interpolate({
                              inputRange: [0, 1],
                              outputRange: [0, -8]
                            }) }]
                          }
                        ]}
                      />
                    ))}
                  </View>
                )}
              </View>

              {/* Checkmark */}
              {index < currentStep && (
                <Icon name="check-circle" size={20} color={colors.success} />
              )}
              {index === currentStep && isComplete && (
                <Icon name="check-circle" size={20} color={colors.success} />
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
                { width: `${((currentStep + 1) / processingSteps.length) * 100}%` }
              ]}
            />
          </View>
          <View style={styles.progressLabels}>
            <Text style={styles.progressLabel}>0%</Text>
            <Text style={styles.progressLabel}>50%</Text>
            <Text style={styles.progressLabel}>100%</Text>
          </View>
        </View>

        {/* Security Message */}
        <View style={styles.securityContainer}>
          <View style={styles.securityContent}>
            <Icon name="shield" size={20} color={colors.primary} />
            <Text style={styles.securityText}>
              <Text style={styles.securityBold}>Transacción segura</Text> • Protegido por blockchain
            </Text>
          </View>
        </View>

        {/* Processing Info */}
        <View style={styles.infoContainer}>
          <View style={styles.infoContent}>
            <Icon name="clock" size={16} color={colors.primary} />
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
          <View style={styles.completionContainer}>
            <View style={styles.completionContent}>
              <Icon name="check-circle" size={32} color={colors.success} />
              <Text style={styles.completionTitle}>¡Transacción completada!</Text>
              <Text style={styles.completionText}>Redirigiendo a confirmación...</Text>
            </View>
          </View>
        )}
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingBottom: 48,
    paddingHorizontal: 16,
  },
  headerContent: {
    alignItems: 'center',
  },
  processingCircle: {
    width: 96,
    height: 96,
    backgroundColor: '#ffffff',
    borderRadius: 48,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 24,
    marginBottom: 24,
    position: 'relative',
  },
  pulseCircle: {
    position: 'absolute',
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.primary,
    opacity: 0.2,
  },
  spinner: {
    transform: [{ rotate: '0deg' }],
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#ffffff',
    marginBottom: 8,
  },
  headerAmount: {
    fontSize: 36,
    fontWeight: 'bold',
    color: '#ffffff',
    marginBottom: 16,
  },
  headerSubtitle: {
    fontSize: 18,
    color: '#ffffff',
    opacity: 0.9,
  },
  content: {
    paddingHorizontal: 16,
    marginTop: -32,
    paddingBottom: 32,
  },
  stepsContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 32,
    marginBottom: 24,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 24,
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
  dotsContainer: {
    flexDirection: 'row',
    marginTop: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.primary,
    marginRight: 4,
  },
  progressContainer: {
    marginBottom: 24,
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
    backgroundColor: colors.primary,
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
  securityContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
    marginBottom: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
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
    color: colors.primary,
  },
  infoContainer: {
    backgroundColor: '#D1FAE5',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
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
    fontWeight: '600',
    color: '#065F46',
    marginBottom: 4,
  },
  infoText: {
    fontSize: 12,
    color: '#047857',
    lineHeight: 16,
  },
  completionContainer: {
    backgroundColor: '#D1FAE5',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  completionContent: {
    alignItems: 'center',
  },
  completionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#065F46',
    marginTop: 8,
    marginBottom: 4,
  },
  completionText: {
    fontSize: 12,
    color: '#047857',
  },
}); 