import React, { useCallback, useMemo, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, SafeAreaView, Alert, ActivityIndicator } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { useQuery, useMutation } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { GET_PENDING_PAYROLL_ITEMS, GET_PAYROLL_VAULT_BALANCE } from '../apollo/queries';
import { PREPARE_PAYROLL_ITEM_PAYOUT, SUBMIT_PAYROLL_ITEM_PAYOUT } from '../apollo/mutations/payroll';
import algorandService from '../services/algorandService';
import { Buffer } from 'buffer';
import { useAccount } from '../contexts/AccountContext';
import { biometricAuthService } from '../services/biometricAuthService';
import LoadingOverlay from '../components/LoadingOverlay';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollPending'>;

const colors = {
  primary: '#34d399',
  text: '#111827',
  muted: '#6b7280',
  border: '#e5e7eb',
  bg: '#f9fafb',
};

const statusStyles = (status: string) => {
  const key = (status || '').toLowerCase();
  switch (key) {
    case 'pending':
      return { bg: { backgroundColor: '#fff7ed' }, fg: { color: '#9a3412' }, label: 'Pendiente' };
    case 'ready':
    case 'prepared':
      return { bg: { backgroundColor: '#ecfeff' }, fg: { color: '#0e7490' }, label: 'Listo' };
    case 'submitted':
      return { bg: { backgroundColor: '#e0f2fe' }, fg: { color: '#075985' }, label: 'Enviado' };
    case 'confirmed':
    case 'completed':
      return { bg: { backgroundColor: '#ecfdf3' }, fg: { color: '#166534' }, label: 'Completado' };
    case 'failed':
      return { bg: { backgroundColor: '#fef2f2' }, fg: { color: '#b91c1c' }, label: 'Fallido' };
    default:
      return { bg: { backgroundColor: '#f3f4f6' }, fg: { color: '#374151' }, label: status || '—' };
  }
};

