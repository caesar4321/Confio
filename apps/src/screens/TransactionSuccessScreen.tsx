import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Platform, ScrollView, TouchableOpacity, Alert, Linking, Share, Modal, Vibration } from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import WhatsAppLogo from '../assets/svg/WhatsApp.svg';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect } from '@react-navigation/native';
import { SHARE_LINKS } from '../config/shareLinks';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';
import ViewShot from 'react-native-view-shot';
import RNShare from 'react-native-share';
import { colors } from '../config/theme';
import { SuccessHero } from '../components/common/SuccessHero';
import { AnalyticsService } from '../services/analyticsService';
import { StatusTierBadge } from '../components/StatusTierBadge';
import { buildInviteLink, buildSendAndInviteShareMessage } from '../utils/inviteLinks';

type TransactionType = 'sent' | 'received' | 'payment';

interface TransactionData {
  type: TransactionType;
  amount: string;
  currency: string;
  recipient?: string;
  recipientPhone?: string;
  recipientUserId?: string;
  sender?: string;
  senderName?: string;
  recipientName?: string;
  recipientAddress?: string;
  senderAddress?: string;
  merchantAddress?: string;
  message?: string;
  isOnConfio?: boolean;
  internalId?: string;
  merchant?: string;
  invoiceId?: string;
  transactionId?: string;
  transactionHash?: string;
  status?: 'SUBMITTED' | 'CONFIRMED' | 'FAILED';
  // Status tier & verified badge for the counterparty
  recipientStatusTier?: string;
  recipientIsReferralVerified?: boolean;
  senderStatusTier?: string;
  senderIsReferralVerified?: boolean;
}

