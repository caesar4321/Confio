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
import { Button } from '../components/common/Button';
import { InlineBanner } from '../components/common/InlineBanner';
import { ReceiptCard } from '../components/common/ReceiptCard';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { formatNumber } from '../utils/numberFormatting';
import { useMutation } from '@apollo/client';
import { GET_INVOICE } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';
import { APP_LAYOUT } from '../config/layout';

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
  const { userProfile } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);
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
          return;
        }

        // WS-only mode: if WS pack missing/invalid, record error
        if (alive) {
          setPrepareError('Failed to prepare payment via WebSocket');
        }
      } catch (e: any) {
        if (alive) setPrepareError(e?.message || 'Failed to prepare payment');
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
          <Text style={{ marginTop: 10, color: colors.text.secondary }}>Cargando detalles del pago...</Text>
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
    verification: 'Verificado'
  };

  // Use snapshot balance; no immediate network dependency
  const realBalance = balanceSnapshot || '0';

  const hasEnoughBalance = balanceSnapshot != null && parseFloat(realBalance) >= parseFloat(currentPayment.amount);

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

  // Wallet data for display
  const walletData = {
    symbol: currentPayment.currency,
    name: currentPayment.currency === 'cUSD' ? 'Confío Dollar' :
      currentPayment.currency === 'CONFIO' ? 'Confío' :
        currentPayment.currency === 'USDC' ? 'USD Coin' : currentPayment.currency,
    balance: formatBalanceDisplay(realBalance),
    color: currentPayment.currency === 'cUSD' ? colors.primary :
      currentPayment.currency === 'CONFIO' ? colors.secondary :
        currentPayment.currency === 'USDC' ? colors.accent : colors.primary,
    icon: currentPayment.currency === 'cUSD' ? 'C' :
      currentPayment.currency === 'CONFIO' ? 'F' :
        currentPayment.currency === 'USDC' ? 'U' : '?'
  };

  const handleConfirmPayment = async () => {

    // Prevent double-clicks/rapid button presses
    if (isProcessing || navLock.current) {
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
        } else {
        }
      } catch (e) {
      }
    }


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
        {/* Header — brand field: emerald gradient + coin ring; padding on
            headerInner (Yoga insets absolute children by parent padding). */}
        <View style={styles.header}>
          <Svg style={StyleSheet.absoluteFill}>
            <Defs>
              <SvgLinearGradient id="payConfirmField" x1="0" y1="0" x2="0" y2="1">
                <Stop offset="0" stopColor={colors.primary} />
                <Stop offset="1" stopColor={colors.primaryDark} />
              </SvgLinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill="url(#payConfirmField)" />
            <Circle cx="105%" cy="25%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
          </Svg>
          <View style={styles.headerInner}>
          <View style={styles.headerContent}>
            <TouchableOpacity onPress={handleCancel} style={styles.backButton} accessibilityRole="button" accessibilityLabel="Volver">
              <Icon name="arrow-left" size={24} color={colors.white} />
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
                    <Icon name="check-circle" size={12} color={colors.primaryDark} />
                    <Text style={styles.verificationText}>{currentPayment.verification}</Text>
                  </View>
                </View>
              </View>
            </View>

            {/* Payment Details */}
            <View style={styles.detailsList}>
              {currentPayment.description && (
                <View style={styles.detailRow}>
                  <Icon name="file-text" size={16} color={colors.text.light} />
                  <Text style={styles.detailText}>{currentPayment.description}</Text>
                </View>
              )}

              <View style={styles.detailRow}>
                <Icon name="map-pin" size={16} color={colors.text.light} />
                <View>
                  <Text style={styles.detailText}>{currentPayment.location}</Text>
                  <Text style={styles.detailSubtext}>ID: {currentPayment.merchantId}</Text>
                </View>
              </View>

              <View style={styles.detailRow}>
                <Icon name="clock" size={16} color={colors.text.light} />
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
                    { color: hasEnoughBalance ? colors.primaryDark : colors.danger }
                  ]}>
                    {balanceSnapshot == null || balanceLoading ? 'Verificando...' :
                      balanceError ? 'Error al cargar saldo' :
                        hasEnoughBalance ? 'Saldo suficiente' : 'Saldo insuficiente'}
                  </Text>
                </View>
              </View>
            </View>
          </View>

          {/* Payment summary — shared receipt grammar */}
          <View style={styles.summarySection}>
            <Text style={styles.sectionLabel}>Resumen del pago</Text>
            <ReceiptCard
              items={[
                { label: 'Monto', value: `$${formatAmount(currentPayment.amount)} ${currentPayment.currency}` },
                { label: 'Comisión para ti', value: 'Gratis · cubre Confío', color: colors.primaryDark },
                { label: 'Total a pagar', value: `$${formatAmount(currentPayment.amount)} ${currentPayment.currency}`, color: colors.text.primary },
              ]}
              style={styles.receiptCard}
            />
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

          {/* Insufficient balance — only claim it once we actually know */}
          {balanceSnapshot != null && !balanceError && !hasEnoughBalance && (
            <InlineBanner
              variant="error"
              message={`Necesitas $${formatAmount(currentPayment.amount)} pero tienes $${walletData.balance} en ${walletData.name}.`}
              style={{ marginBottom: 16 }}
            />
          )}

          {/* Action Buttons */}
          <View style={styles.actionButtons}>
            <Button
              title={hasEnoughBalance ? 'Confirmar Pago' : (balanceSnapshot == null ? 'Cargando saldo…' : 'Saldo Insuficiente')}
              onPress={handleConfirmPayment}
              loading={isProcessing}
              disabled={!hasEnoughBalance}
              accessibilityLabel="Confirmar pago"
              style={{ backgroundColor: hasEnoughBalance && !isProcessing ? colors.primary : colors.borderMedium }}
            />

            <Button
              title="Cancelar"
              variant="secondary"
              onPress={handleCancel}
              style={{ backgroundColor: colors.neutralDark, borderWidth: 0 }}
            />
          </View>

          {/* Supportive footnote — the mission line, no fee marketing */}
          <Text style={styles.supportFootnote}>{supportCopy.ecosystemLine}</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const { width } = Dimensions.get('window');

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  scrollView: {
    flex: 1,
  },
  header: {
    backgroundColor: colors.primary,
    overflow: 'hidden',
  },
  headerInner: {
    paddingTop: Platform.OS === 'ios' ? APP_LAYOUT.topSafeArea : APP_LAYOUT.topSafeArea + 8,
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
    color: colors.white,
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
    backgroundColor: colors.white,
    borderRadius: 32,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  amountText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: colors.white,
    marginBottom: 8,
  },
  recipientText: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.white,
    marginBottom: 4,
  },
  recipientTypeText: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.8)',
  },
  content: {
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 24,
  },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 20,
    marginBottom: 16,
  },
  summarySection: {
    marginBottom: 16,
  },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 10,
  },
  receiptCard: {
    backgroundColor: colors.white,
  },
  supportFootnote: {
    fontSize: 12,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 18,
    paddingHorizontal: 24,
    marginBottom: 8,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
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
    backgroundColor: colors.violetLight,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  avatarText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.secondary,
  },
  recipientInfo: {
    flex: 1,
  },
  recipientName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 4,
  },
  recipientMeta: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  recipientCategory: {
    fontSize: 14,
    color: colors.text.secondary,
    marginRight: 8,
  },
  verificationBadge: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  verificationText: {
    fontSize: 12,
    color: colors.primaryDark,
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
    color: colors.text.primary,
    marginLeft: 12,
    flex: 1,
  },
  detailSubtext: {
    fontSize: 12,
    color: colors.text.secondary,
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
    color: colors.white,
    fontWeight: 'bold',
    fontSize: 16,
  },
  balanceInfo: {
    flex: 1,
  },
  balanceName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  balanceLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  balanceAmount: {
    alignItems: 'flex-end',
  },
  balanceValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  balanceStatus: {
    fontSize: 12,
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
  actionButtons: {
    gap: 12,
    marginBottom: 16,
  },

});
