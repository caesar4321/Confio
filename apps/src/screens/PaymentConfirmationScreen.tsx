import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Alert,
  Dimensions,
  Platform,
  StatusBar,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp, StackActions, useFocusEffect } from '@react-navigation/native';
import { useCallback } from 'react';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import { prepareViaWs } from '../services/payWs';
import { useAccount } from '../contexts/AccountContext';
import { colors } from '../config/theme';
import { formatNumber } from '../utils/numberFormatting';
import { useMutation } from '@apollo/client';
import { GET_INVOICE } from '../apollo/queries';

type PaymentConfirmationRouteProp = RouteProp<{
  PaymentConfirmation: {
    invoiceData: {
      id: string;
      internalId: string;
      amount: string;
      tokenType: string;
      description?: string;
      merchantUser: {
        id: string;
        username: string;
        firstName?: string;
        lastName?: string;
      };
      merchantAccount: {
        id: string;
        accountType: string;
        accountIndex: number;
        algorandAddress: string;
        business?: {
          id: string;
          name: string;
          category: string;
          address?: string;
        };
      };
      isExpired: boolean;
    };
  };
}, 'PaymentConfirmation'>;

interface WalletData {
  symbol: string;
  name: string;
  balance: string;
  color: string;
  icon: string;
}

export const PaymentConfirmationScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<PaymentConfirmationRouteProp>();
  const { activeAccount } = useAccount();
  const [isProcessing, setIsProcessing] = useState(false);
  const [prepared, setPrepared] = useState<any | null>(null);
  const [prepareError, setPrepareError] = useState<string | null>(null);
  const navLock = useRef(false);

  // Extract params (invoiceData is normal flow, invoiceId is deep link)
  const { invoiceData: initialInvoiceData, invoiceId } = route.params as any;

  // State for invoice data (fetched or passed)
  const [fetchedInvoiceData, setFetchedInvoiceData] = useState<any | null>(initialInvoiceData || null);
  const [isFetchingInvoice, setIsFetchingInvoice] = useState(false);

  // Use mutation to fetch invoice (aligned with ScanScreen usage)
  const [getInvoice] = useMutation(GET_INVOICE);

  // Fetch logic
  const fetchInvoice = async (id: string) => {
    setIsFetchingInvoice(true);
    try {
      // NOTE: GET_INVOICE is a Mutation in apollo/queries.ts that returns { getInvoice: { invoice, success, errors } }
      // We use the mutation hook [getInvoice]
      const { data } = await getInvoice({ variables: { invoiceId: id } });

      if (data?.getInvoice?.success && data?.getInvoice?.invoice) {
        setFetchedInvoiceData(data.getInvoice.invoice);
      } else {
        const msg = data?.getInvoice?.errors?.[0] || 'Factura no encontrada';
        Alert.alert('Error', msg);
        navigation.goBack();
      }
    } catch (e: any) {
      console.error('Error fetching invoice:', e);
      Alert.alert('Error', 'No se pudo cargar la factura. Verifique su conexión.');
      navigation.goBack();
    } finally {
      setIsFetchingInvoice(false);
    }
  };

  // Effect to trigger fetch if needed
  useEffect(() => {
    // If we have initial data, update state (unlikely to change but good practice)
    if (initialInvoiceData && !fetchedInvoiceData) {
      setFetchedInvoiceData(initialInvoiceData);
      return;
    }

    // If passed via deep link and we don't have data yet
    if (invoiceId && !fetchedInvoiceData && !isFetchingInvoice) {
      console.log('PaymentConfirmation: Deep link detected, fetching invoice', invoiceId);
      fetchInvoice(invoiceId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invoiceId, initialInvoiceData]);

  // ALIAS for the rest of the component
  const invoiceData = fetchedInvoiceData;
  const safeInvoiceId = invoiceData?.internalId || '';
  const safeTokenType = invoiceData?.tokenType || 'cUSD';

  // Helper function to format amount with 2 decimal places
  const formatAmount = (amount: string | number): string => {
    const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount;
    return numAmount.toFixed(2);
  };

  // Function to translate business categories to user-friendly Spanish labels
  const translateCategory = (category: string): string => {
    const categoryTranslations: { [key: string]: string } = {
      'FOOD': 'Comida y Bebidas',
      'RETAIL': 'Comercio Minorista',
      'SERVICES': 'Servicios',
      'HEALTHCARE': 'Salud',
      'EDUCATION': 'Educación',
      'TRANSPORTATION': 'Transporte',
      'ENTERTAINMENT': 'Entretenimiento',
      'FINANCIAL': 'Servicios Financieros',
      'TECHNOLOGY': 'Tecnología',
      'BEAUTY': 'Belleza y Cuidado Personal',
      'AUTOMOTIVE': 'Automotriz',
      'REAL_ESTATE': 'Bienes Raíces',
      'MANUFACTURING': 'Manufactura',
      'CONSTRUCTION': 'Construcción',
      'AGRICULTURE': 'Agricultura',
      'TOURISM': 'Turismo',
      'SPORTS': 'Deportes',
      'ARTS': 'Arte y Cultura',
      'NON_PROFIT': 'Organización Sin Fines de Lucro',
      'OTHER': 'Otros'
    };

    return categoryTranslations[category.toUpperCase()] || category;
  };

  // Normalize token type for balance query
  const normalizeTokenType = (tokenType: string) => {
    if (tokenType === 'CUSD') return 'cUSD';
    return tokenType;
  };

  // Balance snapshot from Apollo cache, refresh in background only
  const [balanceSnapshot, setBalanceSnapshot] = useState<string | null>(null);
  const [balanceLoading, setBalanceLoading] = useState<boolean>(false);
  const [balanceError, setBalanceError] = useState<string | null>(null);

  useEffect(() => {
    if (!invoiceData) return; // Guard clause
    let mounted = true;
    const token = normalizeTokenType(safeTokenType);
    try {
      // Read from cache only (no network)
      const cached = apolloClient.readQuery<{ accountBalance: string }>({
        query: GET_ACCOUNT_BALANCE,
        variables: { tokenType: token }
      });
      if (cached?.accountBalance && mounted) {
        setBalanceSnapshot(cached.accountBalance);
      }
    } catch (_) {
      // cache miss is fine
    }
    // Background refresh (non-blocking)
    setBalanceLoading(true);
    apolloClient.query<{ accountBalance: string }>({
      query: GET_ACCOUNT_BALANCE,
      variables: { tokenType: token },
      fetchPolicy: 'network-only'
    }).then((res) => {
      if (!mounted) return;
      setBalanceSnapshot(res.data?.accountBalance ?? null);
      setBalanceError(null);
    }).catch((err) => {
      if (!mounted) return;
      setBalanceError(err?.message || '');
    }).finally(() => {
      if (mounted) setBalanceLoading(false);
    });
    return () => { mounted = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safeTokenType]);

  // Background preflight: create the sponsored payment so confirm only signs+submits
  useEffect(() => {
    if (!invoiceData) return;
    let alive = true;

    const runPreflight = async () => {
      try {
        setPrepareError(null);
        const amt = parseFloat(String(invoiceData.amount || '0'));
        const assetType = (String(invoiceData.tokenType || 'cUSD')).toUpperCase();
        const note = `Invoice ${invoiceData.internalId}`;

        // Try WebSocket fast path first
        const wsPack = await prepareViaWs({
          amount: amt,
          assetType,
          internalId: invoiceData.internalId,
          note,
          recipientBusinessId: invoiceData.merchantAccount?.business?.id
        });

        if (alive && wsPack && Array.isArray(wsPack.transactions) && wsPack.transactions.length === 4) {
          setPrepared({
            transactions: wsPack.transactions,
            paymentId: (wsPack as any).internalId || (wsPack as any).internal_id || (wsPack as any).paymentId || (wsPack as any).payment_id || invoiceData.internalId,
            groupId: (wsPack as any).groupId || (wsPack as any).group_id
          });
          console.log('PaymentConfirmationScreen: Preflight prepared via WS');
          return;
        }

        // WS-only mode: if WS pack missing/invalid, record error
        if (alive) {
          setPrepareError('Failed to prepare payment via WebSocket');
          console.log('PaymentConfirmationScreen: Preflight failed via WS');
        }
      } catch (e: any) {
        if (alive) setPrepareError(e?.message || 'Failed to prepare payment');
        console.log('PaymentConfirmationScreen: Preflight exception', e?.message || e);
      }
    };

    runPreflight();

    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safeInvoiceId]);

  // Loading state (Render phase) - placed AFTER all hooks
  if (isFetchingInvoice) {
    return (
      <SafeAreaView style={[styles.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <View style={{ padding: 20, alignItems: 'center' }}>
          <Text style={{ marginTop: 10, color: '#666' }}>Cargando detalles del pago...</Text>
        </View>
      </SafeAreaView>
    );
  }

  // Guard: if no data, don't render content
  if (!invoiceData) {
    return (
      <SafeAreaView style={styles.container} />
    );
  }

  const currentPayment = {
    type: 'merchant',
    recipient: invoiceData.merchantAccount.business?.name ||
      invoiceData.merchantUser.firstName ||
      invoiceData.merchantUser.username,
    recipientType: translateCategory(invoiceData.merchantAccount.business?.category || 'Usuario'),
    amount: invoiceData.amount,
    currency: normalizeTokenType(invoiceData.tokenType),
    description: invoiceData.description,
    location: invoiceData.merchantAccount.business?.address || 'Dirección no disponible',
    merchantId: invoiceData.merchantAccount.id,
    paymentId: invoiceData.internalId,
    avatar: (invoiceData.merchantAccount.business?.name ||
      invoiceData.merchantUser.firstName ||
      invoiceData.merchantUser.username).charAt(0).toUpperCase(),
    verification: 'Verificado ✓'
  };

  // Use snapshot balance; no immediate network dependency
  const realBalance = balanceSnapshot || '0';

  // Fallback to mock values only if explicit error (dev/test)
  const mockBalances: { [key: string]: string } = {
    'cUSD': '2850.35',
    'CUSD': '2850.35', // Handle both cases
    'CONFIO': '234.18',
    'USDC': '458.22'
  };

  const fallbackBalance = balanceError ? mockBalances[invoiceData.tokenType] || '0' : realBalance;
  const hasEnoughBalance = balanceSnapshot != null && parseFloat(fallbackBalance) >= parseFloat(currentPayment.amount);

  // Prevent overstatement: floor-based formatting with tiny-balance label
  const floorToDecimals = (value: number, decimals: number) => {
    if (!isFinite(value)) return 0;
    const m = Math.pow(10, decimals);
    return Math.floor(value * m) / m;
  };
  const formatFixedFloor = (value: number, decimals = 2) => {
    const floored = floorToDecimals(value, decimals);
    return floored.toLocaleString('es-ES', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  };
  const formatBalanceDisplay = (valueStr: string | number) => {
    const v = typeof valueStr === 'string' ? parseFloat(valueStr) : valueStr;
    if (!isFinite(v) || v <= 0) return '0.00';
    if (v < 0.01) return '< 0.01';
    return formatFixedFloor(v, 2);
  };

  // Debug logging
  console.log('PaymentConfirmationScreen - Balance Debug:', {
    hasSnapshot: balanceSnapshot != null,
    balanceError,
    realBalance,
    fallbackBalance,
    currentPaymentAmount: currentPayment.amount,
    currentPaymentCurrency: currentPayment.currency,
    hasEnoughBalance,
    balanceLoading,
    tokenType: invoiceData.tokenType,
  });

  // Wallet data for display
  const walletData = {
    symbol: currentPayment.currency,
    name: currentPayment.currency === 'cUSD' ? 'Confío Dollar' :
      currentPayment.currency === 'CONFIO' ? 'Confío' :
        currentPayment.currency === 'USDC' ? 'USD Coin' : currentPayment.currency,
    balance: formatBalanceDisplay(fallbackBalance),
    color: currentPayment.currency === 'cUSD' ? colors.primary :
      currentPayment.currency === 'CONFIO' ? colors.secondary :
        currentPayment.currency === 'USDC' ? colors.accent : colors.primary,
    icon: currentPayment.currency === 'cUSD' ? 'C' :
      currentPayment.currency === 'CONFIO' ? 'F' :
        currentPayment.currency === 'USDC' ? 'U' : '?'
  };

  const handleConfirmPayment = async () => {
    console.log('PaymentConfirmationScreen: handleConfirmPayment called for', { invoiceId: invoiceData.internalId });

    // Prevent double-clicks/rapid button presses
    if (isProcessing || navLock.current) {
      console.log('PaymentConfirmationScreen: Already processing, ignoring duplicate click');
      return;
    }

    if (!hasEnoughBalance) {
      Alert.alert('Saldo Insuficiente', 'No tienes suficiente saldo para realizar este pago.');
      return;
    }

    setIsProcessing(true);
    navLock.current = true;
    // Create deterministic idempotency key for this submission window (1 min granularity)
    const minuteTimestamp = Math.floor(Date.now() / 60000);
    const idempotencyKey = `pay_${invoiceData.internalId}_${minuteTimestamp}`;

    // Background preflight: moved to top-level effect

    // Ensure we have a prepared pack for THIS invoice before navigating (WS-only)
    let preparedForNav = prepared;
    if (!preparedForNav) {
      try {
        const amt = parseFloat(String(invoiceData.amount || '0'));
        const assetType = (String(invoiceData.tokenType || 'cUSD')).toUpperCase();
        const note = `Invoice ${invoiceData.internalId}`;
        console.log('PaymentConfirmationScreen: prepareViaWs on confirm', { invoiceId: invoiceData.internalId, amt, assetType });
        const pack = await prepareViaWs({
          amount: amt,
          assetType,
          internalId: invoiceData.internalId,
          note,
          recipientBusinessId: invoiceData.merchantAccount?.business?.id
        });
        if (pack && Array.isArray((pack as any).transactions) && (pack as any).transactions.length === 4) {
          preparedForNav = {
            transactions: (pack as any).transactions,
            paymentId: (pack as any).internalId || (pack as any).internal_id || (pack as any).paymentId || (pack as any).payment_id || invoiceData.internalId,
            groupId: (pack as any).groupId || (pack as any).group_id
          } as any;
          setPrepared(preparedForNav);
          console.log('PaymentConfirmationScreen: prepareViaWs on confirm OK');
        } else {
          console.log('PaymentConfirmationScreen: prepareViaWs on confirm failed');
        }
      } catch (e) {
        console.log('PaymentConfirmationScreen: prepareViaWs on confirm exception', e);
      }
    }

    console.log('PaymentConfirmationScreen: Navigating to PaymentProcessing with data:', {
      type: 'payment',
      amount: currentPayment.amount,
      currency: currentPayment.currency,
      merchant: currentPayment.recipient,
      action: 'Procesando pago',
      idempotencyKey,
      prepared: preparedForNav ? { paymentId: preparedForNav.paymentId, txCount: preparedForNav.transactions.length } : null,
      prepareError
    });

    // Navigate to payment processing screen (prefer navigate for simplicity while debugging logs)
    (navigation as any).navigate('PaymentProcessing', {
      transactionData: {
        type: 'payment',
        amount: currentPayment.amount,
        currency: currentPayment.currency,
        merchant: currentPayment.recipient,
        address: currentPayment.location,
        message: currentPayment.description,
        action: 'Procesando pago',
        internalId: invoiceData.internalId,
        idempotencyKey,
        merchantBusinessId: invoiceData.merchantAccount?.business?.id,
        preflight: true,
        prepared: preparedForNav
      }
    });
    console.log('PaymentConfirmationScreen: Triggered navigation to PaymentProcessing');

    // Safety reset in case navigation is blocked by an unseen error
    setTimeout(() => {
      if (navLock.current) {
        navLock.current = false;
        setIsProcessing(false);
      }
    }, 5000);

    // Reset processing state after navigation
    setTimeout(() => {
      setIsProcessing(false);
      navLock.current = false;
    }, 1000);
  };

  const handleCancel = () => {
    navigation.goBack();
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Header */}
        <View style={[styles.header, { backgroundColor: colors.primary }]}>
          <View style={styles.headerContent}>
            <TouchableOpacity onPress={handleCancel} style={styles.backButton}>
              <Icon name="arrow-left" size={24} color="white" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Confirmar Pago</Text>
            <View style={styles.placeholder} />
          </View>

          <View style={styles.headerCenter}>
            <View style={styles.merchantIcon}>
              <Icon name="shopping-bag" size={32} color={colors.primary} />
            </View>

            <Text style={styles.amountText}>
              ${formatAmount(currentPayment.amount)} {currentPayment.currency}
            </Text>

            <Text style={styles.recipientText}>
              Pagar a {currentPayment.recipient}
            </Text>

            <Text style={styles.recipientTypeText}>
              {currentPayment.recipientType}
            </Text>
          </View>
        </View>

        {/* Content */}
        <View style={styles.content}>
          {/* Recipient Details */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Detalles del destinatario</Text>

            <View style={styles.recipientRow}>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{currentPayment.avatar}</Text>
              </View>
              <View style={styles.recipientInfo}>
                <Text style={styles.recipientName}>{currentPayment.recipient}</Text>
                <View style={styles.recipientMeta}>
                  <Text style={styles.recipientCategory}>{currentPayment.recipientType}</Text>
                  <View style={styles.verificationBadge}>
                    <Icon name="check-circle" size={12} color="#10B981" />
                    <Text style={styles.verificationText}>{currentPayment.verification}</Text>
                  </View>
                </View>
              </View>
            </View>

            {/* Payment Details */}
            <View style={styles.detailsList}>
              {currentPayment.description && (
                <View style={styles.detailRow}>
                  <Icon name="file-text" size={16} color="#9CA3AF" />
                  <Text style={styles.detailText}>{currentPayment.description}</Text>
                </View>
              )}

              <View style={styles.detailRow}>
                <Icon name="map-pin" size={16} color="#9CA3AF" />
                <View>
                  <Text style={styles.detailText}>{currentPayment.location}</Text>
                  <Text style={styles.detailSubtext}>ID: {currentPayment.merchantId}</Text>
                </View>
              </View>

              <View style={styles.detailRow}>
                <Icon name="clock" size={16} color="#9CA3AF" />
                <View>
                  <Text style={styles.detailText}>ID: {currentPayment.paymentId}</Text>
                  <Text style={styles.detailSubtext}>Solicitud válida por 24 horas</Text>
                </View>
              </View>
            </View>
          </View>

          {/* Balance Check */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>
              Pagar desde tu cuenta {currentPayment.currency}
            </Text>

            <View style={[styles.balanceCard, { backgroundColor: colors.primaryLight }]}>
              <View style={styles.balanceRow}>
                <View style={styles.balanceIcon}>
                  <Text style={styles.balanceIconText}>{walletData.icon}</Text>
                </View>
                <View style={styles.balanceInfo}>
                  <Text style={styles.balanceName}>{walletData.name}</Text>
                  <Text style={styles.balanceLabel}>Saldo disponible</Text>
                </View>
                <View style={styles.balanceAmount}>
                  <Text style={styles.balanceValue}>
                    {balanceSnapshot == null || balanceLoading ? 'Cargando...' :
                      balanceError ? 'Error' : `$${walletData.balance}`}
                  </Text>
                  <Text style={[
                    styles.balanceStatus,
                    { color: hasEnoughBalance ? '#10B981' : '#EF4444' }
                  ]}>
                    {balanceSnapshot == null || balanceLoading ? 'Verificando...' :
                      balanceError ? 'Error al cargar saldo' :
                        hasEnoughBalance ? 'Saldo suficiente' : 'Saldo insuficiente'}
                  </Text>
                </View>
              </View>
            </View>
          </View>

          {/* Payment Summary */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Resumen del pago</Text>

            <View style={styles.summaryList}>
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Monto</Text>
                <Text style={styles.summaryAmount}>
                  ${formatAmount(currentPayment.amount)} {currentPayment.currency}
                </Text>
              </View>

              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Comisión para ti</Text>
                <View style={styles.commissionInfo}>
                  <Text style={styles.commissionText}>Gratis</Text>
                  <Text style={styles.commissionSubtext}>Cubierto por Confío</Text>
                </View>
              </View>

              <View style={styles.divider} />

              <View style={styles.summaryRow}>
                <Text style={styles.totalLabel}>Total a pagar</Text>
                <Text style={styles.totalAmount}>
                  ${formatAmount(currentPayment.amount)} {currentPayment.currency}
                </Text>
              </View>
            </View>
          </View>

          {/* Security Info */}
          <View style={[styles.securityCard, { backgroundColor: colors.primaryLight }]}>
            <Icon name="shield" size={20} color={colors.primaryDark} />
            <View style={styles.securityContent}>
              <Text style={[styles.securityTitle, { color: colors.primaryDark }]}>
                Pago seguro
              </Text>
              <Text style={[styles.securityText, { color: colors.primaryDark }]}>
                Tu pago está protegido por blockchain y será procesado instantáneamente
              </Text>
            </View>
          </View>

          {/* Warning if insufficient balance */}
          {!hasEnoughBalance && (
            <View style={styles.warningCard}>
              <Icon name="alert-triangle" size={20} color="#EF4444" />
              <View style={styles.warningContent}>
                <Text style={styles.warningTitle}>Saldo insuficiente</Text>
                <Text style={styles.warningText}>
                  Necesitas ${formatAmount(currentPayment.amount)} pero solo tienes ${formatAmount(walletData.balance)} en {walletData.name}
                </Text>
              </View>
            </View>
          )}

          {/* Action Buttons */}
          <View style={styles.actionButtons}>
            <TouchableOpacity
              style={[
                styles.confirmButton,
                { backgroundColor: hasEnoughBalance && !isProcessing ? colors.primary : '#D1D5DB' },
                (!hasEnoughBalance || isProcessing) && styles.disabledButton
              ]}
              onPress={handleConfirmPayment}
              disabled={!hasEnoughBalance || isProcessing}
            >
              <Text style={styles.confirmButtonText}>
                {isProcessing ? 'Procesando...' :
                  hasEnoughBalance ? 'Confirmar Pago' : (balanceSnapshot == null ? 'Cargando saldo…' : 'Saldo Insuficiente')}
              </Text>
            </TouchableOpacity>

            <TouchableOpacity style={styles.cancelButton} onPress={handleCancel}>
              <Text style={styles.cancelButtonText}>Cancelar</Text>
            </TouchableOpacity>
          </View>

          {/* Value Proposition */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>¿Por qué elegir Confío?</Text>

            <View style={[styles.valueCard, { backgroundColor: colors.primaryLight }]}>
              <View style={styles.valueRow}>
                <Icon name="check-circle" size={20} color={colors.primaryDark} />
                <Text style={[styles.valueTitle, { color: colors.primaryDark }]}>
                  Pagos 100% gratuitos para clientes
                </Text>
              </View>
              <Text style={[styles.valueText, { color: colors.primaryDark }]}>
                Pagas sin comisiones adicionales
              </Text>
              <View style={[styles.valueHighlight, { backgroundColor: colors.primary }]}>
                <Text style={styles.valueHighlightText}>
                  💡 Confío: 0% para clientes, solo 0.9% para comerciantes{'\n'}
                  vs. tarjetas tradicionales (2.5-3.5% para comerciantes){'\n'}
                  Apoyamos a los argentinos 🇦🇷 con un ecosistema justo
                </Text>
              </View>
            </View>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const { width } = Dimensions.get('window');

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  scrollView: {
    flex: 1,
  },
  header: {
    paddingTop: Platform.OS === 'ios' ? 48 : (StatusBar.currentHeight || 32),
    paddingBottom: 32,
    paddingHorizontal: 16,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 24,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: 'white',
  },
  placeholder: {
    width: 40,
  },
  headerCenter: {
    alignItems: 'center',
  },
  merchantIcon: {
    width: 64,
    height: 64,
    backgroundColor: 'white',
    borderRadius: 32,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  amountText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 8,
  },
  recipientText: {
    fontSize: 18,
    fontWeight: '600',
    color: 'white',
    marginBottom: 4,
  },
  recipientTypeText: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.8)',
  },
  content: {
    paddingHorizontal: 16,
    paddingTop: -16,
    paddingBottom: 24,
  },
  card: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 24,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  recipientRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  avatar: {
    width: 48,
    height: 48,
    backgroundColor: '#E5E7EB',
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  avatarText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#4B5563',
  },
  recipientInfo: {
    flex: 1,
  },
  recipientName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 4,
  },
  recipientMeta: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  recipientCategory: {
    fontSize: 14,
    color: '#6B7280',
    marginRight: 8,
  },
  verificationBadge: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  verificationText: {
    fontSize: 12,
    color: '#10B981',
    marginLeft: 4,
  },
  detailsList: {
    gap: 12,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  detailText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
    marginLeft: 12,
    flex: 1,
  },
  detailSubtext: {
    fontSize: 12,
    color: '#6B7280',
    marginLeft: 12,
  },
  balanceCard: {
    borderRadius: 12,
    padding: 16,
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  balanceIcon: {
    width: 40,
    height: 40,
    backgroundColor: colors.primary,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  balanceIconText: {
    color: 'white',
    fontWeight: 'bold',
    fontSize: 16,
  },
  balanceInfo: {
    flex: 1,
  },
  balanceName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  balanceLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  balanceAmount: {
    alignItems: 'flex-end',
  },
  balanceValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  balanceStatus: {
    fontSize: 12,
  },
  summaryList: {
    gap: 12,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  summaryLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  summaryAmount: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  commissionInfo: {
    alignItems: 'flex-end',
  },
  commissionText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#10B981',
  },
  commissionSubtext: {
    fontSize: 12,
    color: '#6B7280',
  },
  divider: {
    height: 1,
    backgroundColor: '#E5E7EB',
    marginVertical: 8,
  },
  totalLabel: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  totalAmount: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  securityCard: {
    flexDirection: 'row',
    padding: 16,
    borderRadius: 12,
    marginBottom: 16,
  },
  securityContent: {
    marginLeft: 12,
    flex: 1,
  },
  securityTitle: {
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 4,
  },
  securityText: {
    fontSize: 12,
  },
  warningCard: {
    flexDirection: 'row',
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#FECACA',
    padding: 16,
    borderRadius: 12,
    marginBottom: 16,
  },
  warningContent: {
    marginLeft: 12,
    flex: 1,
  },
  warningTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#DC2626',
    marginBottom: 4,
  },
  warningText: {
    fontSize: 12,
    color: '#B91C1C',
  },
  actionButtons: {
    gap: 12,
    marginBottom: 16,
  },
  confirmButton: {
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  confirmButtonText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: 'white',
  },
  disabledButton: {
    opacity: 0.5,
  },
  cancelButton: {
    paddingVertical: 12,
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    alignItems: 'center',
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#374151',
  },
  valueCard: {
    padding: 16,
    borderRadius: 12,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  valueTitle: {
    fontSize: 14,
    fontWeight: '600',
    marginLeft: 8,
  },
  valueText: {
    fontSize: 12,
    marginBottom: 12,
  },
  valueHighlight: {
    padding: 12,
    borderRadius: 8,
  },
  valueHighlightText: {
    fontSize: 12,
    color: 'white',
    lineHeight: 18,
  },

});
