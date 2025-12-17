import React, { useState } from 'react';
import { View, Text, StyleSheet, Platform, ScrollView, TouchableOpacity, Alert, Clipboard, Linking, Share, Modal } from 'react-native';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect } from '@react-navigation/native';
import { SHARE_LINKS } from '../config/shareLinks';
import { useAuth } from '../contexts/AuthContext';

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

type TransactionType = 'sent' | 'received' | 'payment';

interface TransactionData {
  type: TransactionType;
  amount: string;
  currency: string;
  recipient?: string;
  recipientPhone?: string;
  recipientUserId?: string;
  sender?: string;
  recipientAddress?: string;
  senderAddress?: string;
  merchantAddress?: string;
  message?: string;
  isOnConfio?: boolean;
  sendTransactionId?: string;
  merchant?: string;
  invoiceId?: string;
  transactionId?: string;
  status?: 'SUBMITTED' | 'CONFIRMED' | 'FAILED';
}

export const TransactionSuccessScreen = () => {
  console.log('TransactionSuccessScreen: Component mounted');
  const navigation = useNavigation();
  const route = useRoute();

  const transactionData: TransactionData = (route.params as any)?.transactionData || {
    type: 'sent',
    amount: '125.50',
    currency: 'cUSD',
    recipient: 'María González',
    recipientAddress: '0x1a2b3c4d...7890abcd',
    message: 'Transferencia',
    isOnConfio: true
  };

  // Debug logging
  console.log('TransactionSuccessScreen: Received transaction data:', transactionData);
  console.log('TransactionSuccessScreen: isOnConfio value:', transactionData.isOnConfio);

  const [copied, setCopied] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);

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

      return () => { };
    }, [])
  );

  const handleCopy = () => {
    Clipboard.setString(transactionId);
    Alert.alert('Copiado', 'ID de transacción copiado al portapapeles');
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSendAgain = () => {
    if (transactionData.type === 'sent') {
      // Check if it's an external wallet send (has address but no phone)
      if (transactionData.recipientAddress && !transactionData.recipientPhone) {
        console.log('TransactionSuccessScreen: handleSendAgain - navigating to SendWithAddress');
        (navigation as any).navigate('SendWithAddress', {
          tokenType: transactionData.currency.toLowerCase() === 'cusd' ? 'cusd' : 'confio',
          prefilledAddress: transactionData.recipientAddress
        });
      } else if (transactionData.recipient) {
        // Friend or invitation send
        const friendData = {
          name: transactionData.recipient,
          avatar: transactionData.recipient?.charAt(0) || 'F',
          phone: transactionData.recipientPhone || '', // Use actual phone number from transaction
          isOnConfio: Boolean(transactionData.isOnConfio), // Ensure proper boolean conversion
          userId: transactionData.recipientUserId, // Pass user ID if available
          // aptosAddress removed - server will determine this
        };

        console.log('TransactionSuccessScreen: handleSendAgain - friend data:', friendData);
        console.log('TransactionSuccessScreen: transactionData.isOnConfio:', transactionData.isOnConfio);
        console.log('TransactionSuccessScreen: transactionData.recipientAddress:', transactionData.recipientAddress);

        (navigation as any).navigate('SendToFriend', {
          friend: friendData,
          tokenType: transactionData.currency.toLowerCase() === 'cusd' ? 'cusd' : 'confio' // Use same currency as original transaction
        });
      }
    }
  };



  const handleShareReceipt = () => {
    (navigation as any).navigate('TransactionReceipt', {
      transaction: {
        ...transactionData,
        id: transactionData.transactionId,
        transactionHash: transactionData.transactionId,
        date: new Date().toISOString(),
        status: 'completed', // Success screen implies completion
        // Map fields for generic view
        employeeName: transactionData.recipient,
        employeePhone: transactionData.recipientPhone,
        businessName: transactionData.sender || 'Usuario', // For P2P
        transactionId: transactionData.transactionId
      },
      type: transactionData.type === 'payment' ? 'payment' : 'transfer'
    });
  };

  const { userProfile } = useAuth();

  const handleShareInvitation = async () => {
    try {
      const phoneRaw = (transactionData as any).recipientPhone as string | undefined;
      const cleanPhone = phoneRaw ? String(phoneRaw).replace(/[^\d]/g, '') : '';
      const amount = String(transactionData.amount).replace(/[+-]/g, '');
      const currency = formatCurrency(transactionData.currency);

      // Generate invite link with uppercase username
      const rawUsername = userProfile?.username || '';
      const cleanUsername = rawUsername.replace('@', '').toUpperCase();
      const inviteLink = `https://confio.lat/invite/${cleanUsername}`;

      const message = `¡Hola! Te envié ${amount} ${currency} por Confío. 🎉\n\nTienes 7 días para reclamarlo. Descarga la app y crea tu cuenta:\n\n📲 ${inviteLink}\n\n¡Es gratis y en segundos recibes tu dinero!`;
      const encodedMessage = encodeURIComponent(message);

      if (Platform.OS === 'android') {
        const apiUrl = cleanPhone
          ? `https://api.whatsapp.com/send?phone=${cleanPhone}&text=${encodedMessage}`
          : `https://api.whatsapp.com/send?text=${encodedMessage}`;
        try {
          await Linking.openURL(apiUrl);
          return;
        } catch (e) { }

        const schemeUrl = cleanPhone
          ? `whatsapp://send?phone=${cleanPhone}&text=${encodedMessage}`
          : `whatsapp://send?text=${encodedMessage}`;
        const canOpenScheme = await Linking.canOpenURL(schemeUrl);
        if (canOpenScheme) {
          await Linking.openURL(schemeUrl);
          return;
        }

        const intentUrl = `intent://send?text=${encodedMessage}#Intent;scheme=whatsapp;package=com.whatsapp;end`;
        try {
          await Linking.openURL(intentUrl);
          return;
        } catch (_) { }

        const webUrl = cleanPhone
          ? `https://wa.me/${cleanPhone}?text=${encodedMessage}`
          : `https://wa.me/?text=${encodedMessage}`;
        const canOpenWeb = await Linking.canOpenURL(webUrl);
        if (canOpenWeb) {
          await Linking.openURL(webUrl);
          return;
        }

        try {
          await Linking.openURL('market://details?id=com.whatsapp');
          return;
        } catch (_) { }
        await Share.share({ message });
        return;
      } else {
        const schemeUrl = cleanPhone
          ? `whatsapp://send?phone=${cleanPhone}&text=${encodedMessage}`
          : `whatsapp://send?text=${encodedMessage}`;
        const canOpen = await Linking.canOpenURL(schemeUrl);
        if (canOpen) {
          await Linking.openURL(schemeUrl);
          return;
        }
        const webUrl = cleanPhone
          ? `https://wa.me/${cleanPhone}?text=${encodedMessage}`
          : `https://wa.me/?text=${encodedMessage}`;
        const canOpenWeb = await Linking.canOpenURL(webUrl);
        if (canOpenWeb) {
          await Linking.openURL(webUrl);
          return;
        }
        await Share.share({ message });
      }
    } catch (error) {
      try {
        await Share.share({ message: `Te envié dinero por Confío. ${SHARE_LINKS.campaigns.beta}` });
      } catch (_) { }
      Alert.alert('Error', 'No se pudo abrir WhatsApp.');
    }
  };

  const handleViewTechnicalDetails = () => {
    setShowTechnical(true);
  };

  const handleGoHome = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Home' });
  };

  const handleViewContacts = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Contacts' });
  };

  const transactionId = (transactionData as any).transactionId || 'pendiente';
  const isConfirmed = (transactionData as any).status === 'CONFIRMED';
  const currentDate = new Date().toLocaleDateString('es-ES');
  const currentTime = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });

  return (
    <>
      <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
        {/* Success Header */}
        <View style={[styles.header, { backgroundColor: colors.primary, paddingTop: 8 }]}>
          <View style={styles.headerContent}>
            {/* Success Animation */}
            <View style={styles.successCircle}>
              <Icon name="check-circle" size={48} color={colors.primary} />
            </View>

            <Text style={styles.headerTitle}>
              {transactionData.type === 'sent' ? '¡Enviado con éxito!' :
                transactionData.type === 'payment' ? '¡Pago realizado!' : '¡Recibido con éxito!'}
            </Text>

            <Text style={styles.headerAmount}>
              {transactionData.type === 'sent' ? '-' : '+'}${transactionData.amount} {formatCurrency(transactionData.currency)}
            </Text>

            <Text style={styles.headerSubtitle}>
              {transactionData.type === 'sent'
                ? `Enviado a ${transactionData.recipient}`
                : transactionData.type === 'payment'
                  ? `Pagado a ${transactionData.merchant}`
                  : `Recibido de ${transactionData.sender}`
              }
            </Text>

            {transactionData.type === 'sent' && !transactionData.isOnConfio && transactionData.recipientPhone && (
              <View style={styles.invitationNotice}>
                <Icon name="alert-triangle" size={16} color="#fff" style={{ marginRight: 6 }} />
                <Text style={styles.invitationNoticeText}>Tu amigo tiene 7 días para reclamar</Text>
              </View>
            )}
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
                      : transactionData.type === 'payment'
                        ? transactionData.merchant?.charAt(0)
                        : transactionData.sender?.charAt(0)
                    }
                  </Text>
                </View>
                <View style={styles.participantInfo}>
                  <Text style={styles.participantName}>
                    {transactionData.type === 'sent'
                      ? transactionData.recipient
                      : transactionData.type === 'payment'
                        ? transactionData.merchant
                        : transactionData.sender}
                  </Text>
                  {/* Show phone number for friend transactions, address for external wallets */}
                  {transactionData.recipientPhone && transactionData.recipientPhone.trim() !== '' ? (
                    <Text style={styles.participantDetails}>
                      {transactionData.recipientPhone}
                    </Text>
                  ) : transactionData.recipientAddress ? (
                    <Text style={styles.participantDetails}>
                      {`${transactionData.recipientAddress.slice(0, 6)}...${transactionData.recipientAddress.slice(-6)}`}
                    </Text>
                  ) : null}
                </View>
                <View style={styles.participantIcon}>
                  <Icon
                    name={transactionData.type === 'sent' || transactionData.type === 'payment' ? 'arrow-up' : 'arrow-down'}
                    size={16}
                    color={transactionData.type === 'sent' || transactionData.type === 'payment' ? '#EF4444' : '#10B981'}
                  />
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

                {transactionId && transactionId !== 'pendiente' && (
                  <View style={styles.detailRow}>
                    <Text style={styles.detailLabel}>ID de Transacción</Text>
                    <View style={styles.transactionIdContainer}>
                      <Text style={styles.transactionId}>#{String(transactionId).slice(0, 8)}</Text>
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
                    {isConfirmed ? (
                      <>
                        <Icon name="check-circle" size={16} color={colors.success} />
                        <Text style={styles.statusText}>Confirmado</Text>
                      </>
                    ) : (
                      <>
                        <Icon name="clock" size={16} color={colors.warning} />
                        <Text style={[styles.statusText, { color: colors.warning }]}>Confirmando…</Text>
                      </>
                    )}
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

          {/* Remittance Invitation Section - Only for non-Confío friends with phone numbers */}
          {(() => {
            const isOnConfio = Boolean(transactionData.isOnConfio);
            const hasPhone = Boolean(transactionData.recipientPhone);
            console.log('TransactionSuccessScreen: Checking invitation box condition:', {
              type: transactionData.type,
              isOnConfio: transactionData.isOnConfio,
              isOnConfioBoolean: isOnConfio,
              hasPhone: hasPhone,
              shouldShow: transactionData.type === 'sent' && !isOnConfio && hasPhone
            });
            return transactionData.type === 'sent' && !isOnConfio && hasPhone;
          })() && (
              <View style={[styles.remittanceContainer, styles.invitationCard]}>
                <View style={styles.invitationHeader}>
                  <Icon name="alert-circle" size={24} color="#ef4444" />
                  <Text style={[styles.sectionTitle, styles.invitationCardTitle]}>¡Acción Requerida!</Text>
                </View>

                <View style={styles.remittanceContent}>
                  <Text style={[styles.remittanceCardText, { fontWeight: 'bold', color: '#dc2626' }]}>
                    ⏰ Tu amigo tiene solo 7 días para reclamar el dinero o se perderá
                  </Text>

                  <View style={[styles.remittanceDetailsBox, { backgroundColor: '#fef2f2', borderColor: '#ef4444' }]}>
                    <Text style={[styles.remittanceDetailsTitle, { color: '#dc2626' }]}>¡Avísale ahora mismo!</Text>
                    <View style={styles.remittanceDetailRow}>
                      <Text style={styles.remittanceDetailText}>1. Envíale un mensaje con el link de invitación</Text>
                    </View>
                    <View style={styles.remittanceDetailRow}>
                      <Text style={styles.remittanceDetailText}>2. Ayúdale a crear su cuenta en Confío</Text>
                    </View>
                    <View style={styles.remittanceDetailRow}>
                      <Text style={styles.remittanceDetailText}>3. Una vez registrado, recibirá el dinero al instante</Text>
                    </View>
                  </View>

                  <TouchableOpacity
                    style={styles.shareButton}
                    onPress={handleShareInvitation}
                  >
                    <WhatsAppLogo width={20} height={20} style={{ marginRight: 8 }} />
                    <Text style={styles.shareButtonText}>Compartir invitación por WhatsApp</Text>
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
                  Apoyamos a los argentinos 🇦🇷 con transferencias gratuitas
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
                    {transactionData.recipientAddress && !transactionData.recipientPhone
                      ? `Enviar de nuevo a ${transactionData.recipientAddress.slice(0, 6)}...${transactionData.recipientAddress.slice(-4)}`
                      : `Enviar de nuevo a ${transactionData.recipient}`
                    }
                  </Text>
                </TouchableOpacity>
              )}



              <TouchableOpacity
                style={[styles.actionButton, { backgroundColor: '#ECFDF5', borderWidth: 1, borderColor: '#A7F3D0' }]}
                onPress={handleShareReceipt}
              >
                <Icon name="file-text" size={16} color="#059669" />
                <Text style={[styles.actionButtonText, { color: '#059669' }]}>
                  Ver comprobante oficial
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
              <TouchableOpacity onPress={() => setShowTechnical(false)} style={{ padding: 8 }}>
                <Icon name="x" size={20} color={colors.text.primary} />
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
                      const h = ((transactionData as any).transactionHash || '').toString();
                      if (!h) return 'N/D';
                      return h.replace(/(.{10}).+(.{6})/, '$1…$2');
                    })()}
                  </Text>
                </View>
              </View>
              <TouchableOpacity
                style={[styles.explorerButton, { backgroundColor: colors.secondary }]}
                onPress={async () => {
                  const txid = (transactionData as any).transactionHash;
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
    </>
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
  invitationNotice: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 12,
    backgroundColor: '#ef4444',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  invitationNoticeText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '500',
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
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: '#fff',
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
    borderBottomColor: '#e5e7eb',
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
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
    color: '#374151',
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
    color: '#6b7280',
  },
  modalValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#111827',
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
    color: '#fff',
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
  invitationCard: {
    backgroundColor: '#fef2f2',
    borderColor: '#ef4444',
    borderWidth: 2,
  },
  invitationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  invitationCardTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#ef4444',
    marginLeft: 12,
    marginBottom: 0,
  },
  remittanceContent: {
    gap: 16,
  },
  remittanceCardText: {
    fontSize: 16,
    color: '#1f2937',
    marginBottom: 16,
    lineHeight: 24,
  },
  remittanceDetailsBox: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#ef4444',
    marginBottom: 16,
  },
  remittanceDetailsTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#dc2626',
    marginBottom: 12,
  },
  remittanceDetailRow: {
    marginBottom: 8,
  },
  remittanceDetailText: {
    fontSize: 14,
    color: '#1f2937',
  },
  shareButton: {
    backgroundColor: '#25D366', // WhatsApp green
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    paddingHorizontal: 24,
    borderRadius: 12,
    marginTop: 4,
  },
  shareButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
}); 
