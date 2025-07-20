import React, { useState } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, TextInput, Image, Modal } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { useMutation } from '@apollo/client';
import { CREATE_SEND_TRANSACTION } from '../apollo/queries';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';

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
  warning: {
    background: '#FEF3C7', // yellow-50
    border: '#FDE68A', // yellow-200
    text: '#92400E', // yellow-800
    icon: '#D97706', // yellow-600
  },
};

type TokenType = 'cusd' | 'confio';

const tokenConfig = {
  cusd: {
    name: 'cUSD',
    fullName: 'Confío Dollar',
    logo: cUSDLogo,
    color: colors.primary,
    minSend: 1,
    available: '2,850.35',
    fee: 0.02,
    description: 'Envía cUSD a cualquier dirección Sui',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
  confio: {
    name: 'CONFIO',
            fullName: 'Confío',
    logo: CONFIOLogo,
    color: colors.secondary,
    minSend: 1,
    available: '1,000.00',
    fee: 0.02,
    description: 'Envía CONFIO a cualquier dirección Sui',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
};

type Friend = {
  name: string;
  avatar: string;
  isOnConfio: boolean;
  phone: string;
};

export const SendToFriendScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  const insets = useSafeAreaInsets();
  
  const friend: Friend = (route.params as any)?.friend || { name: 'Friend', avatar: 'F', isOnConfio: true, phone: '' };
  
  // Debug log to check friend data
  console.log('SendToFriendScreen: friend data:', friend);
  console.log('SendToFriendScreen: friend.isOnConfio:', friend.isOnConfio);
  const [tokenType, setTokenType] = useState<TokenType>((route.params as any)?.tokenType || 'cusd');
  const config = tokenConfig[tokenType];

  const [amount, setAmount] = useState('');
  const [showSuccess, setShowSuccess] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  // GraphQL mutation for creating send transaction
  const [createSendTransaction] = useMutation(CREATE_SEND_TRANSACTION);

  const handleQuickAmount = (val: string) => setAmount(val);

  const handleSend = async () => {
    console.log('SendToFriendScreen: handleSend called');
    if (!amount || parseFloat(amount) < config.minSend) {
      setErrorMessage(`El mínimo para enviar es ${config.minSend} ${config.name}`);
      setShowError(true);
      return;
    }
    
    try {
      console.log('SendToFriendScreen: Creating send transaction...');
      
      // For now, use a mock Sui address for the friend
      // In a real implementation, this would come from the friend's profile
      const friendSuiAddress = friend.isOnConfio 
        ? '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef' // Mock address
        : '0x0000000000000000000000000000000000000000000000000000000000000000'; // External address
      
      const { data } = await createSendTransaction({
        variables: {
          input: {
            recipientAddress: friendSuiAddress,
            amount: amount,
            tokenType: config.name,
            memo: `Send ${amount} ${config.name} to ${friend.name}${friend.phone ? ` (${friend.phone})` : ''}`
          }
        }
      });

      console.log('SendToFriendScreen: Send transaction created:', data);

      if (data?.createSendTransaction?.success) {
        console.log('SendToFriendScreen: Navigating to TransactionProcessing');
        // Navigate to processing screen with transaction data
        (navigation as any).replace('TransactionProcessing', {
          transactionData: {
            type: 'sent',
            amount: amount,
            currency: config.name,
            recipient: friend.name,
            recipientPhone: friend.phone,
            action: 'Enviando',
            isOnConfio: friend.isOnConfio,
            sendTransactionId: data.createSendTransaction.sendTransaction.id,
            recipientAddress: friendSuiAddress
          }
        });
      } else {
        const errors = data?.createSendTransaction?.errors || ['Error desconocido'];
        setErrorMessage(errors.join(', '));
        setShowError(true);
      }
    } catch (error) {
      console.error('SendToFriendScreen: Error creating send transaction:', error);
      setErrorMessage('Error al crear la transacción. Inténtalo de nuevo.');
      setShowError(true);
    }
  };

  return (
    <View style={styles.container}>
      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Header */}
        <View style={[styles.header, { backgroundColor: config.color, paddingTop: insets.top + 8 }]}> 
          <View style={styles.headerContent}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
              <Icon name="arrow-left" size={24} color="#ffffff" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Enviar a {friend.name}</Text>
            <View style={styles.placeholder} />
          </View>
          <View style={styles.headerInfo}>
            <View style={styles.friendAvatarContainer}>
              <Text style={styles.friendAvatarText}>{friend.avatar}</Text>
            </View>
            <Text style={styles.headerSubtitle}>{friend.name}</Text>
            {friend.phone && friend.phone !== friend.name && friend.phone.trim() !== '' && (
              <Text style={styles.headerPhone}>{friend.phone}</Text>
            )}
            <Text style={styles.headerDescription}>Enviar {config.name} a tu amigo</Text>
          </View>
        </View>

        {/* Available Balance */}
        <View style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>Saldo disponible</Text>
          <Text style={styles.balanceAmount}>{config.available} {config.name}</Text>
          <Text style={styles.balanceMin}>Mínimo para enviar: {config.minSend} {config.name}</Text>
        </View>

        {/* Send Form */}
        <View style={styles.formCard}>
          {/* Amount Input */}
          <View style={styles.inputContainer}>
            <Text style={styles.inputLabel}>Cantidad a enviar</Text>
            <View style={styles.amountContainer}>
              <TextInput
                style={[styles.amountField, { flex: 1 }]}
                value={amount}
                onChangeText={setAmount}
                placeholder="0.00"
                keyboardType="numeric"
              />
              <View style={styles.currencyBadge}>
                <Image source={config.logo} style={styles.currencyBadgeLogo} />
                <Text style={styles.currencyBadgeText}>{config.name}</Text>
              </View>
            </View>
            <View style={styles.quickAmounts}>
              {config.quickAmounts.map((val) => (
                <TouchableOpacity 
                  key={val}
                  onPress={() => handleQuickAmount(val)}
                  style={styles.quickAmountButton}
                >
                  <Text style={styles.quickAmountText}>${val}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          {/* Fee Breakdown */}
          <View style={styles.feeBreakdown}>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de red</Text>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <Text style={styles.feeValueFree}>Gratis</Text>
                <Text style={styles.feeValueNote}>• Cubierto por Confío</Text>
              </View>
            </View>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Tiempo estimado</Text>
              <View style={styles.timeContainer}>
                <Icon name="clock" size={12} color={config.color} style={styles.timeIcon} />
                <Text style={styles.timeText}>3-5 segundos</Text>
              </View>
            </View>
            <View style={styles.feeDivider} />
            <View style={styles.feeRow}>
              <Text style={styles.feeTotalLabel}>Total a enviar</Text>
              <Text style={styles.feeTotalValue}>
                {amount ? parseFloat(amount).toFixed(2) : '0.00'} {config.name}
              </Text>
            </View>
          </View>

          {/* Confío Value Proposition */}
          <View style={styles.valuePropositionOuter}>
            <View style={styles.valueRow}>
              <Icon name="check-circle" size={20} color={colors.primary} style={styles.valueIcon} />
              <Text style={styles.valueTitle}>Transferencias 100% gratuitas</Text>
            </View>
            <Text style={styles.valueDescription}>
              Enviarás este dinero sin pagar comisiones
            </Text>
            <View style={styles.valueHighlightBox}>
              <Text style={styles.valueHighlightText}>
                💡 <Text style={styles.bold}>Confío: 0% comisión</Text>{'\n'}
                vs. remesadoras tradicionales <Text style={styles.bold}>(5%-20%)</Text>{'\n'}
                Apoyamos a los venezolanos 🇻🇪 con transferencias gratuitas
              </Text>
            </View>
          </View>

          <TouchableOpacity 
            style={[
              styles.confirmButton,
              (!amount || parseFloat(amount) < config.minSend) && styles.confirmButtonDisabled
            ]}
            disabled={!amount || parseFloat(amount) < config.minSend}
            onPress={() => {
              console.log('SendToFriendScreen: Button pressed');
              console.log('SendToFriendScreen: amount:', amount);
              console.log('SendToFriendScreen: config.minSend:', config.minSend);
              console.log('SendToFriendScreen: button disabled:', !amount || parseFloat(amount) < config.minSend);
              handleSend();
            }}
          >
            <Text style={styles.confirmButtonText}>Enviar a {friend.name}</Text>
          </TouchableOpacity>

          {showSuccess && (
            <View style={styles.successBox}>
              <Icon name="check-circle" size={32} color={config.color} />
              <Text style={styles.successText}>¡Envío realizado!</Text>
            </View>
          )}
          {showError && (
            <View style={styles.errorBox}>
              <Icon name="alert-triangle" size={28} color={colors.warning.icon} />
              <Text style={styles.errorText}>{errorMessage}</Text>
              <TouchableOpacity onPress={() => setShowError(false)}>
                <Text style={styles.errorDismiss}>Cerrar</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    flexGrow: 1,
    paddingBottom: 32,
  },
  header: {
    paddingBottom: 32,
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 24,
  },
  backButton: {
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#ffffff',
  },
  placeholder: {
    width: 40,
  },
  headerInfo: {
    alignItems: 'center',
  },
  friendAvatarContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#ffffff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  friendAvatarText: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.primary,
  },
  headerSubtitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#ffffff',
    marginBottom: 8,
  },
  headerPhone: {
    fontSize: 14,
    color: '#ffffff',
    opacity: 0.8,
  },
  headerDescription: {
    fontSize: 14,
    color: '#ffffff',
    opacity: 0.8,
  },
  balanceCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    marginHorizontal: 16,
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
  balanceLabel: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  balanceAmount: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  balanceMin: {
    fontSize: 14,
    color: '#6B7280',
  },
  formCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
    marginHorizontal: 16,
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
  inputContainer: {
    marginBottom: 24,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#374151',
    marginBottom: 8,
  },
  amountContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F0F6FF',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 8,
  },
  amountField: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F2937',
    backgroundColor: 'transparent',
    borderWidth: 0,
  },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 8,
  },
  currencyBadgeLogo: {
    width: 32,
    height: 32,
    resizeMode: 'contain',
    marginRight: 6,
  },
  currencyBadgeText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#2563eb',
  },
  quickAmounts: {
    flexDirection: 'row',
    marginTop: 12,
    gap: 8,
  },
  quickAmountButton: {
    backgroundColor: colors.accent + '20',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 16,
  },
  quickAmountText: {
    fontSize: 12,
    color: colors.accent,
  },
  feeBreakdown: {
    marginBottom: 24,
  },
  feeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  feeLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  feeValueFree: {
    fontSize: 14,
    fontWeight: '500',
    color: '#10b981',
  },
  feeValueNote: {
    fontSize: 12,
    color: '#6B7280',
  },
  timeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  timeIcon: {
    marginRight: 4,
  },
  timeText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  feeDivider: {
    height: 1,
    backgroundColor: '#E5E7EB',
    marginVertical: 12,
  },
  feeTotalLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
  },
  feeTotalValue: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.accent,
  },
  confirmButton: {
    backgroundColor: colors.accent,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  confirmButtonDisabled: {
    opacity: 0.5,
  },
  confirmButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  successBox: {
    alignItems: 'center',
    marginTop: 16,
    marginBottom: 8,
  },
  successText: {
    color: colors.primary,
    fontSize: 16,
    fontWeight: '600',
    marginTop: 8,
  },
  errorBox: {
    alignItems: 'center',
    marginTop: 16,
    marginBottom: 8,
    backgroundColor: colors.warning.background,
    borderRadius: 8,
    padding: 12,
  },
  errorText: {
    color: colors.warning.text,
    fontSize: 15,
    fontWeight: '500',
    marginTop: 8,
    marginBottom: 4,
    textAlign: 'center',
  },
  errorDismiss: {
    color: colors.warning.icon,
    fontWeight: 'bold',
    marginTop: 8,
    fontSize: 14,
  },
  valuePropositionOuter: {
    backgroundColor: '#A7F3D0', // emerald-200
    borderRadius: 16,
    padding: 16,
    marginBottom: 24,
    marginHorizontal: 0,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  valueIcon: {
    marginRight: 8,
  },
  valueTitle: {
    fontWeight: 'bold',
    fontSize: 16,
    color: '#059669',
  },
  valueDescription: {
    fontSize: 14,
    color: '#059669',
    marginBottom: 12,
  },
  valueHighlightBox: {
    backgroundColor: '#D1FAE5', // emerald-100
    borderRadius: 12,
    padding: 14,
  },
  valueHighlightText: {
    fontSize: 14,
    color: '#065F46',
    lineHeight: 20,
  },
  bold: {
    fontWeight: 'bold',
  },
}); 