import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, Platform, ScrollView, TextInput, Image, Modal, ActivityIndicator } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Feather';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';
import { InlineBanner } from '../components/common/InlineBanner';
import { GET_ACCOUNT_BALANCE } from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import { SafeAreaView } from 'react-native-safe-area-context';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import { useNumberFormat } from '../utils/numberFormatting';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { inviteSendService } from '../services/inviteSendService';

type TokenType = 'cusd' | 'confio';

const tokenConfig = {
  cusd: {
    name: 'cUSD',
    fullName: 'Confío Dollar',
    logo: cUSDLogo,
    color: colors.primary,
    colorDark: colors.primaryDark,
    chipBg: colors.primarySoft,
    chipText: colors.primaryDark,
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
    colorDark: colors.secondaryDark,
    chipBg: colors.violetLight,
    chipText: colors.secondaryDark,
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
  normalizedPhones?: string[];
  algorandAddress?: string;
  userId?: string;
  id?: string; // Some screens pass 'id' instead of 'userId'
};

export const SendToFriendScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  // Safe area handled with SafeAreaView
  const { formatNumber } = useNumberFormat();
  const { userProfile } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);

  const friend: Friend = (route.params as any)?.friend || { name: 'Friend', avatar: 'F', isOnConfio: true, phone: '' };

  // Debug log to check friend data
  const [tokenType, setTokenType] = useState<TokenType>((route.params as any)?.tokenType || 'cusd');
  const config = tokenConfig[tokenType];

  const [amount, setAmount] = useState('');
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
    } catch { }
    setBalanceLoading(true);
    apolloClient.query<{ accountBalance: string }>({
      query: GET_ACCOUNT_BALANCE,
      variables: { tokenType: tok },
      fetchPolicy: 'network-only'
    }).then(res => {
      if (!mounted) return;
      setBalanceSnapshot(res.data?.accountBalance ?? null);
    }).catch(() => { }).finally(() => mounted && setBalanceLoading(false));
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
        }
      } catch (e) {
        // ignore preflight errors; processing screen will fallback
      }
    })();
    return () => { alive = false; };
  }, [amount, tokenType, friend?.userId, friend?.id, friend?.phone, friend?.isOnConfio]);

  const handleSend = async () => {

    // Prevent double-clicks/rapid button presses
    if (isProcessing || navLock.current) {
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

      // For invites, prepare up front and use the invitation_id as the stable
      // retry key. That keeps repeated taps/navigation retries aligned with the
      // server-side idempotency guard.
      let invitePrepared: any | null = null;
      let idempotencyKey: string;
      if (friend.isOnConfio === false && friend.phone) {
        const invitePhone = friend.normalizedPhones?.find(phone => phone.startsWith('+')) || friend.phone;
        const prep = await inviteSendService.prepareInvite(
          invitePhone,
          undefined,
          parseFloat(amount),
          (tokenType.toUpperCase() === 'CUSD' ? 'CUSD' : 'CONFIO'),
          '',
        );
        if (!prep.success || !prep.prepared) {
          throw new Error(prep.error || 'No se pudo preparar la invitación');
        }
        invitePrepared = prep.prepared;
        idempotencyKey = prep.prepared.invitationId;
      } else {
        const recipientIdentifier = friend.userId || friend.id || 'unknown';
        const timestamp = Date.now();
        const amountStr = amount.replace('.', '');
        idempotencyKey = `send_${recipientIdentifier}_${amountStr}_${config.name}_${timestamp}`;
      }

      // Navigate to processing screen with transaction data
      (navigation as any).replace('TransactionProcessing', {
        transactionData: {
          type: 'sent',
          amount: amount,
          currency: config.name,
          recipient: friend.name,
          recipientPhone: friend.normalizedPhones?.find(phone => phone.startsWith('+')) || friend.phone,
          recipientUserId: friend.userId || friend.id, // Pass user ID if available
          action: 'Enviando',
          isOnConfio: friend.isOnConfio,
          // recipientAddress removed - server will determine this
          memo: '', // Empty memo - user can add notes in a future feature
          idempotencyKey: idempotencyKey,
          preparedInvite: invitePrepared,
          prepared: prepared,
          senderName: userProfile?.firstName ? `${userProfile.firstName} ${userProfile.lastName || ''}`.trim() : (userProfile?.username || 'Usuario'),
          sender: userProfile?.firstName || 'Usuario',
          recipientStatusTier: (friend as any).statusTier || null,
          recipientIsReferralVerified: (friend as any).isReferralVerified || false,
        }
      });
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : 'Error al procesar la transacción. Inténtalo de nuevo.';
      setErrorMessage(message);
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
        {/* Header — instrument brand field (emerald cUSD / violet CONFIO):
            gradient + coin ring, padding on headerInner (Yoga insets
            absolute children by parent padding). */}
        <SafeAreaView edges={['top']} style={{ backgroundColor: config.color }}>
          <View style={styles.header}>
            <Svg style={StyleSheet.absoluteFill}>
              <Defs>
                <SvgLinearGradient id={`sendField-${tokenType}`} x1="0" y1="0" x2="0" y2="1">
                  <Stop offset="0" stopColor={config.color} />
                  <Stop offset="1" stopColor={config.colorDark} />
                </SvgLinearGradient>
              </Defs>
              <Rect width="100%" height="100%" fill={`url(#sendField-${tokenType})`} />
              <Circle cx="105%" cy="24%" r="90" stroke={colors.white} strokeWidth="22" strokeOpacity="0.10" fill="none" />
            </Svg>
            <View style={styles.headerInner}>
              <View style={styles.headerContent}>
                <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton} accessibilityRole="button" accessibilityLabel="Volver">
                  <Icon name="arrow-left" size={24} color={colors.white} />
                </TouchableOpacity>
                <Text style={styles.headerTitle}>Enviar</Text>
                <View style={styles.placeholder} />
              </View>
              <View style={styles.headerInfo}>
                <View style={styles.friendAvatarContainer}>
                  <Text style={[styles.friendAvatarText, { color: config.color }]}>{friend.avatar}</Text>
                </View>
                <Text style={styles.headerSubtitle}>{friend.name}</Text>
                {friend.phone && friend.phone !== friend.name && friend.phone.trim() !== '' && (
                  <Text style={styles.headerPhone}>{friend.phone}</Text>
                )}
              </View>
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
                  style={[styles.quickAmountButton, { backgroundColor: config.chipBg }]}
                  accessibilityRole="button"
                  accessibilityLabel={`Enviar ${val} ${config.name}`}
                >
                  {/* $ prefix only for the dollar token — CONFIO isn't dollars */}
                  <Text style={[styles.quickAmountText, { color: config.chipText }]}>
                    {tokenType === 'cusd' ? `$${val}` : val}
                  </Text>
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

          <Button
            title={balanceSnapshot == null ? 'Cargando saldo…' :
              parseFloat(amount || '0') > availableBalance ? 'Saldo insuficiente' :
                `Enviar a ${friend.name}`}
            onPress={handleSend}
            loading={isProcessing}
            disabled={!amount || parseFloat(amount) < config.minSend || parseFloat(amount || '0') > availableBalance}
            accessibilityLabel={`Enviar ${amount || ''} a ${friend.name}`}
            style={{ backgroundColor: config.color }}
          />

          {showError && (
            <InlineBanner
              message={errorMessage}
              variant="error"
              onDismiss={() => setShowError(false)}
              style={{ marginTop: 16, marginBottom: 0 }}
            />
          )}
        </View>

        {/* Supportive footnote — the mission line, no fee marketing */}
        <Text style={styles.supportFootnote}>{supportCopy.transferLine}</Text>
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
    overflow: 'hidden',
    marginBottom: 16,
  },
  headerInner: {
    paddingTop: 8,
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
    padding: 8,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.white,
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
    backgroundColor: colors.white,
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
    color: colors.white,
    marginBottom: 8,
  },
  headerPhone: {
    fontSize: 14,
    color: colors.white,
    opacity: 0.8,
  },
  balanceCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 16,
    marginHorizontal: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  balanceLabel: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  balanceAmount: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  balanceMin: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  formCard: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 24,
    marginHorizontal: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: colors.border,
  },
  inputContainer: {
    marginBottom: 24,
  },
  inputLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 8,
  },
  amountContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutral,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 8,
  },
  amountField: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.text.primary,
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
    color: colors.text.primary,
  },
  supportFootnote: {
    fontSize: 12,
    color: colors.text.secondary,
    textAlign: 'center',
    lineHeight: 18,
    marginHorizontal: 32,
    marginBottom: 8,
  },
  quickAmounts: {
    flexDirection: 'row',
    marginTop: 12,
    gap: 8,
  },
  quickAmountButton: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 16,
  },
  quickAmountText: {
    fontSize: 13,
    fontWeight: '600',
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
    color: colors.text.secondary,
  },
  feeValueFree: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.primaryDark,
  },
  feeValueNote: {
    fontSize: 12,
    color: colors.text.secondary,
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
    color: colors.text.primary,
  },
  feeDivider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: 12,
  },
  feeTotalLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
  },
  feeTotalValue: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.text.primary,
  },
}); 
