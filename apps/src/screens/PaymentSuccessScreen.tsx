import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Dimensions,
  Alert,
  Platform,
  Modal,
  Linking,
  Share,
  Vibration,
} from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { colors } from '../config/theme';
import { SuccessHero } from '../components/common/SuccessHero';
import { formatLocalDate, formatLocalTime } from '../utils/dateUtils';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';

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
      internalId?: string;
      status?: string;
    };
  };
}, 'PaymentSuccess'>;

const { width } = Dimensions.get('window');

export const PaymentSuccessScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<PaymentSuccessRouteProp>();
  const { transactionData } = route.params;
  const [copied, setCopied] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);
  const { userProfile, profileData } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);

  // Haptic feedback on successful payment
  useEffect(() => {
    Vibration.vibrate(Platform.OS === 'ios' ? 50 : [0, 50, 30, 50]);
  }, []);

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
    if (transactionData.transactionHash) {
      Clipboard.setString(transactionData.transactionHash);
      Alert.alert('Copiado', 'ID de transacción copiado al portapapeles');
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleShareReceipt = () => {
    (navigation as any).navigate('TransactionReceipt', {
      transaction: {
        ...transactionData,
        id: transactionData.internalId || transactionData.transactionHash || 'pending',
        transactionHash: transactionData.transactionHash || 'pending',
        date: new Date().toISOString(),
        // Pass actual status - 'CONFIRMED' for green, anything else for yellow pending
        status: transactionData.status || 'pending',
        // Map fields for generic view
        merchantName: transactionData.merchant,
        merchantAddress: transactionData.merchantAddress,
        amount: transactionData.amount,
        currency: transactionData.currency,
        transactionId: transactionData.internalId || transactionData.transactionHash,
        // verificationId for QR code - ONLY use internalId (UUID), never transactionHash
        verificationId: transactionData.internalId || undefined,

        // Inject current user info as payer (since this screen is for the payer)
        payerName: profileData?.currentAccountType === 'business'
          ? profileData?.businessProfile?.name || 'Negocio'
          : (userProfile?.firstName
            ? `${userProfile.firstName} ${userProfile.lastName || ''}`.trim()
            : (userProfile?.username || 'Usuario')),

        payerDisplayName: profileData?.currentAccountType === 'business'
          ? profileData?.businessProfile?.name || 'Negocio'
          : (userProfile?.firstName
            ? `${userProfile.firstName} ${userProfile.lastName || ''}`.trim()
            : (userProfile?.username || 'Usuario')),

        senderUser: userProfile,
        payerBusiness: profileData?.currentAccountType === 'business' ? profileData?.businessProfile : undefined,
      },
      type: 'payment'
    });
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

  const isPending = transactionData.status === 'SUBMITTED' || !transactionData.transactionHash;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <SuccessHero
          title="¡Pago realizado!"
          amount={`$${transactionData.amount} ${formatCurrency(transactionData.currency)}`}
          hint={`Pagado en ${transactionData.merchant}`}
        />

        {/* Compact receipt card: everything else is one quiet card. */}
        <View style={styles.card}>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Comercio</Text>
            <Text style={styles.rowValue} numberOfLines={1}>
              {transactionData.location && transactionData.terminal
                ? `${transactionData.merchant} · ${transactionData.location}`
                : transactionData.merchant}
            </Text>
          </View>
          <View style={styles.row}>
            <Text style={styles.rowLabel}>Fecha</Text>
            <Text style={styles.rowValue}>
              {formatLocalDate(new Date().toISOString())} · {formatLocalTime(new Date().toISOString())}
            </Text>
          </View>
          {(transactionData.transactionHash && transactionData.transactionHash !== 'pending') ? (
            <View style={styles.row}>
              <Text style={styles.rowLabel}>ID</Text>
              <View style={styles.rowInline}>
                <Text style={styles.rowMono}>#{transactionData.transactionHash.slice(0, 8)}</Text>
                <TouchableOpacity onPress={handleCopy} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }} accessibilityRole="button" accessibilityLabel="Copiar ID">
                  <Icon name={copied ? 'check-circle' : 'copy'} size={15} color={colors.primaryDark} />
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            transactionData.internalId ? (
              <View style={styles.row}>
                <Text style={styles.rowLabel}>ID</Text>
                <Text style={styles.rowMono}>#{String(transactionData.internalId).slice(-8).toUpperCase()}</Text>
              </View>
            ) : null
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
                name={isPending ? 'clock' : 'check-circle'}
                size={15}
                color={isPending ? colors.warning.icon : colors.success}
              />
              <Text style={[styles.rowValue, { color: isPending ? colors.warning.icon : colors.success, fontWeight: '600' }]}>
                {isPending ? 'Confirmando…' : 'Confirmado'}
              </Text>
            </View>
          </View>
          {transactionData.message ? (
            <View style={styles.messageBox}>
              <Text style={styles.messageLabel}>Descripción</Text>
              <Text style={styles.messageText}>{transactionData.message}</Text>
            </View>
          ) : null}
        </View>

        {/* Quiet secondary actions */}
        <View style={styles.secondaryRow}>
          <TouchableOpacity style={styles.secondaryBtn} onPress={handleShareReceipt} accessibilityRole="button" accessibilityLabel="Compartir comprobante">
            <Icon name="share" size={16} color={colors.gray700} />
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
                      const h = (transactionData.transactionHash || '').toString();
                      if (!h) return 'N/D';
                      return h.replace(/(.{10}).+(.{6})/, '$1…$2');
                    })()}
                  </Text>
                </View>
                {(transactionData.merchantAddress || transactionData.recipientAddress) && (
                  <View style={styles.modalRow}>
                    <Text style={styles.modalLabel}>Comercio</Text>
                    <Text style={styles.modalValue} numberOfLines={1}>
                      {(transactionData.merchantAddress || transactionData.recipientAddress || '')
                        .toString().replace(/(.{10}).+(.{6})/, '$1…$2')}
                    </Text>
                  </View>
                )}
              </View>
              <TouchableOpacity
                style={[styles.explorerButton, { backgroundColor: '#8B5CF6' }]}
                onPress={async () => {
                  const txid = transactionData.transactionHash;
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
  // Compact receipt card
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
  },
  rowMono: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
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
  // Quiet secondary actions
  secondaryRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 28,
    marginTop: 20,
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
