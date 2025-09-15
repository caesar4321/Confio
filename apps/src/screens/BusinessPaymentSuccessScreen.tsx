import React, { useState } from 'react';
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
  Clipboard,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { colors } from '../config/theme';
import { useMutation } from '@apollo/client';
import { GET_INVOICE } from '../apollo/queries';

const { width } = Dimensions.get('window');

type BusinessPaymentSuccessRouteProp = RouteProp<{
  BusinessPaymentSuccess: {
    paymentData: {
      id: string;
      paymentTransactionId: string;
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
  const [copied, setCopied] = useState(false);
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
  const initialCustomerName = paymentData.payerAccount?.business?.name || 
                              paymentData.payerUser?.firstName || 
                              paymentData.payerUser?.lastName || 
                              paymentData.payerUser?.username || 'Cliente';

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
          const ptx = list.find((pt: any) => pt?.paymentTransactionId === paymentData.paymentTransactionId) || list[0];
          if (ptx?.payerUser) {
            const name = ptx.payerUser.firstName || ptx.payerUser.lastName || ptx.payerUser.username;
            if (name) setDisplayCustomerName(name);
          }
        }
      } catch (e) {
        // ignore enrichment errors
      }
    })();
  }, [invoiceId, shouldFetchInvoice, fetchInvoice, paymentData?.paymentTransactionId]);

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
    Clipboard.setString(paymentData.paymentTransactionId);
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
    Alert.alert('Compartir Comprobante', 'Función de compartir en desarrollo');
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
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Success Header */}
        <View style={[styles.header, { backgroundColor: headerBgColor }]}>
          <View style={styles.headerContent}>
            {/* Success Animation */}
            <View style={styles.successIconContainer}>
              <Icon name="check-circle" size={48} color={isCUSD ? colors.primary : colors.secondary} />
            </View>

            <Text style={styles.successTitle}>¡Pago Recibido!</Text>
            
            <Text style={styles.amountText}>
              +${netAmount.toFixed(2)} {currentCurrency}
            </Text>
            
            <Text style={styles.customerText}>De {displayCustomerName}</Text>
          </View>
        </View>

        {/* Content */}
        <View style={styles.content}>
          {/* Customer Info */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Cliente</Text>
            
            <View style={styles.customerRow}>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{customerAvatar}</Text>
              </View>
              <View style={styles.customerInfo}>
                <Text style={styles.customerName}>{displayCustomerName}</Text>
                {/* For privacy, do not show raw blockchain address */}
              </View>
              <View style={styles.verificationBadge}>
                <Icon name="check-circle" size={20} color="#10B981" />
              </View>
            </View>

            <View style={styles.detailsGrid}>
              <View style={styles.detailItem}>
                <Icon name="clock" size={16} color="#9CA3AF" />
                <View style={styles.detailContent}>
                  <Text style={styles.detailText}>{formattedDate} • {formattedTime}</Text>
                  <Text style={styles.detailSubtext}>Hace unos segundos</Text>
                </View>
              </View>
              
              <View style={styles.detailItem}>
                <Icon name="file-text" size={16} color="#9CA3AF" />
                <View style={styles.detailContent}>
                  <Text style={styles.detailText}>ID: {paymentData.paymentTransactionId}</Text>
                  <Text style={styles.detailSubtext}>{paymentData.description || 'Sin descripción'}</Text>
                </View>
              </View>
            </View>
          </View>

          {/* Revenue Summary */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Resumen de Ingresos</Text>
            
            <View style={styles.revenueContainer}>
              {/* Revenue breakdown */}
              <View style={styles.revenueBreakdown}>
                <View style={styles.revenueRow}>
                  <Text style={styles.revenueLabel}>Monto recibido del cliente</Text>
                  <Text style={styles.revenueAmount}>${paymentData.amount}</Text>
                </View>
                
                <View style={styles.revenueRow}>
                  <Text style={styles.feeLabel}>Comisión Confío (0.9%)</Text>
                  <Text style={styles.feeAmount}>-${merchantFee.toFixed(2)}</Text>
                </View>
                
                <View style={styles.revenueRow}>
                  <Text style={styles.feeLabel}>Comisión de red</Text>
                  <View style={styles.freeFeeContainer}>
                    <Text style={styles.freeFeeText}>Gratis</Text>
                    <Text style={styles.freeFeeSubtext}>Cubierto por Confío</Text>
                  </View>
                </View>
                
                <View style={styles.divider} />
                
                <View style={styles.revenueRow}>
                  <Text style={styles.netLabel}>Ingreso neto</Text>
                  <Text style={styles.netAmount}>+${netAmount.toFixed(2)}</Text>
                </View>
              </View>

              {/* Transaction details */}
              <View style={styles.transactionDetails}>
                <View style={styles.transactionRow}>
                  <Text style={styles.transactionLabel}>Método de pago</Text>
                  <Text style={styles.transactionValue}>
                    {currentCurrency === 'cUSD' ? 'Confío Dollar' : 'Confío'}
                  </Text>
                </View>

                <View style={styles.transactionRow}>
                  <Text style={styles.transactionLabel}>Estado</Text>
                  <View style={styles.statusContainer}>
                {isConfirming ? (
                  <>
                    <Icon name="clock" size={16} color={confirmColor} />
                    <Text style={[styles.statusText, { color: confirmColor }]}>Confirmando…</Text>
                  </>
                ) : (
                  <>
                    <Icon name="check-circle" size={16} color="#10B981" />
                    <Text style={styles.statusText}>Procesado exitosamente</Text>
                  </>
                )}
                  </View>
                </View>

                <View style={styles.transactionRow}>
                  <Text style={styles.transactionLabel}>Liquidación</Text>
                  <Text style={styles.transactionValue}>Inmediata</Text>
                </View>

                <View style={styles.transactionRow}>
                  <Text style={styles.transactionLabel}>ID de Transacción</Text>
                  <View style={styles.transactionIdContainer}>
                    <Text style={styles.transactionId}>
                      #{paymentData.paymentTransactionId.slice(-8).toUpperCase()}
                    </Text>
                    <TouchableOpacity onPress={handleCopy} style={styles.copyButton}>
                      {copied ? (
                        <Icon name="check" size={16} color={colors.accent} />
                      ) : (
                        <Icon name="copy" size={16} color={colors.accent} />
                      )}
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
            </View>
          </View>

          {/* Quick Actions */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Acciones Rápidas</Text>
            
            <View style={styles.actionsContainer}>
              <TouchableOpacity 
                style={[styles.actionButton, { backgroundColor: isCUSD ? colors.primary : colors.secondary }]}
                onPress={handleGenerateInvoice}
              >
                <Icon name="file-text" size={16} color="white" />
                <Text style={styles.actionButtonText}>Generar factura</Text>
              </TouchableOpacity>
              
              <TouchableOpacity style={styles.secondaryActionButton} onPress={handleShareReceipt}>
                <Icon name="share-2" size={16} color="#6B7280" />
                <Text style={styles.secondaryActionText}>Compartir comprobante</Text>
              </TouchableOpacity>
              
              <TouchableOpacity style={styles.secondaryActionButton} onPress={handleViewCustomerProfile}>
                <Icon name="user" size={16} color="#6B7280" />
                <Text style={styles.secondaryActionText}>Ver perfil del cliente</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Continue Working */}
          <View style={styles.continueContainer}>
            <TouchableOpacity 
              style={[styles.continueButton, { backgroundColor: isCUSD ? colors.primary : colors.secondary }]}
              onPress={handleNewCharge}
            >
              <Icon name="plus" size={16} color="white" />
              <Text style={styles.continueButtonText}>Nuevo Cobro</Text>
            </TouchableOpacity>
            
            <TouchableOpacity style={styles.homeButton} onPress={handleGoHome}>
              <Icon name="home" size={16} color="#6B7280" />
              <Text style={styles.homeButtonText}>Ir al Inicio</Text>
            </TouchableOpacity>
          </View>

          {/* Why Choose Confío */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>¿Por qué elegir Confío?</Text>
            
            <View style={[styles.whyConfioContainer, { backgroundColor: isCUSD ? '#ECFDF5' : '#F5F3FF' }]}>
              <View style={styles.whyConfioHeader}>
                <Icon name="check-circle" size={20} color={isCUSD ? colors.primary : colors.secondary} />
                <Text style={[styles.whyConfioTitle, { color: isCUSD ? colors.primary : colors.secondary }]}>
                  Comisiones ultra competitivas
                </Text>
              </View>
              <Text style={[styles.whyConfioText, { color: isCUSD ? '#065F46' : '#5B21B6' }]}>
                Acabas de ahorrar en comisiones vs. métodos tradicionales
              </Text>
              <View style={[styles.comparisonContainer, { backgroundColor: isCUSD ? '#D1FAE5' : '#EDE9FE' }]}>
                <Text style={[styles.comparisonText, { color: isCUSD ? '#065F46' : '#5B21B6' }]}>
                  💡 <Text style={styles.bold}>Confío: 0.9% para comerciantes</Text>
                  {'\n'}vs. tarjetas tradicionales <Text style={styles.bold}>(2.5-3.5%)</Text>
                  {'\n'}Apoyamos a los comerciantes venezolanos 🇻🇪
                </Text>
              </View>
            </View>
          </View>

          {/* Success Message */}
          <View style={[styles.successMessage, { backgroundColor: isCUSD ? '#ECFDF5' : '#F5F3FF' }]}>
            <Icon name="check-circle" size={32} color={isCUSD ? colors.primary : colors.secondary} />
            <Text style={[styles.successMessageTitle, { color: isCUSD ? colors.primary : colors.secondary }]}>¡Pago procesado exitosamente!</Text>
            <Text style={[styles.successMessageText, { color: isCUSD ? '#065F46' : '#5B21B6' }]}>El dinero ya está disponible en tu cuenta. Puedes continuar vendiendo.</Text>
          </View>
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
    paddingTop: Platform.OS === 'ios' ? 60 : 40,
    paddingBottom: 48,
    paddingHorizontal: 16,
  },
  headerContent: {
    alignItems: 'center',
  },
  successIconContainer: {
    width: 96,
    height: 96,
    backgroundColor: 'white',
    borderRadius: 48,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
  },
  successTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 8,
  },
  amountText: {
    fontSize: 36,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 16,
  },
  customerText: {
    fontSize: 18,
    color: 'white',
    opacity: 0.9,
  },
  content: {
    paddingHorizontal: 16,
    paddingTop: -32,
    paddingBottom: 24,
  },
  card: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 24,
    marginBottom: 24,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  customerRow: {
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
    color: '#6B7280',
  },
  customerInfo: {
    flex: 1,
  },
  customerName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 4,
  },
  addressRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  addressText: {
    fontSize: 14,
    color: '#6B7280',
    marginRight: 8,
    flex: 1,
  },
  copyButton: {
    padding: 4,
  },
  verificationBadge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#F0FDF4',
    justifyContent: 'center',
    alignItems: 'center',
  },
  detailsGrid: {
    gap: 16,
  },
  detailItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  detailContent: {
    marginLeft: 12,
    flex: 1,
  },
  detailText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  detailSubtext: {
    fontSize: 12,
    color: '#6B7280',
  },
  revenueContainer: {
    gap: 24,
  },
  revenueBreakdown: {
    backgroundColor: '#F0FDF4',
    padding: 16,
    borderRadius: 12,
  },
  revenueRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  revenueLabel: {
    fontSize: 14,
    color: '#065F46',
  },
  revenueAmount: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#065F46',
  },
  feeLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  feeAmount: {
    fontSize: 14,
    color: '#DC2626',
  },
  freeFeeContainer: {
    alignItems: 'flex-end',
  },
  freeFeeText: {
    fontSize: 14,
    color: '#059669',
    fontWeight: '500',
  },
  freeFeeSubtext: {
    fontSize: 12,
    color: '#6B7280',
  },
  divider: {
    height: 1,
    backgroundColor: '#D1FAE5',
    marginVertical: 12,
  },
  netLabel: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#065F46',
  },
  netAmount: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#065F46',
  },
  transactionDetails: {
    gap: 12,
  },
  transactionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  transactionLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  transactionValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  statusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#059669',
    marginLeft: 4,
  },
  transactionIdContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  transactionId: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
    marginRight: 8,
  },
  actionsContainer: {
    gap: 12,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
    gap: 8,
  },
  actionButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: 'white',
  },
  secondaryActionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    gap: 8,
  },
  secondaryActionText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#6B7280',
  },
  continueContainer: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 24,
  },
  continueButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
    gap: 8,
  },
  continueButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: 'white',
  },
  homeButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    backgroundColor: '#F3F4F6',
    borderRadius: 12,
    gap: 8,
  },
  homeButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#6B7280',
  },
  whyConfioContainer: {
    padding: 16,
    borderRadius: 12,
  },
  whyConfioHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  whyConfioTitle: {
    fontSize: 16,
    fontWeight: '500',
    marginLeft: 8,
  },
  whyConfioText: {
    fontSize: 14,
    marginBottom: 12,
  },
  comparisonContainer: {
    padding: 12,
    borderRadius: 8,
  },
  comparisonText: {
    fontSize: 12,
    lineHeight: 18,
  },
  bold: {
    fontWeight: 'bold',
  },
  successMessage: {
    alignItems: 'center',
    padding: 16,
    borderRadius: 12,
  },
  successMessageTitle: {
    fontSize: 16,
    fontWeight: '500',
    marginTop: 8,
    marginBottom: 4,
  },
  successMessageText: {
    fontSize: 14,
    textAlign: 'center',
  },
}); 
