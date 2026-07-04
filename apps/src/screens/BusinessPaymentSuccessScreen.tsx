import React, { useState, useEffect } from 'react';
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
  Modal,
  Linking,
  Vibration,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { colors } from '../config/theme';
import { SuccessHero } from '../components/common/SuccessHero';
import { useMutation } from '@apollo/client';
import { GET_INVOICE } from '../apollo/queries';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';

const { width } = Dimensions.get('window');

type BusinessPaymentSuccessRouteProp = RouteProp<{
  BusinessPaymentSuccess: {
    paymentData: {
      id: string;
      internalId: string;
      invoiceId?: string;
      amount: string;
      tokenType: string;
      description?: string;
      payerUser: {
        id: string;
        username: string;
        firstName?: string;
        lastName?: string;
      };
      payerAccount?: {
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
      payerAddress: string;
      payerBusiness?: {
        id: string;
        name: string;
        category: string;
      };
      payerDisplayName?: string;
      merchantUser: {
        id: string;
        username: string;
        firstName?: string;
        lastName?: string;
      };
      merchantAccount?: {
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
      merchantAddress: string;
      status: string;
      transactionHash: string;
      createdAt: string;
    };
  };
}, 'BusinessPaymentSuccess'>;

export const BusinessPaymentSuccessScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<BusinessPaymentSuccessRouteProp>();
  const { userProfile } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);
  const [copied, setCopied] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const [displayCustomerName, setDisplayCustomerName] = useState<string>('Cliente');

  const { paymentData } = route.params;

  // Calculate merchant fee (0.9%)
  const amount = parseFloat(paymentData.amount);
  const merchantFee = amount * 0.009;
  const netAmount = amount - merchantFee;

  // Format currency for display
  const formatCurrency = (currency: string): string => {
    if (currency === 'CUSD') return 'cUSD';
    if (currency === 'CONFIO') return 'CONFIO';
    if (currency === 'USDC') return 'USDC';
    return currency;
  };

  // Get customer name - prefer business name if payment was made from business account
  const initialCustomerName = paymentData.payerDisplayName ||
    paymentData.payerBusiness?.name ||
    paymentData.payerAccount?.business?.name ||
    paymentData.payerUser?.firstName ||
    paymentData.payerUser?.lastName ||
    paymentData.payerUser?.username || 'Cliente';

  // Haptic feedback on successful payment
  useEffect(() => {
    Vibration.vibrate(Platform.OS === 'ios' ? 50 : [0, 50, 30, 50]);
  }, []);

  // Prefer the name in params; if it's a placeholder, try fetching from invoice to enrich
  React.useEffect(() => {
    setDisplayCustomerName(initialCustomerName);
  }, [initialCustomerName]);

  const invoiceId = paymentData.invoiceId;
  const shouldFetchInvoice = !initialCustomerName || initialCustomerName === 'Cliente';
  const [fetchInvoice] = useMutation(GET_INVOICE);

  React.useEffect(() => {
    (async () => {
      if (!invoiceId || !shouldFetchInvoice) return;
      try {
        const { data } = await fetchInvoice({ variables: { invoiceId } });
        if (data?.getInvoice?.success && data.getInvoice.invoice?.paymentTransactions) {
          const list = data.getInvoice.invoice.paymentTransactions;
          const ptx = list.find((pt: any) => pt?.internalId === paymentData.internalId) || list[0];
          if (ptx?.payerUser) {
            const name = ptx.payerUser.firstName || ptx.payerUser.lastName || ptx.payerUser.username;
            if (name) setDisplayCustomerName(name);
          }
        }
      } catch (e) {
        // ignore enrichment errors
      }
    })();
  }, [invoiceId, shouldFetchInvoice, fetchInvoice, paymentData?.internalId]);

  // Get customer avatar
  const customerAvatar = (displayCustomerName || 'C').charAt(0).toUpperCase();

  // Format date and time
  const paymentDate = new Date(paymentData.createdAt);
  const formattedDate = paymentDate.toLocaleDateString('es-ES');
  const formattedTime = paymentDate.toLocaleTimeString('es-ES', {
    hour: '2-digit',
    minute: '2-digit'
  });

  const handleCopy = () => {
    Clipboard.setString(paymentData.internalId);
    Alert.alert('Copiado', 'ID de transacción copiado al portapapeles');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleNewCharge = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Charge' });
  };

  const handleGoHome = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Home' });
  };

  const handleGenerateInvoice = () => {
    Alert.alert('Generar Factura', 'Función de generación de factura en desarrollo');
  };

  const handleShareReceipt = () => {
    (navigation as any).navigate('TransactionReceipt', {
      transaction: {
        ...paymentData,
        // Map to fields expected by TransactionReceiptScreen
        internalId: paymentData.internalId,
        id: paymentData.id || paymentData.internalId,
        amount: paymentData.amount,
        currency: formatCurrency(paymentData.tokenType),
        status: paymentData.status,
        date: paymentData.createdAt,

        // Payer info
        payerName: paymentData.payerDisplayName || paymentData.payerBusiness?.name || 'Cliente',
        senderDisplayName: paymentData.payerDisplayName,
        payerBusiness: paymentData.payerBusiness,
        senderUser: paymentData.payerUser,
        payerPhone: '', // Not always available in paymentData unless added to schema override

        // Merchant info
        merchantName: paymentData.merchantAccount?.business?.name || 'Comercio',
        recipientBusiness: paymentData.merchantAccount?.business,
        recipientUser: paymentData.merchantUser,

        transactionHash: paymentData.transactionHash,
        verificationId: paymentData.internalId
      },
      type: 'payment'
    });
  };

  const handleViewCustomerProfile = () => {
    Alert.alert('Ver Perfil del Cliente', 'Función de perfil en desarrollo');
  };

  const currentCurrency = formatCurrency(paymentData.tokenType);
  const isCUSD = currentCurrency === 'cUSD';
  const isConfirming = (paymentData.status || '').toUpperCase() === 'SUBMITTED' || (paymentData.status || '').toUpperCase() === 'PENDING_BLOCKCHAIN';
  const headerBgColor = isCUSD ? colors.primary : colors.secondary;
  const confirmColor = '#d97706'; // amber-600
  const confirmBg = '#fef3c7'; // amber-100

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <SuccessHero
          title="¡Pago recibido!"
          amount={`+$${netAmount.toFixed(2)} ${currentCurrency}`}
          hint={`De ${displayCustomerName} · ya disponible en tu cuenta`}
          tint={isCUSD ? undefined : colors.secondary}
          amountColor={isCUSD ? undefined : colors.secondary}
        />

        {/* Revenue breakdown — real merchant information, kept prominent */}
        <View style={styles.card}>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Recibido del cliente</Text>
            <Text style={styles.rowValue}>${paymentData.amount}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Comisión Confío (0.9%)</Text>
            <Text style={styles.rowValue}>-${merchantFee.toFixed(2)}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Comisión de red</Text>
            <Text style={[styles.rowValue, { color: colors.primaryDark, fontWeight: '600' }]}>
              Gratis · cubierta por Confío
            </Text>
          </View>
          <View style={[styles.row, styles.rowLast]}>
            <Text style={styles.netLabel}>Ingreso neto</Text>
            <Text style={[styles.netAmount, !isCUSD && { color: colors.secondary }]}>
              +${netAmount.toFixed(2)}
            </Text>
          </View>
        </View>

        {/* Compact receipt card */}
        <View style={[styles.card, { marginTop: 12 }]}>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Cliente</Text>
            <View style={styles.rowInline}>
              <Text style={styles.rowValue} numberOfLines={1}>{displayCustomerName}</Text>
              <Icon name="check-circle" size={15} color={colors.success} />
            </View>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Fecha</Text>
            <Text style={styles.rowValue}>{formattedDate} · {formattedTime}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>ID</Text>
            <View style={styles.rowInline}>
              <Text style={styles.rowMono}>#{paymentData.internalId?.slice(-8)?.toUpperCase() || 'N/A'}</Text>
              <TouchableOpacity onPress={handleCopy} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} accessibilityRole="button" accessibilityLabel="Copiar ID">
                <Icon name={copied ? 'check-circle' : 'copy'} size={15} color={colors.primaryDark} />
              </TouchableOpacity>
            </View>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Método</Text>
            <Text style={styles.rowValue}>{currentCurrency === 'cUSD' ? 'Confío Dollar' : 'Confío'}</Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Liquidación</Text>
            <Text style={styles.rowValue}>Inmediata</Text>
          </View>
          <View style={[styles.row, styles.rowLast]}>
            <Text style={styles.rowLabel}>Estado</Text>
            <View style={styles.rowInline}>
              <Icon
                name={isConfirming ? 'clock' : 'check-circle'}
                size={15}
                color={isConfirming ? colors.warning.icon : colors.success}
              />
              <Text style={[styles.rowValue, { color: isConfirming ? colors.warning.icon : colors.success, fontWeight: '600' }]}>
                {isConfirming ? 'Confirmando…' : 'Confirmado'}
              </Text>
            </View>
          </View>
          {paymentData.description ? (
            <View style={styles.messageBox}>
              <Text style={styles.messageLabel}>Descripción</Text>
              <Text style={styles.messageText}>{paymentData.description}</Text>
            </View>
          ) : null}
        </View>

        {/* Quiet secondary actions */}
        <View style={styles.secondaryRow}>
          <TouchableOpacity style={styles.secondaryBtn} onPress={handleShareReceipt} accessibilityRole="button" accessibilityLabel="Compartir comprobante">
            <Icon name="share-2" size={16} color={colors.gray700} />
            <Text style={styles.secondaryText}>Comprobante</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryBtn} onPress={() => setShowTechnical(true)} accessibilityRole="button" accessibilityLabel="Ver detalles técnicos">
            <Icon name="external-link" size={16} color={colors.gray700} />
            <Text style={styles.secondaryText}>Detalles</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryBtn} onPress={handleGoHome} accessibilityRole="button" accessibilityLabel="Ir al inicio">
            <Icon name="home" size={16} color={colors.gray700} />
            <Text style={styles.secondaryText}>Inicio</Text>
          </TouchableOpacity>
        </View>

        {/* Merchant's continue action: back to selling */}
        <View style={styles.ctaWrap}>
          <TouchableOpacity
            style={[styles.cta, !isCUSD && { backgroundColor: colors.secondary }]}
            onPress={handleNewCharge}
            activeOpacity={0.85}
            accessibilityRole="button"
          >
            <Icon name="plus" size={18} color={colors.white} />
            <Text style={styles.ctaText}>Nuevo cobro</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>

      {/* Technical Details Modal */}
      <Modal
        visible={showTechnical}
        transparent
        animationType="fade"
        onRequestClose={() => setShowTechnical(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Detalles técnicos</Text>
              <TouchableOpacity onPress={() => setShowTechnical(false)} style={{ padding: 8 }} accessibilityRole="button" accessibilityLabel="Cerrar">
                <Icon name="x" size={20} color="#111827" />
              </TouchableOpacity>
            </View>
            <View style={styles.modalBody}>
              <View style={styles.modalSection}>
                <Text style={styles.modalSectionTitle}>Transacción</Text>
                <View style={styles.modalRow}>
                  <Text style={styles.modalLabel}>Red</Text>
                  <Text style={styles.modalValue}>{__DEV__ ? 'Testnet' : 'Mainnet'}</Text>
                </View>
                <View style={styles.modalRow}>
                  <Text style={styles.modalLabel}>Hash</Text>
                  <Text style={styles.modalValue} numberOfLines={1}>
                    {(() => {
                      const h = (paymentData.transactionHash || '').toString();
                      if (!h) return 'N/D';
                      return h.replace(/(.{10}).+(.{6})/, '$1…$2');
                    })()}
                  </Text>
                </View>
                {paymentData.merchantAddress && (
                  <View style={styles.modalRow}>
                    <Text style={styles.modalLabel}>Comercio</Text>
                    <Text style={styles.modalValue} numberOfLines={1}>
                      {paymentData.merchantAddress.replace(/(.{10}).+(.{6})/, '$1…$2')}
                    </Text>
                  </View>
                )}
              </View>
              <TouchableOpacity
                style={[styles.explorerButton, { backgroundColor: '#8B5CF6' }]}
                onPress={async () => {
                  const txid = paymentData.transactionHash;
                  if (!txid) {
                    Alert.alert('Sin hash', 'Aún no hay hash de transacción disponible.');
                    return;
                  }
                  const base = __DEV__ ? 'https://testnet.explorer.perawallet.app' : 'https://explorer.perawallet.app';
                  const url = `${base}/tx/${encodeURIComponent(txid)}`;
                  try {
                    await Linking.openURL(url);
                  } catch {
                    Alert.alert('Error', 'No se pudo abrir Pera Explorer.');
                  }
                }}
              >
                <Icon name="external-link" size={16} color="#fff" style={{ marginRight: 8 }} />
                <Text style={styles.explorerButtonText}>Abrir en Pera Explorer</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollContent: {
    flexGrow: 1,
    paddingBottom: 24,
  },
  card: {
    marginHorizontal: 24,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 16,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 13,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    gap: 12,
  },
  rowLast: {
    borderBottomWidth: 0,
  },
  rowLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  rowValue: {
    fontSize: 14,
    color: colors.text.primary,
    fontWeight: '500',
    flexShrink: 1,
    textAlign: 'right',
  },
  rowInline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexShrink: 1,
  },
  rowMono: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
  },
  netLabel: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.text.primary,
  },
  netAmount: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.primaryDark,
  },
  messageBox: {
    backgroundColor: colors.neutral,
    borderRadius: 10,
    padding: 12,
    marginBottom: 14,
  },
  messageLabel: {
    fontSize: 12,
    color: colors.text.secondary,
    marginBottom: 2,
  },
  messageText: {
    fontSize: 14,
    color: colors.text.primary,
  },
  secondaryRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    columnGap: 24,
    marginTop: 20,
    paddingHorizontal: 16,
  },
  secondaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 4,
  },
  secondaryText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.gray700,
  },
  ctaWrap: {
    flex: 1,
    justifyContent: 'flex-end',
    alignItems: 'center',
    paddingTop: 28,
    paddingHorizontal: 24,
  },
  cta: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 14,
    paddingVertical: 15,
    paddingHorizontal: 40,
    minWidth: 200,
  },
  ctaText: {
    color: colors.white,
    fontSize: 16,
    fontWeight: '700',
  },
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: colors.background,
    borderRadius: 16,
    width: '100%',
    maxWidth: 420,
    maxHeight: '80%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.dark,
  },
  modalBody: {
    padding: 16,
  },
  modalSection: {
    marginBottom: 16,
  },
  modalSectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.gray700,
    marginBottom: 8,
  },
  modalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 6,
  },
  modalLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  modalValue: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.dark,
    flexShrink: 1,
    textAlign: 'right',
    marginLeft: 12,
  },
  explorerButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.accent,
    paddingVertical: 14,
    borderRadius: 12,
    marginTop: 8,
  },
  explorerButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.white,
  },
});