export const TransactionSuccessScreen = () => {
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

  const [copied, setCopied] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const viewShotRef = useRef<ViewShot>(null);

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

  // Haptic feedback on successful transaction
  useEffect(() => {
    Vibration.vibrate(Platform.OS === 'ios' ? 50 : [0, 50, 30, 50]);
  }, []);

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
        // Use internalId for the receipt verification ID if available, else fallback to hash
        id: (transactionData as any).internalId || transactionData.transactionId,
        transactionHash: (transactionData as any).transactionHash || transactionData.transactionId,
        date: new Date().toISOString(),
        // Pass actual status - only 'CONFIRMED' shows green, else shows yellow pending
        status: (transactionData as any).status || 'SUBMITTED',
        // Map fields for generic view
        employeeName: (transactionData as any).recipient || (transactionData as any).recipientName || 'Empleado',
        employeePhone: (transactionData as any).recipientPhone,
        businessName: (transactionData as any).payerBusiness?.name || (transactionData as any).sender || (transactionData as any).senderName || 'Usuario',
        senderName: (transactionData as any).payerBusiness?.name || (transactionData as any).payerDisplayName || (transactionData as any).senderName || (transactionData as any).sender || 'Usuario',
        recipientName: (transactionData as any).recipientBusiness?.name || (transactionData as any).merchantDisplayName || (transactionData as any).recipientName || (transactionData as any).recipient || 'Usuario',

        // Pass rich objects
        payerBusiness: (transactionData as any).payerBusiness,
        payerDisplayName: (transactionData as any).payerDisplayName,
        merchantBusiness: (transactionData as any).merchantBusiness || (transactionData as any).recipientBusiness,
        merchantDisplayName: (transactionData as any).merchantDisplayName,

        transactionId: (transactionData as any).internalId || transactionData.transactionId,
        verificationId: (transactionData as any).internalId // Explicitly pass verificationId
      },
      type: transactionData.type === 'payment' ? 'payment' : 'transfer'
    });
  };

  const { userProfile } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);

  const handleShareInvitation = async () => {
    const invitationId = (transactionData as any).invitationId
      || (transactionData as any).invitation_id
      || (transactionData as any).idempotencyKey
      || undefined;

    // Fire-and-forget funnel event: the user tapped the WhatsApp share
    // button. This is the first real signal that A will actually notify B
    // about the invite — the critical `invite_submitted → share_tapped`
    // step in the Invitar y Enviar funnel.
    try {
      const currencyForEvent = formatCurrency(transactionData.currency);
      AnalyticsService.logFunnelEvent('whatsapp_share_tapped', {
        invitation_id: invitationId,
        currency: currencyForEvent,
      }, {
        sourceType: 'send_invite',
        channel: 'whatsapp',
      });
    } catch (_e) {
      // never block the share path
    }

    try {
      const phoneRaw = (transactionData as any).recipientPhone as string | undefined;
      const cleanPhone = phoneRaw ? String(phoneRaw).replace(/[^\d]/g, '') : '';
      const amount = String(transactionData.amount).replace(/[+-]/g, '');
      const currency = formatCurrency(transactionData.currency);

      // Generate invite link with uppercase username
      const inviteLink = buildInviteLink({
        username: userProfile?.username,
        source: 'whatsapp',
        invitationId,
      });

      const message = buildSendAndInviteShareMessage({ amount, currency, inviteLink });
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
        const inviteLink = buildInviteLink({
          username: userProfile?.username,
          source: 'whatsapp',
          invitationId,
        });
        const fallbackMessage = buildSendAndInviteShareMessage({
          amount: String(transactionData.amount).replace(/[+-]/g, ''),
          currency: formatCurrency(transactionData.currency),
          inviteLink,
        });
        await Share.share({ message: fallbackMessage });
      } catch (_) { }
      Alert.alert('Error', 'No se pudo abrir WhatsApp.');
    }
  };

  const handleViewTechnicalDetails = () => {
    setShowTechnical(true);
  };

  const handleShareScreenshot = async () => {
    try {
      if (!viewShotRef.current?.capture) return;
      const uri = await viewShotRef.current.capture();
      if (!uri) return;
      const typeLabel = transactionData.type === 'payment' ? 'Pago' : 'Transferencia';
      await RNShare.open({
        title: `Comprobante de ${typeLabel}`,
        message: `${typeLabel} de $${transactionData.amount} ${formatCurrency(transactionData.currency)} por Confío`,
        url: uri,
        type: 'image/jpeg',
        filename: `Confio_${typeLabel}_${displayId.slice(0, 8)}`,
      });
    } catch (error: any) {
      // User cancelled share — not an error
      if (error?.message !== 'User did not share') {      }
    }
  };

  const handleGoHome = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Home' });
  };

  const handleViewContacts = () => {
    (navigation as any).navigate('BottomTabs', { screen: 'Contacts' });
  };

  const displayId = (transactionData as any).internalId || (transactionData as any).transactionId || 'pendiente';
  const transactionId = displayId; // Alias for backward compatibility in render
  const isConfirmed = (transactionData as any).status === 'CONFIRMED';
  const currentDate = new Date().toLocaleDateString('es-ES');
  const currentTime = new Date().toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });

  const needsInvitation = transactionData.type === 'sent'
    && !Boolean(transactionData.isOnConfio)
    && Boolean(transactionData.recipientPhone);

  const counterpartName = transactionData.type === 'sent'
    ? transactionData.recipient
    : transactionData.type === 'payment'
      ? transactionData.merchant
      : transactionData.sender;

  return (
    <>
      <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        {/* ViewShot captures hero + receipt card for the screenshot share */}
        <ViewShot ref={viewShotRef} options={{ format: 'jpg', quality: 0.9 }}>
          <View style={{ backgroundColor: colors.background }}>
            <SuccessHero
              title={transactionData.type === 'sent' ? '¡Enviado con éxito!' :
                transactionData.type === 'payment' ? '¡Pago realizado!' : '¡Recibido con éxito!'}
              amount={`$${transactionData.amount} ${formatCurrency(transactionData.currency)}`}
              hint={transactionData.type === 'sent'
                ? `Enviado a ${transactionData.recipient}`
                : transactionData.type === 'payment'
                  ? `Pagado a ${transactionData.merchant}`
                  : `Recibido de ${transactionData.sender}`}
            />

            {/* Compact receipt card */}
            <View style={styles.card}>
              <View style={styles.row}>
                <Text style={styles.rowLabel}>
                  {transactionData.type === 'received' ? 'De' : 'Para'}
                </Text>
                <View style={styles.rowInline}>
                  <Text style={styles.rowValue} numberOfLines={1}>{counterpartName}</Text>
                  {(() => {
                    const isVerified = transactionData.type === 'sent'
                      ? transactionData.recipientIsReferralVerified
                      : transactionData.senderIsReferralVerified;
                    const tier = transactionData.type === 'sent'
                      ? transactionData.recipientStatusTier
                      : transactionData.senderStatusTier;
                    return (
                      <>
                        {isVerified && (
                          <View style={styles.verifiedDot}>
                            <Icon name="check" size={10} color={colors.white} />
                          </View>
                        )}
                        {tier && tier !== 'member' && (
                          <StatusTierBadge tier={tier} compact />
                        )}
                      </>
                    );
                  })()}
                </View>
              </View>
              {(transactionData.recipientPhone && transactionData.recipientPhone.trim() !== '') ? (
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>Teléfono</Text>
                  <Text style={styles.rowValue}>{transactionData.recipientPhone}</Text>
                </View>
              ) : transactionData.recipientAddress ? (
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>Dirección</Text>
                  <Text style={styles.rowMono}>
                    {`${transactionData.recipientAddress.slice(0, 6)}...${transactionData.recipientAddress.slice(-6)}`}
                  </Text>
                </View>
              ) : null}
              <View style={styles.row}>
                <Text style={styles.rowLabel}>Fecha</Text>
                <Text style={styles.rowValue}>{currentDate} · {currentTime}</Text>
              </View>
              {transactionId && transactionId !== 'pendiente' && (
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>ID</Text>
                  <View style={styles.rowInline}>
                    <Text style={styles.rowMono}>#{String(transactionId).toUpperCase().slice(0, 8)}</Text>
                    <TouchableOpacity onPress={handleCopy} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} accessibilityRole="button" accessibilityLabel="Copiar ID">
                      <Icon name={copied ? 'check-circle' : 'copy'} size={15} color={colors.primaryDark} />
                    </TouchableOpacity>
                  </View>
                </View>
              )}
              <View style={styles.row}>
                <Text style={styles.rowLabel}>Comisión</Text>
                <Text style={[styles.rowValue, { color: colors.primaryDark, fontWeight: '600' }]}>
                  Gratis · cubierta por Confío
                </Text>
              </View>
              <View style={[styles.row, styles.rowLast]}>
                <Text style={styles.rowLabel}>Estado</Text>
                <View style={styles.rowInline}>
                  <Icon
                    name={isConfirmed ? 'check-circle' : 'clock'}
                    size={15}
                    color={isConfirmed ? colors.success : colors.warning.icon}
                  />
                  <Text style={[styles.rowValue, { color: isConfirmed ? colors.success : colors.warning.icon, fontWeight: '600' }]}>
                    {isConfirmed ? 'Confirmado' : 'Confirmando…'}
                  </Text>
                </View>
              </View>
              {transactionData.message ? (
                <View style={styles.messageBox}>
                  <Text style={styles.messageLabel}>Mensaje</Text>
                  <Text style={styles.messageText}>{transactionData.message}</Text>
                </View>
              ) : null}
            </View>
          </View>
        </ViewShot>

        {/* Invitation urgency — the one loud block, only when money can expire */}
        {needsInvitation && (
          <View style={styles.invitationCard}>
            <View style={styles.invitationHeader}>
              <Icon name="alert-circle" size={20} color={colors.danger} />
              <Text style={styles.invitationTitle}>Tu amigo aún no está en Confío</Text>
            </View>
            <Text style={styles.invitationText}>
              Tiene 7 días para crear su cuenta y reclamar el dinero — avísale ahora
              para que no se pierda.
            </Text>
            <TouchableOpacity
              style={styles.shareButton}
              onPress={handleShareInvitation}
              accessibilityRole="button"
              accessibilityLabel="Compartir invitación por WhatsApp"
            >
              <WhatsAppLogo width={20} height={20} style={{ marginRight: 8 }} />
              <Text style={styles.shareButtonText}>Avisar por WhatsApp</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Quiet secondary actions */}
        <View style={styles.secondaryRow}>
          {transactionData.type === 'sent' && (
            <TouchableOpacity style={styles.secondaryBtn} onPress={handleSendAgain} accessibilityRole="button" accessibilityLabel={`Enviar de nuevo a ${counterpartName}`}>
              <Icon name="refresh-cw" size={16} color={colors.gray700} />
              <Text style={styles.secondaryText}>Reenviar</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity style={styles.secondaryBtn} onPress={handleShareScreenshot} accessibilityRole="button" accessibilityLabel="Compartir captura del comprobante">
            <Icon name="share-2" size={16} color={colors.gray700} />
            <Text style={styles.secondaryText}>Compartir</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryBtn} onPress={handleShareReceipt} accessibilityRole="button" accessibilityLabel="Ver comprobante oficial">
            <Icon name="file-text" size={16} color={colors.gray700} />
            <Text style={styles.secondaryText}>Comprobante</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryBtn} onPress={handleViewTechnicalDetails} accessibilityRole="button" accessibilityLabel="Ver detalles técnicos">
            <Icon name="external-link" size={16} color={colors.gray700} />
            <Text style={styles.secondaryText}>Detalles</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.ctaWrap}>
          <TouchableOpacity style={styles.cta} onPress={handleGoHome} activeOpacity={0.85} accessibilityRole="button">
            <Text style={styles.ctaText}>Listo</Text>
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
  scrollContent: {
    flexGrow: 1,
    paddingBottom: 24,
  },
  // Compact receipt card (captured by ViewShot together with the hero)
  card: {
    marginHorizontal: 24,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 16,
    marginBottom: 4,
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
  verifiedDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
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
  // Invitation urgency: deliberately the ONE loud block on the page —
  // money genuinely expires if the recipient never claims it.
  invitationCard: {
    marginHorizontal: 24,
    marginTop: 20,
    backgroundColor: colors.error.background,
    borderWidth: 1,
    borderColor: colors.error.border,
    borderRadius: 16,
    padding: 16,
  },
  invitationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 6,
  },
  invitationTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.error.text,
    flex: 1,
  },
  invitationText: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.error.text,
    marginBottom: 12,
  },
  shareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#25D366', // WhatsApp brand green (nominative use)
    borderRadius: 12,
    paddingVertical: 13,
  },
  shareButtonText: {
    color: colors.white,
    fontSize: 15,
    fontWeight: '700',
  },
  // Quiet secondary actions
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
  // Primary CTA pill
  ctaWrap: {
    flex: 1,
    justifyContent: 'flex-end',
    alignItems: 'center',
    paddingTop: 28,
    paddingHorizontal: 24,
  },
  cta: {
    backgroundColor: colors.primary,
    borderRadius: 14,
    paddingVertical: 15,
    paddingHorizontal: 40,
    minWidth: 200,
    alignItems: 'center',
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
