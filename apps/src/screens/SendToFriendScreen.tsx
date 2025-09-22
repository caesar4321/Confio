import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, TextInput, Image, Modal, ActivityIndicator } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useNumberFormat } from '../utils/numberFormatting';

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
    fee: 0,  // Sponsored transactions
    description: 'Envía cUSD a cualquier dirección Algorand',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
  confio: {
    name: 'CONFIO',
    fullName: 'Confío',
    logo: CONFIOLogo,
    color: colors.secondary,
    minSend: 1,
    fee: 0,  // Sponsored transactions
    description: 'Envía CONFIO a cualquier dirección Algorand',
    quickAmounts: ['10.00', '50.00', '100.00'],
  },
};

type Friend = {
  name: string;
  avatar: string;
  isOnConfio: boolean;
  phone: string;
  algorandAddress?: string;
  userId?: string;
  id?: string; // Some screens pass 'id' instead of 'userId'
};

export const SendToFriendScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  // Safe area handled with SafeAreaView
  const { formatNumber } = useNumberFormat();
  
  const friend: Friend = (route.params as any)?.friend || { name: 'Friend', avatar: 'F', isOnConfio: true, phone: '' };
  
  // Debug log to check friend data
  console.log('SendToFriendScreen: route.params:', route.params);
  console.log('SendToFriendScreen: friend data:', friend);
  console.log('SendToFriendScreen: friend.isOnConfio:', friend.isOnConfio);
  console.log('SendToFriendScreen: friend.algorandAddress:', friend.algorandAddress);
  console.log('SendToFriendScreen: friend.algorandAddress length:', friend.algorandAddress?.length);
  const [tokenType, setTokenType] = useState<TokenType>((route.params as any)?.tokenType || 'cusd');
  const config = tokenConfig[tokenType];

  const [amount, setAmount] = useState('');
  const [showSuccess, setShowSuccess] = useState(false);
  const [showError, setShowError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const navLock = React.useRef(false);
  const [prepared, setPrepared] = useState<any | null>(null);

  // Balance snapshot + background refresh
  const [balanceSnapshot, setBalanceSnapshot] = useState<string | null>(null);
  const [balanceLoading, setBalanceLoading] = useState<boolean>(false);
  useEffect(() => {
    let mounted = true;
    const tok = tokenType.toUpperCase();
    try {
      const cached = apolloClient.readQuery<{ accountBalance: string }>({
        query: GET_ACCOUNT_BALANCE,
        variables: { tokenType: tok }
      });
      if (cached?.accountBalance && mounted) setBalanceSnapshot(cached.accountBalance);
    } catch {}
    setBalanceLoading(true);
    apolloClient.query<{ accountBalance: string }>({
      query: GET_ACCOUNT_BALANCE,
      variables: { tokenType: tok },
      fetchPolicy: 'network-only'
    }).then(res => {
      if (!mounted) return;
      setBalanceSnapshot(res.data?.accountBalance ?? null);
    }).catch(() => {}).finally(() => mounted && setBalanceLoading(false));
    return () => { mounted = false; };
  }, [tokenType]);
  const availableBalance = React.useMemo(() => parseFloat(balanceSnapshot || '0'), [balanceSnapshot]);

  // Prevent overstatement: floor display to 2 decimals
  const floorToDecimals = React.useCallback((value: number, decimals: number) => {
    if (!isFinite(value)) return 0;
    const m = Math.pow(10, decimals);
    return Math.floor(value * m) / m;
  }, []);

  const formatFixedFloor = React.useCallback((value: number, decimals = 2) => {
    const floored = floorToDecimals(value, decimals);
    return floored.toLocaleString('es-ES', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }, [floorToDecimals]);

  // Mutations are now handled in TransactionProcessingScreen

  const handleQuickAmount = (val: string) => setAmount(val);

  // Background preflight via WebSocket when inputs look valid
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setPrepared(null);
        const amt = parseFloat(String(amount || '0'));
        if (!(isFinite(amt) && amt > 0 && friend && friend.isOnConfio !== false)) return;
        const assetType = (tokenType.toUpperCase() === 'CUSD' ? 'CUSD' : 'CONFIO');
        const { prepareSendViaWs } = await import('../services/sendWs');
        const pack = await prepareSendViaWs({
          amount: amt,
          assetType,
          recipientUserId: friend.userId || friend.id,
          recipientPhone: friend.phone,
        });
        if (!alive) return;
        if (pack && Array.isArray((pack as any).transactions) && (pack as any).transactions.length >= 2) {
          setPrepared({ transactions: (pack as any).transactions });
          console.log('SendToFriendScreen: Preflight prepared via WS');
        }
      } catch (e) {
        // ignore preflight errors; processing screen will fallback
      }
    })();
    return () => { alive = false; };
  }, [amount, tokenType, friend?.userId, friend?.id, friend?.phone, friend?.isOnConfio]);

  const handleSend = async () => {
    console.log('SendToFriendScreen: handleSend called');
    
    // Prevent double-clicks/rapid button presses
    if (isProcessing || navLock.current) {
      console.log('SendToFriendScreen: Already processing, ignoring duplicate click');
      return;
    }
    
    if (!amount || parseFloat(amount) < config.minSend) {
      setErrorMessage(`El mínimo para enviar es ${config.minSend} ${config.name}`);
      setShowError(true);
      return;
    }
    
    setIsProcessing(true);
    navLock.current = true;
    
    try {
      console.log('SendToFriendScreen: Navigating to TransactionProcessing');
      
      // For idempotency key, we need a stable identifier
      // For Confío users, use their user ID; for non-Confío, use phone number hash
      let recipientIdentifier: string;
      if (friend.isOnConfio && (friend.userId || friend.id)) {
        recipientIdentifier = friend.userId || friend.id || 'unknown';
      } else if (friend.phone) {
        // For non-Confío users, create a hash of the phone number
        const phoneHash = Array.from(friend.phone).reduce((hash, char) => ((hash << 5) - hash) + char.charCodeAt(0), 0);
        recipientIdentifier = Math.abs(phoneHash).toString(16).padStart(8, '0');
      } else {
        recipientIdentifier = 'unknown';
      }
      
      // Generate idempotency key to prevent double-spending
      // Use full timestamp (not just minute) to allow multiple transactions
      const timestamp = Date.now();
      const amountStr = amount.replace('.', '');
      const idempotencyKey = `send_${recipientIdentifier}_${amountStr}_${config.name}_${timestamp}`;
      
      // Navigate to processing screen with transaction data
      (navigation as any).replace('TransactionProcessing', {
        transactionData: {
          type: 'sent',
          amount: amount,
          currency: config.name,
          recipient: friend.name,
          recipientPhone: friend.phone,
          recipientUserId: friend.userId || friend.id, // Pass user ID if available
          action: 'Enviando',
          isOnConfio: friend.isOnConfio,
          // recipientAddress removed - server will determine this
          memo: '', // Empty memo - user can add notes in a future feature
          idempotencyKey: idempotencyKey,
          prepared: prepared
        }
      });
    } catch (error) {
      console.error('SendToFriendScreen: Error navigating to processing screen:', error);
      setErrorMessage('Error al procesar la transacción. Inténtalo de nuevo.');
      setShowError(true);
    } finally {
      setTimeout(() => {
        setIsProcessing(false);
        navLock.current = false;
      }, 600);
    }
  };

  return (
    <View style={styles.container}>
      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Header */}
        <SafeAreaView edges={['top']} style={{ backgroundColor: config.color }}>
        <View style={[styles.header, { backgroundColor: config.color, paddingTop: 8 }]}> 
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
        </SafeAreaView>

        {/* Available Balance */}
        <View style={styles.balanceCard}>
          <Text style={styles.balanceLabel}>Saldo disponible</Text>
          {balanceLoading ? (
            <ActivityIndicator size="small" color={config.color} style={{ marginVertical: 8 }} />
          ) : (
            <Text style={styles.balanceAmount}>
              {formatFixedFloor(availableBalance, 2)} {config.name}
            </Text>
          )}
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
                {amount ? formatNumber(parseFloat(amount)) : formatNumber(0)} {config.name}
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
              (!amount || parseFloat(amount) < config.minSend || parseFloat(amount || '0') > availableBalance || isProcessing) && styles.confirmButtonDisabled
            ]}
            disabled={!amount || parseFloat(amount) < config.minSend || parseFloat(amount || '0') > availableBalance || isProcessing}
            onPress={() => {
              console.log('SendToFriendScreen: Button pressed');
              console.log('SendToFriendScreen: amount:', amount);
              console.log('SendToFriendScreen: config.minSend:', config.minSend);
              console.log('SendToFriendScreen: availableBalance:', availableBalance);
              console.log('SendToFriendScreen: button disabled:', !amount || parseFloat(amount) < config.minSend || parseFloat(amount || '0') > availableBalance || isProcessing);
              handleSend();
            }}
          >
            <Text style={styles.confirmButtonText}>
              {isProcessing ? 'Procesando...' : 
               balanceSnapshot == null ? 'Cargando saldo…' : 
               parseFloat(amount || '0') > availableBalance ? 'Saldo insuficiente' : 
               `Enviar a ${friend.name}`}
            </Text>
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
