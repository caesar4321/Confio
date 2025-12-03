import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  SafeAreaView,
  TextInput,
  Alert,
  ActivityIndicator,
  TouchableWithoutFeedback,
  Keyboard,
  ScrollView,
  Image,
  RefreshControl,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useNavigation } from '@react-navigation/native';
import { useMutation, useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { GET_ACCOUNT_BALANCE, GET_PAYROLL_VAULT_BALANCE } from '../apollo/queries';
import {
  PREPARE_PAYROLL_VAULT_FUNDING,
  SUBMIT_PAYROLL_VAULT_FUNDING,
  PREPARE_PAYROLL_VAULT_WITHDRAWAL,
  SUBMIT_PAYROLL_VAULT_WITHDRAWAL,
} from '../apollo/mutations/payroll';
import algorandService from '../services/algorandService';
import { Buffer } from 'buffer';
import { useAccount } from '../contexts/AccountContext';
import { biometricAuthService } from '../services/biometricAuthService';
import LoadingOverlay from '../components/LoadingOverlay';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollTopUp'>;

const colors = {
  primary: '#34d399',
  text: '#111827',
  muted: '#6b7280',
  border: '#e5e7eb',
  bg: '#f9fafb',
};

const PayrollTopUpScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const isBusinessAccount = activeAccount?.type === 'business';
  const [amount, setAmount] = useState('');
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [processing, setProcessing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');

  const { data: vaultData, loading: vaultLoading, refetch: refetchVault } = useQuery(GET_PAYROLL_VAULT_BALANCE, {
    fetchPolicy: 'cache-and-network',
    skip: !isBusinessAccount,
  });
  const { data: balanceData, loading: balanceLoading, refetch: refetchBalance } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'cUSD' },
    fetchPolicy: 'cache-and-network',
    skip: !isBusinessAccount,
  });
  const [prepareFunding] = useMutation(PREPARE_PAYROLL_VAULT_FUNDING);
  const [submitFunding] = useMutation(SUBMIT_PAYROLL_VAULT_FUNDING);
  const [prepareWithdraw] = useMutation(PREPARE_PAYROLL_VAULT_WITHDRAWAL);
  const [submitWithdraw] = useMutation(SUBMIT_PAYROLL_VAULT_WITHDRAWAL);

  const availableBalance = useMemo(() => parseFloat(balanceData?.accountBalance ?? '0'), [balanceData]);
  const vaultBalance = useMemo(() => vaultData?.payrollVaultBalance ?? 0, [vaultData]);
  const parseMinBalanceError = (msg?: string) => {
    if (!msg) return null;
    if (!msg.toLowerCase().includes('min')) return null;
    const match = msg.match(/balance\s+(\d+)\s+below\s+min\s+(\d+)/i);
    if (match) {
      const current = parseInt(match[1], 10);
      const required = parseInt(match[2], 10);
      const deficit = Math.max(required - current, 0);
      const toAlgo = (n: number) => (n / 1_000_000).toFixed(3);
      return `Tu cuenta de negocio no tiene suficiente ALGO para la reserva mínima en Algorand. Necesitas ~${toAlgo(required)} ALGO, tienes ~${toAlgo(current)} ALGO. Agrega al menos ${toAlgo(deficit)} ALGO y reintenta.`;
    }
    return 'Saldo ALGO insuficiente para la reserva mínima en Algorand. Agrega ALGO y reintenta.';
  };

  const handleSubmit = async () => {
    if (!isBusinessAccount) {
      Alert.alert('Solo negocios', 'Cambia a una cuenta de negocio para fondear la bóveda de nómina.');
      return;
    }
    if (processing) return;
    const parsed = parseFloat((amount || '').replace(',', '.'));
    if (!isFinite(parsed) || parsed <= 0) {
      Alert.alert('Monto inválido', 'Ingresa un monto mayor a 0.');
      return;
    }
    if (availableBalance && parsed > availableBalance) {
      Alert.alert('Saldo insuficiente', 'El monto supera el saldo disponible de la cuenta de negocio.');
      return;
    }

    // Require biometric authentication for funding the vault
    const authMessage = `Autoriza fondear ${parsed.toFixed(2)} cUSD a la bóveda`;

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
          'Debes autenticarte para fondear la bóveda de nómina. Si fallaste varias veces, espera unos segundos y reintenta.',
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
      setProcessing(true);
      setProcessingMessage('Preparando transacción…');

      const prepRes = await prepareFunding({ variables: { amount: parsed } });
      const prep = prepRes.data?.preparePayrollVaultFunding;
      if (!prep?.success || !prep?.unsignedTransactions?.length) {
        const msg = prep?.errors?.[0] || 'No se pudo preparar la transacción.';
        throw new Error(msg);
      }

      setProcessingMessage('Firmando transacción…');

      // With sponsored transactions, we only sign the business AXFER transaction
      // The sponsor has already signed the app call transaction
      const signedTxns: string[] = [];
      for (const utx of prep.unsignedTransactions) {
        const bytes = Uint8Array.from(Buffer.from(utx, 'base64'));
        const signedBytes = await algorandService.signTransactionBytes(bytes);
        let b64 = Buffer.from(signedBytes).toString('base64');
        if (b64.length % 4 !== 0) {
          b64 = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
        }
        signedTxns.push(b64);
      }

      setProcessingMessage('Enviando a blockchain…');

      // Submit with signed business transaction + already-signed sponsor app call
      const submitRes = await submitFunding({
        variables: {
          signedTransactions: signedTxns,
          sponsorAppCall: prep.sponsorAppCall,
        }
      });
      const submit = submitRes.data?.submitPayrollVaultFunding;
      if (!submit?.success) {
        const msg = submit?.errors?.[0] || 'No se pudo enviar la transacción.';
        throw new Error(msg);
      }

      setProcessingMessage('Confirmando transacción…');
      await Promise.all([refetchVault(), refetchBalance()]);

      setProcessing(false);

      Alert.alert('Fondos enviados', 'Agregamos los fondos a la bóveda de nómina.', [
        { text: 'OK', onPress: () => navigation.goBack() },
      ]);
    } catch (e: any) {
      console.error('Payroll top-up error', e);
      setProcessing(false);
      const gqlMsg = Array.isArray(e?.graphQLErrors) && e.graphQLErrors[0]?.message;
      const friendly = gqlMsg && gqlMsg.includes('preparePayrollVaultFunding')
        ? 'Actualiza/reinicia el backend con las nuevas mutaciones de fondeo de nómina.'
        : parseMinBalanceError(e?.message || gqlMsg);
      Alert.alert('No se pudo fondear', friendly || e?.message || 'Error desconocido');
    }
  };

  const handleWithdraw = async () => {
    if (!isBusinessAccount) {
      Alert.alert('Solo negocios', 'Cambia a una cuenta de negocio para retirar de la bóveda.');
      return;
    }
    if (processing) return;
    const parsed = parseFloat((withdrawAmount || '').replace(',', '.'));
    if (!isFinite(parsed) || parsed <= 0) {
      Alert.alert('Monto inválido', 'Ingresa un monto mayor a 0.');
      return;
    }
    if (vaultBalance && parsed > vaultBalance) {
      Alert.alert('Saldo insuficiente', 'El monto supera el saldo en la bóveda.');
      return;
    }

    const authMessage = `Autoriza retirar ${parsed.toFixed(2)} cUSD de la bóveda`;
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
          'Debes autenticarte para retirar de la bóveda. Si fallaste varias veces, espera unos segundos y reintenta.',
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
      setProcessing(true);
      setProcessingMessage('Preparando retiro…');
      const prepRes = await prepareWithdraw({
        variables: {
          amount: parsed,
        }
      });
      const prep = prepRes.data?.preparePayrollVaultWithdrawal;
      if (!prep?.success || !prep?.transaction) {
        const msg = prep?.errors?.[0] || 'No se pudo preparar el retiro.';
        throw new Error(msg);
      }

      setProcessingMessage('Firmando retiro…');
      const bytes = Uint8Array.from(Buffer.from(prep.transaction, 'base64'));
      const signedBytes = await algorandService.signTransactionBytes(bytes);
      let stxB64 = Buffer.from(signedBytes).toString('base64');
      if (stxB64.length % 4 !== 0) stxB64 = stxB64 + '='.repeat((4 - (stxB64.length % 4)) % 4);

      setProcessingMessage('Enviando a blockchain…');
      const submitRes = await submitWithdraw({ variables: { signedTransaction: stxB64 } });
      const submit = submitRes.data?.submitPayrollVaultWithdrawal;
      if (!submit?.success) {
        const msg = submit?.errors?.[0] || 'No se pudo enviar el retiro.';
        throw new Error(msg);
      }

      setProcessingMessage('Confirmando transacción…');
      await Promise.all([refetchVault(), refetchBalance()]);
      setProcessing(false);
      setWithdrawAmount('');
      Alert.alert('Retiro enviado', 'Retiramos fondos de la bóveda de nómina.', [
        { text: 'OK', onPress: () => navigation.goBack() },
      ]);
    } catch (e: any) {
      console.error('Payroll withdraw error', e);
      setProcessing(false);
      const gqlMsg = Array.isArray(e?.graphQLErrors) && e.graphQLErrors[0]?.message;
      Alert.alert('No se pudo retirar', gqlMsg || e?.message || 'Error desconocido');
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={async () => {
                setRefreshing(true);
                try {
                  await Promise.all([refetchVault(), refetchBalance()]);
                } finally {
                  setRefreshing(false);
                }
              }}
            />
          }
        >
          <View style={styles.header}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
              <Icon name="chevron-left" size={24} color={colors.text} />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Fondear nómina</Text>
            <View style={{ width: 32 }} />
          </View>

          <View style={styles.card}>
            <Text style={styles.cardLabel}>Saldo en bóveda</Text>
            <View style={styles.rowBetween}>
              <Text style={styles.balanceValue}>{vaultLoading ? '...' : `${vaultBalance?.toFixed?.(2) || '0.00'} cUSD`}</Text>
            </View>
            <Text style={styles.cardHint}>Los fondos se guardan en el contrato de nómina y se usan para pagar a tus empleados.</Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.cardLabel}>Saldo disponible en la cuenta de negocio</Text>
            <Text style={styles.balanceValue}>{balanceLoading ? '...' : `${availableBalance.toFixed(2)} cUSD`}</Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.cardLabel}>Monto a fondear</Text>
            <View style={styles.inputRow}>
              <Image source={require('../assets/png/cUSD.png')} style={styles.tokenIcon} />
              <Text style={styles.currency}>cUSD</Text>
              <TextInput
                style={styles.input}
                keyboardType="decimal-pad"
                placeholder="0.00"
                value={amount}
                onChangeText={setAmount}
                returnKeyType="done"
              />
            </View>
            <Text style={styles.cardHint}>Moveremos este monto desde la cuenta de negocio hacia la bóveda de nómina.</Text>
          </View>

          <TouchableOpacity
            style={[styles.primaryButton, (!isBusinessAccount || processing) && styles.primaryButtonDisabled]}
            onPress={handleSubmit}
            disabled={processing || !isBusinessAccount}
            activeOpacity={0.9}
          >
            {processing ? <ActivityIndicator color="#fff" /> : <Icon name="arrow-up-right" size={16} color="#fff" />}
            <Text style={styles.primaryButtonText}>{processing ? 'Enviando...' : 'Agregar a bóveda'}</Text>
          </TouchableOpacity>

          {!isBusinessAccount ? (
            <View style={styles.infoBox}>
              <Icon name="alert-triangle" size={16} color="#92400e" />
              <Text style={styles.infoText}>Cambia a tu cuenta de negocio para fondear la bóveda de nómina.</Text>
            </View>
          ) : null}

          <View style={styles.card}>
            <Text style={styles.cardLabel}>Retirar de la bóveda</Text>
            <Text style={styles.cardHint}>Recupera fondos de la bóveda de nómina hacia tu cuenta o a otra dirección.</Text>
            <View style={[styles.inputRow, { marginTop: 10 }]}>
              <Image source={require('../assets/png/cUSD.png')} style={styles.tokenIcon} />
              <Text style={styles.currency}>cUSD</Text>
              <TextInput
                style={styles.input}
                keyboardType="decimal-pad"
                placeholder="0.00"
                value={withdrawAmount}
                onChangeText={setWithdrawAmount}
                returnKeyType="done"
              />
            </View>
            <TouchableOpacity
              style={[styles.secondaryButton, (!isBusinessAccount || processing) && styles.primaryButtonDisabled]}
              onPress={handleWithdraw}
              disabled={processing || !isBusinessAccount}
              activeOpacity={0.9}
            >
              {processing ? <ActivityIndicator color="#111" /> : <Icon name="arrow-down-left" size={16} color="#111" />}
              <Text style={styles.secondaryButtonText}>{processing ? 'Procesando...' : 'Retirar de bóveda'}</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </TouchableWithoutFeedback>

      <LoadingOverlay visible={processing} message={processingMessage} />
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
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontSize: 18,
    color: colors.text,
    fontWeight: '600',
  },
  card: {
    marginHorizontal: 16,
    marginTop: 12,
    padding: 14,
    borderRadius: 12,
    backgroundColor: colors.bg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  scrollContent: {
    paddingBottom: 32,
  },
  cardLabel: {
    fontSize: 12,
    color: colors.muted,
    marginBottom: 6,
  },
  balanceValue: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
  },
  cardHint: {
    marginTop: 6,
    color: colors.muted,
    fontSize: 12,
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  refreshButton: {
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: '#fff',
  },
  tokenIcon: { width: 22, height: 22, resizeMode: 'contain', marginRight: 8 },
  currency: {
    fontWeight: '700',
    color: colors.text,
    marginRight: 10,
  },
  input: {
    flex: 1,
    fontSize: 18,
    color: colors.text,
  },
  primaryButton: {
    marginHorizontal: 16,
    marginTop: 18,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: colors.primary,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  primaryButtonDisabled: { opacity: 0.6 },
  primaryButtonText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 16,
  },
  infoBox: {
    marginHorizontal: 16,
    marginTop: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 12,
    borderRadius: 10,
    backgroundColor: '#fff7ed',
    borderWidth: 1,
    borderColor: '#fed7aa',
  },
  infoText: {
    flex: 1,
    color: '#92400e',
    fontSize: 13,
  },
  secondaryButton: {
    marginTop: 12,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#e5e7eb',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  secondaryButtonText: {
    color: '#111827',
    fontWeight: '700',
    fontSize: 16,
  },
});

export default PayrollTopUpScreen;