export const PayrollPendingScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const { data, loading, refetch } = useQuery(GET_PENDING_PAYROLL_ITEMS, {
    fetchPolicy: 'cache-and-network',
  });
  const { data: vaultData, loading: vaultLoading, error: vaultError, refetch: refetchVault } = useQuery(GET_PAYROLL_VAULT_BALANCE, {
    fetchPolicy: 'cache-and-network',
    skip: false,
  });
  const [preparePayrollItem] = useMutation(PREPARE_PAYROLL_ITEM_PAYOUT);
  const [submitPayrollItem] = useMutation(SUBMIT_PAYROLL_ITEM_PAYOUT);
  const [payingItemId, setPayingItemId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');

  const isBusinessAccount = activeAccount?.type === 'business';
  const isDelegatePersonal = activeAccount?.type !== 'business' && !!activeAccount?.isEmployee;
  const canViewVault = useMemo(() => {
    // Only hide if viewBalance is explicitly false for this account
    if (activeAccount?.employeePermissions && activeAccount.employeePermissions.viewBalance === false) {
      return false;
    }
    return true;
  }, [activeAccount?.employeePermissions]);

  const ensureBusinessContext = useCallback(async () => true, []);

  useFocusEffect(useCallback(() => {
    refetch();
    refetchVault();
  }, [refetch, refetchVault]));

  const items = useMemo(() => data?.pendingPayrollItems || [], [data]);

  const handlePay = async (item: any) => {
    if (payingItemId) return;
    const okCtx = await ensureBusinessContext();
    if (!okCtx) return;

    // Require biometric authentication for approving payroll payment
    const recipientName = item.recipientUser?.firstName || item.recipientUser?.username || 'destinatario';
    const authMessage = `Autoriza pagar ${item.netAmount} cUSD a ${recipientName}`;

    let authenticated = await biometricAuthService.authenticate(authMessage, true, true);
    if (!authenticated) {
      const lockout = biometricAuthService.isLockout();
      if (lockout) {
        Alert.alert(
          'Biometría bloqueada',
          'Desbloquea tu dispositivo con passcode y vuelve a intentar.',
          [{ text: 'OK', style: 'default' }],
        );
        return;
      }

      const shouldRetry = await new Promise<boolean>((resolve) => {
        Alert.alert(
          'Autenticación requerida',
          'Debes autenticarte para aprobar el pago de nómina. Si fallaste varias veces, espera unos segundos y reintenta.',
          [
            { text: 'Cancelar', style: 'cancel', onPress: () => resolve(false) },
            { text: 'Reintentar', onPress: () => resolve(true) }
          ]
        );
      });

      if (shouldRetry) {
        authenticated = await biometricAuthService.authenticate(authMessage, true, true);
        if (!authenticated) {
          Alert.alert('No autenticado', 'No pudimos validar tu identidad. Intenta de nuevo en unos segundos.');
          return;
        }
      } else {
        return;
      }
    }

    try {
      setPayingItemId(item.itemId);
      setIsProcessing(true);
      setProcessingMessage('Preparando pago…');

      const prepRes = await preparePayrollItem({
        variables: { payrollItemId: item.itemId },
      });
      const prep = prepRes.data?.preparePayrollItemPayout;
      if (!prep?.success) {
        const msg = prep?.errors?.[0] || 'No se pudo preparar el pago';
        console.error('Payroll pay: prepare error', msg, prep?.errors);
        throw new Error(msg);
      }
      const sponsorTransaction = prep.sponsorTransaction;

      if (!prep.unsignedTransactionB64) {
        console.error('Payroll pay: missing unsignedTransactionB64');
        throw new Error('Transacción inválida');
      }

      setProcessingMessage('Firmando transacción…');

      const unsignedBytes = Uint8Array.from(Buffer.from(prep.unsignedTransactionB64, 'base64'));
      console.log('Payroll pay: unsigned len', unsignedBytes.length, 'first bytes', Array.from(unsignedBytes.slice(0, 8)));
      const signedBytes = await algorandService.signTransactionBytes(unsignedBytes);
      console.log('Payroll pay: signed len', signedBytes.length, 'first bytes', Array.from(signedBytes.slice(0, 8)));
      let signedB64 = Buffer.from(signedBytes).toString('base64');
      console.log('Payroll pay: signed b64 len', signedB64.length, 'preview', signedB64.slice(0, 12));
      if (signedB64.length % 4 !== 0) {
        signedB64 = signedB64 + '='.repeat((4 - (signedB64.length % 4)) % 4);
      }

      setProcessingMessage('Enviando a blockchain…');

      const submitRes = await submitPayrollItem({
        variables: {
          payrollItemId: item.itemId,
          signedTransaction: signedB64,
          sponsorSignature: sponsorTransaction
        },
      });
      const submit = submitRes.data?.submitPayrollItemPayout;
      if (!submit?.success) {
        const msg = submit?.errors?.[0] || 'No se pudo enviar la transacción';
        console.error('Payroll pay: submit error', msg, submit?.errors);
        throw new Error(msg);
      }

      setIsProcessing(false);
      Alert.alert('Pago enviado', 'La transacción de nómina fue enviada.');
      refetch();
    } catch (e: any) {
      console.error('Payroll pay: unexpected error', e);
      setIsProcessing(false);
      Alert.alert('No se pudo pagar', e?.message || 'Error desconocido');
    } finally {
      setPayingItemId(null);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Icon name="chevron-left" size={24} color={colors.text} />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Nómina pendiente</Text>
        <TouchableOpacity
          style={styles.historyButton}
          onPress={() => navigation.navigate('PayrollRunsHistory' as never)}
        >
          <Text style={styles.historyText}>Historial</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.balanceCard}>
        <View>
          <Text style={styles.balanceLabel}>Saldo en bóveda de nómina</Text>
          {vaultError ? <Text style={styles.balanceError}>No se pudo cargar el saldo</Text> : null}
          <Text style={styles.balanceValue}>
            {vaultLoading
              ? '...'
              : canViewVault
                ? `${(vaultData?.payrollVaultBalance ?? 0).toFixed(2)} cUSD`
                : '••••'}
          </Text>
          <Text style={styles.balanceHint}>
            {isBusinessAccount
              ? 'Agrega fondos si ves rechazos por saldo insuficiente.'
              : canViewVault ? 'Bóveda de tu negocio.' : 'No puedes ver el saldo de bóveda.'}
          </Text>
        </View>
        {isBusinessAccount ? (
          <TouchableOpacity style={styles.topUpButton} onPress={() => navigation.navigate('PayrollTopUp' as never)}>
            <Icon name="arrow-up-right" size={16} color={colors.primary} />
            <Text style={styles.topUpText}>Agregar fondos</Text>
          </TouchableOpacity>
        ) : null}
      </View>

      <FlatList
        data={items}
        keyExtractor={(item: any) => item.itemId}
        refreshing={loading}
        onRefresh={() => {
          refetch();
          refetchVault();
        }}
        contentContainerStyle={styles.listContent}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Icon name="inbox" size={32} color={colors.muted} />
            <Text style={styles.emptyTitle}>Sin pagos pendientes</Text>
            <Text style={styles.emptySubtitle}>Cuando una nómina esté lista para ti, aparecerá aquí.</Text>
          </View>
        }
        renderItem={({ item }) => {
          const badge = statusStyles(item.status);
          return (
            <TouchableOpacity
              style={[styles.card, payingItemId === item.itemId && styles.cardDisabled]}
              onPress={() => handlePay(item)}
              disabled={!!payingItemId}
            >
              <View style={styles.row}>
                <Text style={styles.business}>{item.run?.business?.name || 'Negocio'}</Text>
                <View style={[styles.statusBadge, badge.bg]}>
                  <Text style={[styles.statusText, badge.fg]}>{badge.label}</Text>
                </View>
              </View>
              <Text style={styles.amount}>{item.netAmount} {item.run?.tokenType || 'cUSD'}</Text>
              <Text style={styles.subtext}>Recibe: {item.recipientUser?.firstName} {item.recipientUser?.lastName}</Text>
              <Text style={styles.subtext}>Bruto: {item.grossAmount} · Comisión: {item.feeAmount}</Text>
              <View style={styles.ctaRow}>
                {payingItemId === item.itemId ? (
                  <View style={styles.payButtonDisabled}>
                    <ActivityIndicator size="small" color="#fff" />
                    <Text style={styles.payText}>Enviando...</Text>
                  </View>
                ) : (
                  <View style={styles.payButton}>
                    <Icon name="send" size={14} color="#fff" />
                    <Text style={styles.payText}>Pagar ahora</Text>
                  </View>
                )}
              </View>
            </TouchableOpacity>
          );
        }}
      />

      <LoadingOverlay visible={isProcessing} message={processingMessage} />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  backButton: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  historyButton: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 10,
    backgroundColor: '#f3f4f6',
  },
  historyText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.text,
  },
  balanceCard: {
    marginHorizontal: 16,
    marginTop: 10,
    marginBottom: 8,
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    backgroundColor: '#f9fafb',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 10,
  },
  balanceLabel: { fontSize: 12, color: colors.muted, marginBottom: 4 },
  balanceValue: { fontSize: 18, fontWeight: '700', color: colors.text },
  balanceHint: { fontSize: 12, color: colors.muted, marginTop: 2 },
  balanceError: { fontSize: 12, color: '#b91c1c', marginTop: 2 },
  topUpButton: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    alignSelf: 'flex-start',
  },
  topUpText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.text,
  },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 18,
    color: colors.text,
    fontWeight: '600',
  },
  listContent: {
    padding: 16,
  },
  card: {
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#e2e8f0',
    borderLeftWidth: 4,
    borderLeftColor: colors.primary,
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
    elevation: 2,
  },
  cardDisabled: { opacity: 0.7 },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  business: {
    fontSize: 14,
    color: colors.text,
    fontWeight: '600',
  },
  status: {
    fontSize: 12,
    color: colors.muted,
    textTransform: 'capitalize',
  },
  amount: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text,
    marginBottom: 4,
  },
  subtext: {
    fontSize: 12,
    color: colors.muted,
  },
  ctaRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 10,
  },
  payButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: colors.primary,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
  },
  payButtonDisabled: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#6ee7b7',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
  },
  payText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  statusBadge: {
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'capitalize',
  },
  emptyState: {
    alignItems: 'center',
    marginTop: 40,
    paddingHorizontal: 24,
  },
  emptyTitle: {
    marginTop: 8,
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },
  emptySubtitle: {
    marginTop: 4,
    fontSize: 13,
    color: colors.muted,
    textAlign: 'center',
  },
});

export default PayrollPendingScreen;
