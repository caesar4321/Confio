import React, { useState } from 'react';
import { View, Text, StyleSheet, Platform, ScrollView, TouchableOpacity, Alert } from 'react-native';
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

type TransactionType = 'sent' | 'received';

interface TransactionData {
  type: TransactionType;
  amount: string;
  currency: string;
  recipient?: string;
  sender?: string;
  recipientAddress?: string;
  senderAddress?: string;
  message?: string;
  isOnConfio?: boolean;
}

export const TransactionSuccessScreen = () => {
  console.log('TransactionSuccessScreen: Component mounted');
  const navigation = useNavigation();
  const route = useRoute();
  const insets = useSafeAreaInsets();
  
  const transactionData: TransactionData = (route.params as any)?.transactionData || {
    type: 'sent',
    amount: '125.50',
    currency: 'cUSD',
    recipient: 'María González',
    recipientAddress: '0x1a2b3c4d...7890abcd',
    message: 'Transferencia',
    isOnConfio: true
  };

  const [copied, setCopied] = useState(false);

  // Helper function to format currency for display
  const formatCurrency = (currency: string): string => {
    if (currency === 'CUSD') return 'cUSD';
    if (currency === 'CONFIO') return 'CONFIO';
    if (currency === 'USDC') return 'USDC';
    return currency; // fallback
  };

  // Prevent back navigation
  useFocusEffect(
    React.useCallback(() => {
      const onBackPress = () => {
        // Prevent back navigation - user must use action buttons
        return true;
      };

      return () => {};
    }, [])
  );

  const handleCopy = () => {
    // In a real app, you'd copy the transaction ID
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSendAgain = () => {
    if (transactionData.type === 'sent' && transactionData.recipient) {
      (navigation as any).navigate('SendToFriend', { 
        friend: { 
          name: transactionData.recipient, 
          phone: transactionData.recipientAddress || '' 
        } 
      });
    }
  };



  const handleShareReceipt = () => {
    Alert.alert('Compartir Comprobante', 'Función de compartir en desarrollo');
  };

  const handleShareInvitation = () => {
    // Share invitation for non-Confío friends
    const invitationMessage = `¡Hola ${transactionData.recipient}! Te envié $${transactionData.amount} ${formatCurrency(transactionData.currency)} a través de Confío. 

Para reclamar tu dinero, descarga Confío y crea tu cuenta en los próximos 7 días:

📱 Descarga Confío: https://confio.lat
💰 Monto: $${transactionData.amount} ${formatCurrency(transactionData.currency)}
⏰ Válido hasta: ${new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toLocaleDateString('es-ES')}

¡Confío - Transferencias gratuitas para Latinoamérica! 🇻🇪`;

    Alert.alert(
      'Compartir Invitación',
      '¿Quieres compartir la invitación con ' + transactionData.recipient + '?',
      [
        { text: 'Cancelar', style: 'cancel' },
        { 
          text: 'Compartir', 
          onPress: () => {
            // In a real app, this would use the Share API
            Alert.alert('Invitación Compartida', 'La invitación se ha compartido exitosamente. Tu amigo tiene 7 días para reclamar el dinero.');
          }
        }
      ]
    );
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

  const transactionId = 'ABC123DEF456';
  const currentDate = new Date().toLocaleDateString('es-ES');
  const currentTime = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });

  return (
    <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
      {/* Success Header */}
      <View style={[styles.header, { backgroundColor: colors.primary, paddingTop: insets.top + 8 }]}>
        <View style={styles.headerContent}>
          {/* Success Animation */}
          <View style={styles.successCircle}>
            <Icon name="check-circle" size={48} color={colors.primary} />
          </View>
          
          <Text style={styles.headerTitle}>
            {transactionData.type === 'sent' ? '¡Enviado con éxito!' : '¡Recibido con éxito!'}
          </Text>
          
          <Text style={styles.headerAmount}>
            {transactionData.type === 'sent' ? '-' : '+'}${transactionData.amount} {formatCurrency(transactionData.currency)}
          </Text>
          
          <Text style={styles.headerSubtitle}>
            {transactionData.type === 'sent' 
              ? `Enviado a ${transactionData.recipient}`
              : `Recibido de ${transactionData.sender}`
            }
          </Text>
        </View>
      </View>

      {/* Content */}
      <View style={styles.content}>
        {/* Transaction Summary */}
        <View style={styles.summaryContainer}>
          <Text style={styles.sectionTitle}>Resumen de Transacción</Text>
          
          <View style={styles.summaryContent}>
            {/* Participant Info */}
            <View style={styles.participantRow}>
              <View style={styles.participantAvatar}>
                <Text style={styles.participantInitial}>
                  {transactionData.type === 'sent' 
                    ? transactionData.recipient?.charAt(0) 
                    : transactionData.sender?.charAt(0)
                  }
                </Text>
              </View>
              <View style={styles.participantInfo}>
                <Text style={styles.participantName}>
                  {transactionData.type === 'sent' ? transactionData.recipient : transactionData.sender}
                </Text>
                <Text style={styles.participantDetails}>
                  {transactionData.type === 'sent' 
                    ? transactionData.recipientAddress 
                    : transactionData.senderAddress
                  }
                </Text>
              </View>
              <View style={styles.participantIcon}>
                <Icon name={transactionData.type === 'sent' ? 'arrow-up' : 'arrow-down'} size={16} color={transactionData.type === 'sent' ? '#EF4444' : '#10B981'} />
              </View>
            </View>

            {/* Amount Breakdown */}
            <View style={styles.amountBreakdown}>
              <View style={styles.amountRow}>
                <Text style={styles.amountLabel}>
                  {transactionData.type === 'sent' ? 'Monto enviado' : 'Monto recibido'}
                </Text>
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
              
              {transactionData.type === 'sent' && (
                <>
                  <View style={styles.divider} />
                  <View style={styles.totalRow}>
                    <Text style={styles.totalLabel}>Total debitado</Text>
                    <Text style={styles.totalValue}>
                      ${transactionData.amount} {formatCurrency(transactionData.currency)}
                    </Text>
                  </View>
                </>
              )}
            </View>

            {/* Transaction Details */}
            <View style={styles.detailsContainer}>
              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>Fecha y hora</Text>
                <Text style={styles.detailValue}>
                  {currentDate} • {currentTime}
                </Text>
              </View>

              <View style={styles.detailRow}>
                <Text style={styles.detailLabel}>ID de Transacción</Text>
                <View style={styles.transactionIdContainer}>
                  <Text style={styles.transactionId}>#{transactionId}</Text>
                  <TouchableOpacity onPress={handleCopy} style={styles.copyButton}>
                    {copied ? (
                      <Icon name="check-circle" size={16} color={colors.accent} />
                    ) : (
                      <Icon name="copy" size={16} color={colors.accent} />
                    )}
                  </TouchableOpacity>
                </View>
              </View>

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
                      <Text style={styles.messageLabel}>Mensaje</Text>
                      <Text style={styles.messageText}>{transactionData.message}</Text>
                    </View>
                  </View>
                </View>
              )}
            </View>
          </View>
        </View>

        {/* Remittance Invitation Section - Only for non-Confío friends */}
        {transactionData.type === 'sent' && !transactionData.isOnConfio && (
          <View style={styles.remittanceContainer}>
            <Text style={styles.sectionTitle}>Invitación de Remesa</Text>
            
            <View style={styles.remittanceContent}>
              <View style={styles.remittanceHeader}>
                <View style={styles.remittanceIconContainer}>
                  <Icon name="gift" size={24} color={colors.secondary} />
                </View>
                <View style={styles.remittanceInfo}>
                  <Text style={styles.remittanceTitle}>¡Dinero enviado con invitación!</Text>
                  <Text style={styles.remittanceSubtitle}>
                    {transactionData.recipient} recibirá una invitación para reclamar ${transactionData.amount} {formatCurrency(transactionData.currency)}
                  </Text>
                </View>
              </View>
              
              <View style={styles.remittanceDetails}>
                <View style={styles.remittanceDetailRow}>
                  <Icon name="clock" size={16} color={colors.warning} />
                  <Text style={styles.remittanceDetailText}>
                    <Text style={styles.remittanceBold}>7 días</Text> para reclamar el dinero
                  </Text>
                </View>
                <View style={styles.remittanceDetailRow}>
                  <Icon name="smartphone" size={16} color={colors.accent} />
                  <Text style={styles.remittanceDetailText}>
                    Debe descargar Confío y crear una cuenta
                  </Text>
                </View>
                <View style={styles.remittanceDetailRow}>
                  <Icon name="check-circle" size={16} color={colors.success} />
                  <Text style={styles.remittanceDetailText}>
                    Transferencia <Text style={styles.remittanceBold}>100% gratuita</Text>
                  </Text>
                </View>
              </View>
              
              <TouchableOpacity 
                style={[styles.actionButton, { backgroundColor: colors.secondary }]}
                onPress={handleShareInvitation}
              >
                <Icon name="share" size={16} color="#ffffff" />
                <Text style={styles.actionButtonText}>
                  Compartir invitación con {transactionData.recipient}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Confío Value Proposition */}
        <View style={styles.valueContainer}>
          <Text style={styles.sectionTitle}>¿Por qué elegir Confío?</Text>
          
          <View style={styles.valueContent}>
            <View style={styles.valueRow}>
              <Icon name="check-circle" size={20} color={colors.primary} />
              <Text style={styles.valueTitle}>Transferencias 100% gratuitas</Text>
            </View>
            <Text style={styles.valueDescription}>
              {transactionData.type === 'sent' 
                ? 'Enviaste este dinero sin pagar comisiones'
                : 'Recibiste este dinero sin comisiones'
              }
            </Text>
            <View style={styles.valueHighlight}>
              <Text style={styles.valueHighlightText}>
                💡 <Text style={styles.valueBold}>Confío: 0% comisión</Text>{'\n'}
                vs. remesadoras tradicionales <Text style={styles.valueBold}>(5%-20%)</Text>{'\n'}
                Apoyamos a los venezolanos 🇻🇪 con transferencias gratuitas
              </Text>
            </View>
          </View>
        </View>

        {/* Quick Actions */}
        <View style={styles.actionsContainer}>
          <Text style={styles.sectionTitle}>Acciones Rápidas</Text>
          
          <View style={styles.actionsContent}>
            {transactionData.type === 'sent' && (
              <TouchableOpacity 
                style={[styles.actionButton, { backgroundColor: colors.primary }]}
                onPress={handleSendAgain}
              >
                <Icon name="user" size={16} color="#ffffff" />
                <Text style={styles.actionButtonText}>
                  Enviar de nuevo a {transactionData.recipient}
                </Text>
              </TouchableOpacity>
            )}
            

            
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
    color: colors.text.primary,
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
    color: colors.text.primary,
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
    color: colors.text.primary,
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
    color: colors.success,
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
    color: colors.text.primary,
  },
  totalValue: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
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
    color: colors.text.primary,
  },
  transactionIdContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  transactionId: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
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
    color: colors.success,
    marginLeft: 4,
  },
  messageContainer: {
    backgroundColor: '#DBEAFE',
    padding: 12,
    borderRadius: 8,
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
    fontWeight: '600',
    color: '#1E40AF',
    marginBottom: 4,
  },
  messageText: {
    fontSize: 14,
    color: '#1E3A8A',
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
    backgroundColor: '#D1FAE5',
    padding: 16,
    borderRadius: 12,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  valueTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#065F46',
    marginLeft: 8,
  },
  valueDescription: {
    fontSize: 14,
    color: '#047857',
    marginBottom: 12,
  },
  valueHighlight: {
    backgroundColor: '#A7F3D0',
    padding: 12,
    borderRadius: 8,
  },
  valueHighlightText: {
    fontSize: 12,
    color: '#065F46',
    lineHeight: 16,
  },
  valueBold: {
    fontWeight: 'bold',
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
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
  },
  actionButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#ffffff',
    marginLeft: 8,
  },
  navigationContainer: {
    flexDirection: 'row',
    gap: 16,
    marginBottom: 24,
  },
  navButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
  },
  navButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#ffffff',
    marginLeft: 8,
  },
  remittanceContainer: {
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
  remittanceContent: {
    gap: 16,
  },
  remittanceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  remittanceIconContainer: {
    width: 48,
    height: 48,
    backgroundColor: '#F3F4F6',
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  remittanceInfo: {
    flex: 1,
  },
  remittanceTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginBottom: 8,
  },
  remittanceSubtitle: {
    fontSize: 14,
    color: '#6B7280',
  },
  remittanceDetails: {
    gap: 12,
  },
  remittanceDetailRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  remittanceDetailText: {
    fontSize: 14,
    color: '#6B7280',
    marginLeft: 8,
  },
  remittanceBold: {
    fontWeight: 'bold',
  },
}); 