import React, { useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
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
import { usePayrollDelegates, payrollInstrument } from '../hooks/usePayrollDelegates';
import { biometricAuthService } from '../services/biometricAuthService';
import LoadingOverlay from '../components/LoadingOverlay';
import { colors } from '../config/theme';
import { Button } from '../components/common/Button';
import { Header } from '../navigation/Header';
import { InlineBanner } from '../components/common/InlineBanner';
import { BrandFieldBackground } from '../components/common/BrandFieldBackground';

type NavigationProp = NativeStackNavigationProp<MainStackParamList, 'PayrollTopUp'>;

const PayrollTopUpScreen = () => {
  const navigation = useNavigation<NavigationProp>();
  const { activeAccount } = useAccount();
  const isBusinessAccount = activeAccount?.type === 'business';
  const [amount, setAmount] = useState('');
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [processing, setProcessing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState('');
  const [banner, setBanner] = useState<{ message: string; variant: 'error' | 'success' } | null>(null);

  const { status: railStatus, rail, executionRail, refetch: refetchRail } = usePayrollDelegates();
  // The vault hero describes where the money IS; every funding control
  // describes where a top-up will GO. Using one rail for both showed the
  // cUSD+ balance and logo while the dark-flag fall-through actually funded
  // the Algorand vault.
  // WHICH POOL this screen is operating on. A business can hold escrow in
  // BOTH (the normal state after an eligibility flip), and the two are not
  // fungible — one operation moves one pool. So the pool is SELECTED state,
  // seeded from the server's default, and every balance check below runs
  // against the selected one. Deriving it server-side hid the entire USDT
  // pool from anyone still holding a single cUSD+ share (audit 2026-08-02).
  type PayrollPool = 'CUSD_PLUS' | 'CUSD_BSC' | 'USDT';
  const [pool, setPool] = useState<PayrollPool | null>(null);
  const defaultPool = (railStatus?.fundingToken as PayrollPool | null) ?? null;
  const activePool = pool ?? defaultPool;
  const instrument = payrollInstrument(activePool);
  const vaultInstrument = instrument;
  const escrowOf = (p: typeof activePool) =>
    p === 'CUSD_PLUS' ? railStatus?.escrowCusdPlusUsd ?? null
      : p === 'CUSD_BSC' ? railStatus?.escrowCusdUsd ?? null
        : railStatus?.escrowUsdtUsd ?? null;
  const fundableOf = (p: typeof activePool) =>
    p === 'CUSD_PLUS' ? railStatus?.fundableCusdPlusUsd ?? null
      : p === 'CUSD_BSC' ? railStatus?.fundableCusdUsd ?? null
        : railStatus?.fundableUsdtUsd ?? null;
  // Offer the choice only when BOTH pools actually hold something — a single
  // door is the common case and a picker over one option is pure friction.
  const selectablePools: PayrollPool[] = (['CUSD_PLUS', 'CUSD_BSC', 'USDT'] as const)
    .filter((p) => p === defaultPool || (escrowOf(p) ?? 0) > 0);
  const showPoolPicker = selectablePools.length > 1;
  const { data: vaultData, loading: vaultLoading, refetch: refetchVault } = useQuery(GET_PAYROLL_VAULT_BALANCE, {
    fetchPolicy: 'cache-and-network',
    skip: !isBusinessAccount,
  });
  // Legacy rail only: on BSC a top-up spends the business's cUSD+ position,
  // and gating it on the Algorand cUSD balance refused funds the business
  // actually had (or waved through funds it didn't).
  const { data: balanceData, loading: balanceLoading, refetch: refetchBalance } = useQuery(GET_ACCOUNT_BALANCE, {
    variables: { tokenType: 'cUSD' },
    fetchPolicy: 'cache-and-network',
    skip: !isBusinessAccount || executionRail === 'bsc',
  });
  const [prepareFunding] = useMutation(PREPARE_PAYROLL_VAULT_FUNDING);
  const [submitFunding] = useMutation(SUBMIT_PAYROLL_VAULT_FUNDING);
  const [prepareWithdraw] = useMutation(PREPARE_PAYROLL_VAULT_WITHDRAWAL);
  const [submitWithdraw] = useMutation(SUBMIT_PAYROLL_VAULT_WITHDRAWAL);

  // What a top-up can draw on: the SELECTED pool's wallet balance, falling
  // back to the aggregate for a server that predates the split.
  const availableBalance = useMemo(() => {
    const perPool = fundableOf(activePool);
    if (perPool !== null && perPool !== undefined) return perPool;
    if (railStatus?.fundableBalanceUsd !== null && railStatus?.fundableBalanceUsd !== undefined) {
      return railStatus.fundableBalanceUsd;
    }
    const legacy = parseFloat(balanceData?.accountBalance ?? '');
    return Number.isFinite(legacy) ? legacy : null;
  }, [railStatus, activePool, balanceData]);
  // null = unknown, rendered "—". Never 0: see PayrollHomeScreen.
  //
  // WITHDRAWALS validate against this, so it is the SELECTED pool, not the
  // sum of both: one operation drains one pool, and validating against a sum
  // let a business ask for more than the chosen pool held — the server then
  // answered insufficient_escrow, which the fall-through below used to read
  // as "withdraw from Algorand instead" (audit 2026-08-02).
  const vaultBalance = useMemo(() => {
    const perPool = escrowOf(activePool);
    if (perPool !== null && perPool !== undefined) return perPool;
    if (railStatus) return railStatus.vaultBalanceUsd;
    const raw = vaultData?.payrollVaultBalance;
    return raw === null || raw === undefined ? null : Number(raw);
  }, [railStatus, activePool, vaultData]);
  // The hero still shows everything parked — that IS the payroll float.
  const totalVaultBalance = useMemo(() => {
    if (railStatus) return railStatus.vaultBalanceUsd;
    const raw = vaultData?.payrollVaultBalance;
    return raw === null || raw === undefined ? null : Number(raw);
  }, [railStatus, vaultData]);
  // One refresh for both rails. refetchBalance is deliberately guarded: on
  // BSC its query is skipped, and refetching a skipped query is not something
  // a balance refresh should be able to throw on.
  const refreshBalances = async () => {
    await Promise.all([
      refetchVault(),
      executionRail === 'bsc' ? Promise.resolve() : refetchBalance().catch(() => undefined),
      refetchRail(),
    ]);
  };

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
      setBanner({ variant: 'error', message: 'Ingresa un monto mayor a 0.' });
      return;
    }
    // Explicitly not gating when the balance is unknown: the server checks
    // the real balance before it will build the batch, and refusing here on a
    // number we do not have would block a business that can afford it.
    if (availableBalance !== null && parsed > availableBalance) {
      setBanner({ variant: 'error', message: 'El monto supera el saldo disponible de la cuenta de negocio.' });
      return;
    }

    // Require biometric authentication for funding the vault
    const authMessage = `Autoriza fondear $${parsed.toFixed(2)} a la bóveda`;

    let authenticated = await biometricAuthService.authenticate(authMessage, true, true);
    if (!authenticated) {
      const lockout = biometricAuthService.isLockout();
      if (lockout) {
        Alert.alert(
          'Biometría bloqueada',
          'Desbloquea tu dispositivo con passcode y vuelve a intentar.',
          [{ text: 'Entendido', style: 'default' }],
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

      // BSC rail first (W3): fund = approve+deposit of cUSD+ shares into
      // ConfioPayrollVault, signed by the business EOA as one sponsored
      // batch. Dark flag falls through to the legacy Algorand vault.
      {
        const { runBscPayrollAdmin, bscPayrollErrorMessage } = await import('../services/bscPayroll');
        try {
          setProcessingMessage('Firmando transacción…');
          await runBscPayrollAdmin({
            action: 'fund', amountUsd: String(parsed),
            tokenType: activePool ?? undefined,
          });
          setProcessingMessage('Confirmando transacción…');
          await refreshBalances();
          setProcessing(false);
          Alert.alert('Fondos enviados', 'Agregamos los fondos a la bóveda de nómina.', [
            { text: 'Entendido', onPress: () => navigation.goBack() },
          ]);
          return;
        } catch (bscErr: any) {
          const code = bscErr?.message || '';
          const fallThrough = code === 'bsc_payroll_disabled'
            || code === 'payroll_vault_not_configured'
            || code === 'vault_not_configured';
          // NOT sponsored_rail_unavailable: the server already confirmed this
          // business is on BSC, so a relay outage means "retry", not "put the
          // money in the Algorand vault instead".
          if (!fallThrough) {
            throw new Error(bscPayrollErrorMessage(code));
          }
        }
      }

      const prepRes = await prepareFunding({ variables: { amount: parsed } });
      const prep = prepRes.data?.preparePayrollVaultFunding;
      if (!prep?.success || !prep?.unsignedTransactions?.length) {
        const msg = prep?.errors?.[0] || 'No se pudo preparar la transacción.';
        throw new Error(msg);
      }

      setProcessingMessage('Firmando transacción…');

      // Ensure wallet is initialized before signing (Critical for cold starts)
      try {
        const { oauthStorage } = await import('../services/oauthStorageService');
        const { secureDeterministicWallet } = await import('../services/secureDeterministicWallet');
        const oauthData = await oauthStorage.getOAuthSubject();

        if (oauthData && oauthData.subject && oauthData.provider) {
          const { GOOGLE_CLIENT_IDS } = await import('../config/env');
          const GOOGLE_WEB_CLIENT_ID = GOOGLE_CLIENT_IDS.production.web;
          const iss = oauthData.provider === 'google' ? 'https://accounts.google.com' : 'https://appleid.apple.com';
          const aud = oauthData.provider === 'google' ? GOOGLE_WEB_CLIENT_ID : 'com.confio.app';

          await secureDeterministicWallet.createOrRestoreWallet(
            iss,
            oauthData.subject,
            aud,
            oauthData.provider,
            activeAccount?.type || 'business',
            activeAccount?.index || 0,
            activeAccount?.id?.startsWith('business_') ? (activeAccount.id.split('_')[1] || undefined) : undefined
          );
        }
      } catch (err) {
      }

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
      await refreshBalances();

      setProcessing(false);

      Alert.alert('Fondos enviados', 'Agregamos los fondos a la bóveda de nómina.', [
        { text: 'Entendido', onPress: () => navigation.goBack() },
      ]);
    } catch (e: any) {
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
      setBanner({ variant: 'error', message: 'Ingresa un monto mayor a 0.' });
      return;
    }
    if (vaultBalance !== null && parsed > vaultBalance) {
      Alert.alert('Saldo insuficiente', 'El monto supera el saldo en la bóveda.');
      return;
    }

    const authMessage = `Autoriza retirar $${parsed.toFixed(2)} de la bóveda`;
    let authenticated = await biometricAuthService.authenticate(authMessage, true, true);
    if (!authenticated) {
      const lockout = biometricAuthService.isLockout();
      if (lockout) {
        Alert.alert(
          'Biometría bloqueada',
          'Desbloquea tu dispositivo con passcode y vuelve a intentar.',
          [{ text: 'Entendido', style: 'default' }],
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

      // BSC rail first (W3). Withdraw ignores the payroll kill switch
      // server-side (exits never gated) — only an unconfigured vault
      // falls through to Algorand.
      {
        const { runBscPayrollAdmin, bscPayrollErrorMessage } = await import('../services/bscPayroll');
        try {
          setProcessingMessage('Firmando retiro…');
          await runBscPayrollAdmin({
            action: 'withdraw', amountUsd: String(parsed),
            tokenType: activePool ?? undefined,
          });
          setProcessingMessage('Confirmando transacción…');
          await refreshBalances();
          setProcessing(false);
          setWithdrawAmount('');
          Alert.alert('Retiro enviado', 'Retiramos fondos de la bóveda de nómina.', [
            { text: 'Entendido', onPress: () => navigation.goBack() },
          ]);
          return;
        } catch (bscErr: any) {
          const code = bscErr?.message || '';
          // insufficient_escrow is NO LONGER a fall-through (audit
          // 2026-08-02, [P1]). It used to mean "nothing parked on BSC, so the
          // money must be in the legacy vault" — true only while there was
          // ONE BSC pool. With two, it also fires when the business picked
          // the pool that happens to be short, and withdrawing from Algorand
          // then moves a different pot than the one on screen. A short pool
          // is an error to show, not a reason to drain another vault.
          const fallThrough = code === 'payroll_vault_not_configured'
            || code === 'vault_not_configured';
          if (!fallThrough) {
            throw new Error(bscPayrollErrorMessage(code));
          }
        }
      }

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
      await refreshBalances();
      setProcessing(false);
      setWithdrawAmount('');
      Alert.alert('Retiro enviado', 'Retiramos fondos de la bóveda de nómina.', [
        { text: 'Entendido', onPress: () => navigation.goBack() },
      ]);
    } catch (e: any) {
      setProcessing(false);
      const gqlMsg = Array.isArray(e?.graphQLErrors) && e.graphQLErrors[0]?.message;
      Alert.alert('No se pudo retirar', gqlMsg || e?.message || 'Error desconocido');
    }
  };

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation as any}
        title="Fondear nómina"
        backgroundColor={colors.white}
        showBackButton
      />
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
                  await refreshBalances();
                } finally {
                  setRefreshing(false);
                }
              }}
            />
          }
        >

          {banner && (
            <InlineBanner
              message={banner.message}
              variant={banner.variant}
              onDismiss={() => setBanner(null)}
              style={{ marginHorizontal: 16, marginTop: 12, marginBottom: 0 }}
            />
          )}

          {/* Vault hero — same brand-field card as the payroll hub */}
          <View style={styles.vaultHero}>
            <BrandFieldBackground id="payrollTopUpField" ringCy="25%" ringR={70} ringWidth={18} />
            <View style={styles.vaultHeroInner}>
              <Text style={styles.vaultHeroLabel}>BÓVEDA DE NÓMINA</Text>
              {/* The hero is the WHOLE payroll float, both pools — that is
                  what the business has parked. The controls below operate on
                  one pool at a time, and say which. */}
              <Text style={styles.vaultHeroBalance}>
                {vaultLoading && !railStatus
                  ? '...'
                  : totalVaultBalance === null ? '—' : `$${totalVaultBalance.toFixed(2)}`}
              </Text>
              {vaultInstrument.known ? (
                <View style={styles.instrumentRow}>
                  <Image
                    source={vaultInstrument.isPlus
                      ? require('../assets/png/cUSDPlus.png')
                      : require('../assets/png/cUSD.png')}
                    style={styles.instrumentIcon}
                  />
                  <Text style={styles.instrumentLabel}>{vaultInstrument.name}</Text>
                </View>
              ) : null}
              {/* Split shown ONLY when both pools hold money — otherwise the
                  hero total already IS the one pool. */}
              {showPoolPicker ? (
                <Text style={styles.vaultHeroHint}>
                  {`Confío Dollar+ $${(railStatus?.escrowCusdPlusUsd ?? 0).toFixed(2)}`}
                  {'  ·  '}
                  {`Confío Dollar $${(railStatus?.escrowUsdtUsd ?? 0).toFixed(2)}`}
                </Text>
              ) : null}
              <Text style={styles.vaultHeroHint}>
                Disponible en tu cuenta de negocio: {balanceLoading && !railStatus
                  ? '...'
                  : availableBalance === null ? '—' : `$${availableBalance.toFixed(2)}`}
              </Text>
            </View>
          </View>

          {/* Which pool the controls below act on. Only rendered when the
              business genuinely holds both — one door needs no picker. */}
          {showPoolPicker ? (
            <View style={styles.card}>
              <Text style={styles.cardLabel}>¿Con cuál saldo?</Text>
              <View style={styles.poolRow}>
                {selectablePools.map((p) => {
                  const selected = activePool === p;
                  const label = payrollInstrument(p).name;
                  return (
                    <TouchableOpacity
                      key={p}
                      style={[styles.poolChip, selected && styles.poolChipSelected]}
                      onPress={() => { setPool(p); setAmount(''); setWithdrawAmount(''); }}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}
                      accessibilityLabel={`Usar ${label}`}
                    >
                      <Text style={[styles.poolChipText, selected && styles.poolChipTextSelected]}>
                        {label}
                      </Text>
                      <Text style={[styles.poolChipAmount, selected && styles.poolChipTextSelected]}>
                        {`$${(escrowOf(p) ?? 0).toFixed(2)}`}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
              <Text style={styles.cardHint}>
                Los dos saldos son dinero distinto: cada operación mueve uno solo.
              </Text>
            </View>
          ) : null}

          <View style={styles.card}>
            <Text style={styles.cardLabel}>Monto a fondear</Text>
            <View style={styles.inputRow}>
              <Image
                source={instrument.isPlus
                  ? require('../assets/png/cUSDPlus.png')
                  : require('../assets/png/cUSD.png')}
                style={styles.tokenIcon}
              />
              <Text style={styles.currency}>$</Text>
              <TextInput
                style={styles.input}
                keyboardType="decimal-pad"
                placeholder="0.00"
                value={amount}
                onChangeText={setAmount}
                returnKeyType="done"
              />
              {availableBalance !== null && availableBalance > 0 && (
                <TouchableOpacity
                  style={styles.maxChip}
                  onPress={() => setAmount(availableBalance.toFixed(2))}
                  accessibilityRole="button"
                  accessibilityLabel="Usar todo el saldo disponible"
                >
                  <Text style={styles.maxChipText}>MAX</Text>
                </TouchableOpacity>
              )}
            </View>
            <Text style={styles.cardHint}>Moveremos este monto desde la cuenta de negocio hacia la bóveda de nómina.</Text>
            {/* An Ondo-blocked employer funds in non-yield cUSD. Say so once, here:
                the money works the same for paying wages, but it does not
                earn — and finding that out from a flat balance months later
                is worse than one line now. */}
            {railStatus?.fundingToken === 'CUSD_BSC' ? (
              <Text style={styles.cardHint}>
                Tu nómina se fondea en {vaultInstrument.name}. Paga igual, pero no
                genera rendimiento en tu país.
              </Text>
            ) : null}
          </View>

          <Button
            title="Agregar a bóveda"
            onPress={handleSubmit}
            loading={processing}
            disabled={!isBusinessAccount}
            icon={<Icon name="arrow-up-right" size={16} color={colors.white} />}
            style={{ marginHorizontal: 16, marginTop: 18, backgroundColor: colors.primary }}
            textStyle={{ fontWeight: '700' }}
          />

          {!isBusinessAccount ? (
            <View style={styles.infoBox}>
              <Icon name="alert-triangle" size={16} color={colors.warning.text} />
              <Text style={styles.infoText}>Cambia a tu cuenta de negocio para fondear la bóveda de nómina.</Text>
            </View>
          ) : null}

          <View style={styles.card}>
            <Text style={styles.cardLabel}>Retirar de la bóveda</Text>
            <Text style={styles.cardHint}>Recupera fondos de la bóveda de nómina hacia tu cuenta o a otra dirección.</Text>
            <View style={[styles.inputRow, { marginTop: 10 }]}>
              <Image
                source={instrument.isPlus
                  ? require('../assets/png/cUSDPlus.png')
                  : require('../assets/png/cUSD.png')}
                style={styles.tokenIcon}
              />
              <Text style={styles.currency}>$</Text>
              <TextInput
                style={styles.input}
                keyboardType="decimal-pad"
                placeholder="0.00"
                value={withdrawAmount}
                onChangeText={setWithdrawAmount}
                returnKeyType="done"
              />
              {vaultBalance !== null && vaultBalance > 0 && (
                <TouchableOpacity
                  style={styles.maxChip}
                  onPress={() => setWithdrawAmount(vaultBalance.toFixed(2))}
                  accessibilityRole="button"
                  accessibilityLabel="Retirar todo el saldo de la bóveda"
                >
                  <Text style={styles.maxChipText}>MAX</Text>
                </TouchableOpacity>
              )}
            </View>
            <Button
              title="Retirar de bóveda"
              variant="secondary"
              onPress={handleWithdraw}
              loading={processing}
              disabled={!isBusinessAccount}
              icon={<Icon name="arrow-down-left" size={16} color="#111" />}
              style={{ marginTop: 12, backgroundColor: colors.border, borderWidth: 0 }}
              textStyle={{ color: colors.text.primary, fontWeight: '700' }}
            />
          </View>
        </ScrollView>
      </TouchableWithoutFeedback>

      <LoadingOverlay visible={processing} message={processingMessage} />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.white },
  vaultHero: {
    marginHorizontal: 16,
    marginTop: 12,
    borderRadius: 16,
    backgroundColor: colors.primary,
    overflow: 'hidden',
  },
  vaultHeroInner: {
    padding: 16,
  },
  vaultHeroLabel: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
    color: colors.primaryLight,
    marginBottom: 6,
  },
  vaultHeroBalance: {
    fontSize: 28,
    fontWeight: '800',
    color: colors.white,
  },
  vaultHeroHint: {
    fontSize: 13,
    color: 'rgba(255,255,255,0.85)',
    marginTop: 8,
  },
  instrumentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 4,
  },
  poolRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 10,
    marginBottom: 4,
  },
  poolChip: {
    flex: 1,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.neutralDark,
    backgroundColor: colors.neutral,
  },
  poolChipSelected: {
    borderColor: colors.primary,
    backgroundColor: colors.primarySoft,
  },
  poolChipText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  poolChipAmount: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.text.primary,
    marginTop: 2,
  },
  poolChipTextSelected: { color: colors.primaryDark },
  instrumentIcon: { width: 18, height: 18, resizeMode: 'contain' },
  instrumentLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.85)',
  },
  maxChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 8,
    backgroundColor: colors.primarySoft,
    marginLeft: 8,
  },
  maxChipText: {
    fontSize: 11,
    fontWeight: '800',
    color: colors.primaryDark,
    letterSpacing: 0.5,
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
  cardHint: {
    marginTop: 6,
    color: colors.muted,
    fontSize: 12,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: colors.white,
  },
  tokenIcon: { width: 22, height: 22, resizeMode: 'contain', marginRight: 8 },
  currency: {
    fontWeight: '700',
    color: colors.textFlat,
    marginRight: 10,
  },
  input: {
    flex: 1,
    fontSize: 18,
    color: colors.textFlat,
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
    color: colors.warning.text,
    fontSize: 13,
  },
});

export default PayrollTopUpScreen;
