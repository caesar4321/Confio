import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
  Dimensions,
  Alert,
  Platform,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { colors } from '../config/theme';

type PaymentSuccessRouteProp = RouteProp<{
  PaymentSuccess: {
    transactionData: {
      type: 'payment';
      amount: string;
      currency: string;
      recipient: string;
      merchant: string;
      recipientAddress?: string;
      merchantAddress?: string;
      message?: string;
      transactionHash?: string;
      location?: string;
      terminal?: string;
      address?: string;
    };
  };
}, 'PaymentSuccess'>;

const { width } = Dimensions.get('window');

export const PaymentSuccessScreen = () => {
  console.log('PaymentSuccessScreen: Component mounted');
  const navigation = useNavigation();
  const route = useRoute<PaymentSuccessRouteProp>();
  const { transactionData } = route.params;
  const [copied, setCopied] = useState(false);

  // Helper function to format currency for display
  const formatCurrency = (currency: string): string => {
    if (currency === 'CUSD') return 'cUSD';
    if (currency === 'CONFIO') return 'CONFIO';
    if (currency === 'USDC') return 'USDC';
    return currency; // fallback
  };

  const handleDone = () => {
    // Navigate back to home screen
    (navigation as any).navigate('BottomTabs');
  };

  const handleViewTransaction = () => {
    // Navigate to transaction detail screen
    (navigation as any).navigate('TransactionDetail', {
      transactionId: transactionData.transactionHash || 'pending'
    });
  };

  const handleCopy = () => {
    // In a real app, you'd copy the transaction ID
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRequestReceipt = () => {
    Alert.alert('Solicitar Factura', 'Función de solicitud de factura en desarrollo');
  };

  const handleShareReceipt = () => {
    Alert.alert('Compartir Comprobante', 'Función de compartir en desarrollo');
  };

  const handleViewTechnicalDetails = () => {
    Alert.alert('Detalles Técnicos', 'Función de detalles técnicos en desarrollo');
  };

  const handleGoHome = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Home' });
  };

  const handleViewContacts = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Contacts' });
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Success Header */}
        <View style={[styles.header, { backgroundColor: colors.primary }]}>
          <View style={styles.headerContent}>
            {/* Success Animation */}
            <View style={styles.successCircle}>
              <Icon name="check-circle" size={48} color={colors.primary} />
            </View>
            
            <Text style={styles.headerTitle}>¡Pago realizado!</Text>
            
            <Text style={styles.headerAmount}>
              -${transactionData.amount} {formatCurrency(transactionData.currency)}
            </Text>
            
            <Text style={styles.headerSubtitle}>
              Pagado en {transactionData.merchant}
            </Text>
          </View>
        </View>

        {/* Content */}
        <View style={styles.content}>
          {/* Payment Summary */}
          <View style={styles.summaryContainer}>
            <Text style={styles.sectionTitle}>Resumen de Pago</Text>
            
            <View style={styles.summaryContent}>
              {/* Merchant Info */}
              <View style={styles.participantRow}>
                <View style={styles.participantAvatar}>
                  <Text style={styles.participantInitial}>
                    {transactionData.merchant?.charAt(0)}
                  </Text>
                </View>
                <View style={styles.participantInfo}>
                  <Text style={styles.participantName}>
                    {transactionData.merchant}
                  </Text>
                  <Text style={styles.participantDetails}>
                    {transactionData.location && transactionData.terminal 
                      ? `${transactionData.location} • ${transactionData.terminal}`
                      : transactionData.address || 'Dirección no disponible'
                    }
                  </Text>
                </View>
                <View style={styles.participantIcon}>
                  <Icon name="arrow-up" size={16} color="#EF4444" />
                </View>
              </View>

              {/* Amount Breakdown */}
              <View style={styles.amountBreakdown}>
                <View style={styles.amountRow}>
                  <Text style={styles.amountLabel}>Monto pagado</Text>
                  <Text style={styles.amountValue}>
                    ${transactionData.amount} {formatCurrency(transactionData.currency)}
                  </Text>
                </View>
                
                <View style={styles.feeRow}>
                  <Text style={styles.feeLabel}>Comisión de red</Text>
                  <View style={styles.feeValue}>
                    <Text style={styles.feeFree}>Gratis</Text>
                    <Text style={styles.feeNote}>• Cubierto por Confío</Text>
                  </View>
                </View>
                
                <View style={styles.divider} />
                <View style={styles.totalRow}>
                  <Text style={styles.totalLabel}>Total debitado</Text>
                  <Text style={styles.totalValue}>
                    ${transactionData.amount} {formatCurrency(transactionData.currency)}
                  </Text>
                </View>
              </View>

              {/* Payment Details */}
              <View style={styles.detailsContainer}>
                <View style={styles.detailRow}>
                  <Text style={styles.detailLabel}>Fecha y hora</Text>
                  <Text style={styles.detailValue}>
                    {new Date().toLocaleDateString('es-ES')} • {new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}
                  </Text>
                </View>

                {transactionData.transactionHash && (
                  <View style={styles.detailRow}>
                    <Text style={styles.detailLabel}>ID de Transacción</Text>
                    <View style={styles.transactionIdContainer}>
                      <Text style={styles.transactionId}>#{transactionData.transactionHash.slice(0, 8)}</Text>
                      <TouchableOpacity onPress={handleCopy} style={styles.copyButton}>
                        {copied ? (
                          <Icon name="check-circle" size={16} color={colors.accent} />
                        ) : (
                          <Icon name="copy" size={16} color={colors.accent} />
                        )}
                      </TouchableOpacity>
                    </View>
                  </View>
                )}

                <View style={styles.detailRow}>
                  <Text style={styles.detailLabel}>Estado</Text>
                  <View style={styles.statusContainer}>
                    <Icon name="check-circle" size={16} color={colors.success} />
                    <Text style={styles.statusText}>Confirmado</Text>
                  </View>
                </View>

                {transactionData.message && (
                  <View style={styles.messageContainer}>
                    <View style={styles.messageContent}>
                      <Icon name="file-text" size={16} color={colors.accent} />
                      <View style={styles.messageTextContainer}>
                        <Text style={styles.messageLabel}>Descripción</Text>
                        <Text style={styles.messageText}>{transactionData.message}</Text>
                      </View>
                    </View>
                  </View>
                )}
              </View>
            </View>
          </View>

          {/* Confío Value Proposition */}
          <View style={styles.valueContainer}>
            <Text style={styles.sectionTitle}>¿Por qué elegir Confío?</Text>
            
            <View style={styles.valueContent}>
              <View style={styles.valueRow}>
                <Icon name="check-circle" size={20} color={colors.primary} />
                <Text style={styles.valueTitle}>Pagos 100% gratuitos para clientes</Text>
              </View>
              <Text style={styles.valueDescription}>
                Pagaste sin comisiones adicionales
              </Text>
              <View style={styles.valueHighlight}>
                <Text style={styles.valueHighlightText}>
                  💡 <Text style={styles.valueBold}>Confío: 0% para clientes, solo 0.9% para comerciantes</Text>{'\n'}
                  vs. tarjetas tradicionales <Text style={styles.valueBold}>(2.5-3.5% para comerciantes)</Text>{'\n'}
                  Apoyamos a los venezolanos 🇻🇪 con un ecosistema justo
                </Text>
              </View>
            </View>
          </View>

          {/* Quick Actions */}
          <View style={styles.actionsContainer}>
            <Text style={styles.sectionTitle}>Acciones Rápidas</Text>
            
            <View style={styles.actionsContent}>
              <TouchableOpacity 
                style={[styles.actionButton, { backgroundColor: colors.secondary }]}
                onPress={handleRequestReceipt}
              >
                <Icon name="file-text" size={16} color="#ffffff" />
                <Text style={styles.actionButtonText}>Solicitar factura</Text>
              </TouchableOpacity>
              
              <TouchableOpacity 
                style={[styles.actionButton, { backgroundColor: '#F3F4F6' }]}
                onPress={handleShareReceipt}
              >
                <Icon name="share" size={16} color="#374151" />
                <Text style={[styles.actionButtonText, { color: '#374151' }]}>
                  Compartir comprobante
                </Text>
              </TouchableOpacity>
              
              <TouchableOpacity 
                style={[styles.actionButton, { backgroundColor: '#F3F4F6' }]}
                onPress={handleViewTechnicalDetails}
              >
                <Icon name="external-link" size={16} color="#374151" />
                <Text style={[styles.actionButtonText, { color: '#374151' }]}>
                  Ver detalles técnicos
                </Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* Navigation */}
          <View style={styles.navigationContainer}>
            <TouchableOpacity 
              style={[styles.navButton, { backgroundColor: '#F3F4F6' }]}
              onPress={handleGoHome}
            >
              <Icon name="home" size={16} color="#374151" />
              <Text style={[styles.navButtonText, { color: '#374151' }]}>Ir al inicio</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={[styles.navButton, { backgroundColor: colors.secondary }]}
              onPress={handleViewContacts}
            >
              <Icon name="user" size={16} color="#ffffff" />
              <Text style={styles.navButtonText}>Ver contactos</Text>
            </TouchableOpacity>
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
    paddingBottom: 48,
    paddingHorizontal: 16,
  },
  headerContent: {
    alignItems: 'center',
  },
  successCircle: {
    width: 96,
    height: 96,
    backgroundColor: '#ffffff',
    borderRadius: 48,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 24,
    marginBottom: 24,
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
  summaryContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
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
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  summaryContent: {
    gap: 16,
  },
  participantRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  participantAvatar: {
    width: 48,
    height: 48,
    backgroundColor: '#F3F4F6',
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  participantInitial: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#6B7280',
  },
  participantInfo: {
    flex: 1,
  },
  participantName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  participantDetails: {
    fontSize: 14,
    color: '#6B7280',
  },
  participantIcon: {
    width: 32,
    height: 32,
    backgroundColor: '#FEE2E2',
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
  },
  amountBreakdown: {
    backgroundColor: '#F9FAFB',
    padding: 16,
    borderRadius: 12,
  },
  amountRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  amountLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  amountValue: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  feeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  feeLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  feeValue: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  feeFree: {
    fontSize: 14,
    color: '#10B981',
    fontWeight: '500',
    marginRight: 4,
  },
  feeNote: {
    fontSize: 12,
    color: '#6B7280',
  },
  divider: {
    height: 1,
    backgroundColor: '#E5E7EB',
    marginVertical: 8,
  },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  totalLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
  },
  totalValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  detailsContainer: {
    gap: 12,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  detailLabel: {
    fontSize: 14,
    color: '#6B7280',
  },
  detailValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
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
  copyButton: {
    padding: 4,
  },
  statusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#10B981',
    marginLeft: 4,
  },
  messageContainer: {
    backgroundColor: '#F9FAFB',
    borderRadius: 8,
    padding: 12,
  },
  messageContent: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  messageTextContainer: {
    flex: 1,
    marginLeft: 8,
  },
  messageLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 2,
  },
  messageText: {
    fontSize: 14,
    color: '#1F2937',
  },
  valueContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
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
  valueContent: {
    backgroundColor: '#ECFDF5', // emerald-50 equivalent
    borderRadius: 12,
    padding: 16,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  valueTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#065F46', // emerald-800 equivalent
    marginLeft: 8,
  },
  valueDescription: {
    fontSize: 14,
    color: '#047857', // emerald-700 equivalent
    marginBottom: 12,
  },
  valueHighlight: {
    backgroundColor: '#D1FAE5', // emerald-100 equivalent
    borderRadius: 8,
    padding: 12,
  },
  valueHighlightText: {
    fontSize: 12,
    color: '#065F46', // emerald-800 equivalent
    lineHeight: 18,
  },
  valueBold: {
    fontWeight: '600',
    color: '#065F46', // emerald-800 equivalent
  },
  actionsContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
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
  actionsContent: {
    gap: 12,
  },
  actionButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    padding: 16,
  },
  actionButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#ffffff',
    marginLeft: 8,
  },
  navigationContainer: {
    flexDirection: 'row',
    gap: 12,
  },
  navButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    padding: 16,
  },
  navButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#ffffff',
    marginLeft: 8,
  },
}); 