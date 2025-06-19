import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Platform, Animated, ScrollView } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect } from '@react-navigation/native';

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
    action: 'Enviando'
  };

  const [currentStep, setCurrentStep] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [pulseAnim] = useState(new Animated.Value(1));
  const [bounceAnims] = useState([
    new Animated.Value(0),
    new Animated.Value(0),
    new Animated.Value(0)
  ]);

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

  // Prevent back navigation
  useFocusEffect(
    React.useCallback(() => {
      const onBackPress = () => {
        // Prevent back navigation during processing
        return true;
      };

      // In a real app, you'd use navigation.setOptions to disable back button
      return () => {};
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
            (navigation as any).replace('TransactionSuccess', { transactionData });
          }, 2000);
          return prev;
        }
      });
    }, 1500); // 1.5 seconds per step

    return () => clearInterval(timer);
  }, []);

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