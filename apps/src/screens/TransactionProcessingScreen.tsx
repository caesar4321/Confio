import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Platform, Animated, ScrollView, BackHandler, Alert } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useFocusEffect } from '@react-navigation/native';
import { useMutation } from '@apollo/client';
import { PAY_INVOICE } from '../apollo/queries';
// HTTP GraphQL fallback removed for Send; WebSocket-only
import { AccountManager } from '../utils/accountManager';
import algorandService from '../services/algorandService';
import { inviteSendService } from '../services/inviteSendService';
import { useAccount } from '../contexts/AccountContext';
import { cusdAppOptInService } from '../services/cusdAppOptInService';
import * as nacl from 'tweetnacl';
import * as msgpack from 'algorand-msgpack';
import { Buffer } from 'buffer';
import { biometricAuthService } from '../services/biometricAuthService';
import { gql } from '@apollo/client';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';
import { colors } from '../config/theme';

const BUILD_AUTO_SWAP_TRANSACTIONS = gql`
  mutation BuildAutoSwapTransactions($inputAssetType: String!, $amount: String!) {
    buildAutoSwapTransactions(inputAssetType: $inputAssetType, amount: $amount) {
      success
      error
      transactions
    }
  }
`;

const SUBMIT_AUTO_SWAP_TRANSACTIONS = gql`
  mutation SubmitAutoSwapTransactions(
    $internalId: String!
    $signedTransactions: [String]!
    $sponsorTransactions: [String]!
    $withdrawalId: String
  ) {
    submitAutoSwapTransactions(
      internalId: $internalId
      signedTransactions: $signedTransactions
      sponsorTransactions: $sponsorTransactions
      withdrawalId: $withdrawalId
    ) {
      success
      error
      txid
    }
  }
`;

const BUILD_BURN_AND_SEND = gql`
  mutation BuildBurnAndSend($amount: String!, $recipientAddress: String!, $note: String) {
    buildBurnAndSend(amount: $amount, recipientAddress: $recipientAddress, note: $note) {
      success
      error
      transactions
    }
  }
`;

function isTechnicalSendFlowError(message?: string | null): boolean {
  const normalized = (message || '').trim().toLowerCase();
  if (!normalized) {
    return true;
  }

  return [
    'open_timeout',
    'prepare_timeout',
    'submit_timeout',
    'ws_closed',
    'prepare_exception',
    'submit_exception',
    'submit_failed',
    'not_open',
    'network request failed',
  ].includes(normalized);
}

const AUTO_SWAP_REQUEST_TIMEOUT_MS = 20000;

function parseAutoSwapPayload(raw: any) {
  if (!raw) {
    throw new Error('missing_auto_swap_payload');
  }

  let payload = typeof raw === 'string' ? JSON.parse(raw) : raw;
  if (typeof payload === 'string') {
    payload = JSON.parse(payload);
  }

  if (!payload || typeof payload !== 'object') {
    throw new Error('invalid_auto_swap_payload');
  }

  return payload;
}

type TransactionType = 'sent' | 'payment';

interface TransactionData {
  type: TransactionType;
  amount: string;
  currency: string;
  recipient?: string;
  merchant?: string;
  action: string;
  isOnConfio?: boolean;
  internalId?: string;
  recipientAddress?: string;
  recipientPhone?: string;
  recipientUserId?: string;
  invoiceId?: string;
  memo?: string;
  idempotencyKey?: string; // Pass idempotency key from calling screen
  transactionId?: string; // Store transaction ID after successful processing
  tokenType?: string; // For blockchain transactions (CUSD, CONFIO)
  senderName?: string;
  sender?: string;
  recipientName?: string;
}

export const TransactionProcessingScreen = () => {
  const navigation = useNavigation();
  const route = useRoute();
  const { activeAccount } = useAccount();
  const { userProfile } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);
  // const insets = useSafeAreaInsets();

  const transactionData: TransactionData = (route.params as any)?.transactionData || {
    type: 'sent',
    amount: '125.50',
    currency: 'cUSD',
    recipient: 'María González',
    action: 'Enviando',
    isOnConfio: true
  };

  const [currentStep, setCurrentStep] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [transactionSuccess, setTransactionSuccess] = useState(false);
  const [transactionError, setTransactionError] = useState<string | null>(null);
  const [bioChecked, setBioChecked] = useState(false);
  const [pulseAnim] = useState(new Animated.Value(1));
  const [bounceAnims] = useState([
    new Animated.Value(0),
    new Animated.Value(0),
    new Animated.Value(0)
  ]);

  // GraphQL mutations
  const [payInvoice] = useMutation(PAY_INVOICE);
  const [buildAutoSwapTransactions] = useMutation(BUILD_AUTO_SWAP_TRANSACTIONS);
  const [submitAutoSwapTransactions] = useMutation(SUBMIT_AUTO_SWAP_TRANSACTIONS);
  const [buildBurnAndSend] = useMutation(BUILD_BURN_AND_SEND);
  // Removed GraphQL send mutations to enforce WS-only for Send

  // Ref to prevent duplicate transaction processing within this session
  const hasProcessedRef = useRef(false);

  // Use idempotency key from transactionData, or generate one as fallback
  const idempotencyKey = transactionData.idempotencyKey || (() => {
    // Fallback: generate idempotency key if not provided
    const timestamp = Date.now();
    if (transactionData.type === 'payment' && transactionData.invoiceId) {
      return `pay_${transactionData.invoiceId}_${timestamp}`;
    } else if (transactionData.type === 'sent') {
      // Use recipient identifier (phone, userId, or address)
      let recipientId = 'unknown';
      if (transactionData.recipientUserId) {
        recipientId = transactionData.recipientUserId;
      } else if (transactionData.recipientPhone) {
        recipientId = transactionData.recipientPhone.replace(/\D/g, '').slice(-8);
      } else if (transactionData.recipientAddress) {
        recipientId = transactionData.recipientAddress.slice(-8);
      }
      const amountStr = transactionData.amount.replace('.', '');
      return `send_${recipientId}_${amountStr}_${transactionData.currency}_${timestamp}`;
    } else {
      return `tx_unknown_${timestamp}`;
    }
  })();

  // Processing steps
  const processingSteps = [
    {
      icon: 'shield',
      text: 'Verificando transacción',
      color: colors.accent,
      bgColor: '#DBEAFE'
    },
    {
      icon: 'zap',
      text: 'Procesando en blockchain',
      color: colors.primary,
      bgColor: '#D1FAE5'
    },
    {
      icon: 'check-circle',
      text: 'Confirmando...',
      color: colors.success,
      bgColor: '#D1FAE5'
    }
  ];

  // Prevent back navigation during processing
  useFocusEffect(
    React.useCallback(() => {
      const onBackPress = () => {
        // Block back navigation during processing to prevent transaction interruption
        return true; // Return true to prevent default back behavior
      };

      // Add event listener for hardware back button
      const subscription = BackHandler.addEventListener('hardwareBackPress', onBackPress);

      // Cleanup function to remove event listener
      return () => {
        subscription.remove();
      };
    }, [])
  );

  // Handle navigation after transaction completes
  useEffect(() => {
    if (isComplete && transactionSuccess) {
      // Navigate quickly; confirmation may complete in background
      const delayMs = 0;
      const timer = setTimeout(() => {
        try {
        } catch { }
        (navigation as any).replace('TransactionSuccess', { transactionData });
      }, delayMs);
      return () => clearTimeout(timer);
    } else if (isComplete && transactionError) {
      // Show error and go back
      Alert.alert(
        'Error al enviar',
        transactionError,
        [{ text: 'Entendido', onPress: () => navigation.goBack() }]
      );
    }
  }, [isComplete, transactionSuccess, transactionError, navigation]);

  // Process transaction when screen loads
  useEffect(() => {
    (async () => {
      if (bioChecked) return;
      const ok = await biometricAuthService.authenticate(
        'Autoriza esta operación crítica (envío/pago)'
      );
      if (!ok) {
        Alert.alert(
          'Se requiere biometría',
          Platform.OS === 'ios' ? 'Confirma con Face ID o Touch ID para continuar.' : 'Confirma con tu huella digital para continuar.',
          [{ text: 'Entendido', onPress: () => navigation.goBack() }]
        );
        return;
      }
      setBioChecked(true);
    })();
  }, [bioChecked, navigation]);

  useEffect(() => {
    if (!bioChecked) return;
    // Watchdog: fail fast if processing stalls
    const watchdog = setTimeout(() => {
      if (isComplete) return;
      console.warn('TransactionProcessingScreen: Watchdog triggered, aborting transaction');
      setTransactionError('La transacción tardó demasiado. Revisa tu conexión e inténtalo de nuevo.');
      setIsComplete(true);
    }, 20000);

    return () => clearTimeout(watchdog);
  }, [bioChecked, isComplete]);

  useEffect(() => {
    if (!bioChecked) return;

    // Prevent duplicate processing within this screen session
    if (hasProcessedRef.current) {
      return;
    }

    const initializeProcessing = async () => {
      try {
        hasProcessedRef.current = true;

        if (transactionData.type === 'payment' && transactionData.invoiceId) {
          await processPayment();
        } else if (transactionData.type === 'sent') {
          await processSend();
        } else {
          console.error('TransactionProcessingScreen: Unknown transaction type or missing data:', {
            type: transactionData.type,
            hasRecipient: !!transactionData.recipient,
            hasRecipientPhone: !!transactionData.recipientPhone,
            hasRecipientUserId: !!transactionData.recipientUserId
          });
        }
      } catch (error) {
        console.error('TransactionProcessingScreen: Error in initializeProcessing:', error);
      }
    };

    const processPayment = async () => {
      try {

        // Debug: Check current active account context before payment
        try {
          const accountManager = AccountManager.getInstance();
          const activeContext = await accountManager.getActiveAccountContext();
        } catch (error) {
        }

        // Step 1: Verifying transaction
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 1000));

        // Step 2: Processing in blockchain
        setCurrentStep(1);
        await new Promise(resolve => setTimeout(resolve, 1000));

        // Step 3: Call the actual payment mutation with security checks
        setCurrentStep(2);

        // Perform payment operation
        const { data } = await payInvoice({
          variables: {
            invoiceId: transactionData.invoiceId,
            idempotencyKey: idempotencyKey
          }
        });


        if (data?.payInvoice?.success) {
          setTransactionSuccess(true);
          setIsComplete(true);
        } else {
          console.error('TransactionProcessingScreen: Payment failed:', data?.payInvoice?.errors);
          setTransactionError(data?.payInvoice?.errors?.join('\n') || 'Error al procesar el pago');
          setIsComplete(true);
        }
      } catch (error) {
        console.error('TransactionProcessingScreen: Error processing payment:', error);
        setTransactionError('Error al procesar el pago. Por favor, inténtalo de nuevo.');
        setIsComplete(true);
      }
    };

    const processSend = async () => {
      try {

        // All sends now go through the same mutation
        await processUnifiedSend();
      } catch (error) {
        console.error('TransactionProcessingScreen: Error in processSend:', error);
        setTransactionError('Error al procesar la transacción. Por favor, inténtalo de nuevo.');
        setIsComplete(true);
      }
    };

    const processAlgorandSponsoredSend = async () => {
      try {
        const withTimeout = async <T,>(promise: Promise<T>, ms: number, label: string): Promise<T> => {
          return await Promise.race([
            promise,
            new Promise<never>((_, reject) =>
              setTimeout(() => reject(new Error(`timeout:${label}`)), ms)
            )
          ]);
        };

        // Prefer WebSocket prepare/submit for lower latency
        setCurrentStep(1);

        // Build variables based on what recipient info we have
        const variables: any = {
          amount: parseFloat(transactionData.amount),
          assetType: (transactionData.tokenType || transactionData.currency || 'CUSD').toUpperCase(),
          note: transactionData.memo || undefined
        };

        // Add recipient identification based on what's available
        if (transactionData.recipientUserId) {
          variables.recipientUserId = transactionData.recipientUserId;
        } else if (transactionData.recipientPhone) {
          variables.recipientPhone = transactionData.recipientPhone;
        } else if (transactionData.recipientAddress) {
          variables.recipientAddress = transactionData.recipientAddress;
        } else {
          console.error('TransactionProcessingScreen: No recipient identification available');
          setTransactionError('No recipient information available');
          setIsComplete(true);
          return;
        }

        try {
        } catch { }

        let userTransaction: string | null = null;
        let sponsorTransaction: string | null = null;
        // Use prepared pack if provided by the confirm screen
        try {
          const prepared = (transactionData as any)?.prepared;
          const txs = prepared && Array.isArray(prepared.transactions) ? prepared.transactions : [];
          if (txs.length >= 2) {
            sponsorTransaction = txs.find((t: any) => t.index === 0)?.transaction || null;
            userTransaction = txs.find((t: any) => t.index === 1)?.transaction || null;
          }
          if (userTransaction && sponsorTransaction) {
          }
        } catch { }
        try {
          if (!(userTransaction && sponsorTransaction)) {
            const { prepareSendViaWs } = await import('../services/sendWs');
            const pack = await withTimeout(prepareSendViaWs({
                amount: variables.amount,
                assetType: variables.assetType,
                note: variables.note,
                recipientAddress: variables.recipientAddress,
                recipientUserId: variables.recipientUserId,
                recipientPhone: variables.recipientPhone,
              }), 10000, 'ws_prepare');
            const txs = pack?.transactions || [];
            sponsorTransaction = txs.find((t: any) => t.index === 0)?.transaction || null;
            userTransaction = txs.find((t: any) => t.index === 1)?.transaction || null;
          }
        } catch (wsErr: any) {
          console.error('TransactionProcessingScreen: WS prepare failed:', wsErr);
          const errMsg = typeof wsErr === 'string' ? wsErr : (wsErr?.message || '');
          if (errMsg.includes('must optin') || errMsg.includes('missing from')) {
            const assetName = transactionData.tokenType || transactionData.currency || 'este token';
            setTransactionError(`La billetera de destino no está configurada para recibir ${assetName}. Deben agregar el token primero.`);
          } else if (errMsg.includes('Insufficient') && errMsg.includes('balance')) {
            const assetName = transactionData.tokenType || transactionData.currency || 'fondos';
            setTransactionError(`Saldo insuficiente. No tienes suficientes ${assetName} para realizar este envío.`);
          } else if (!isTechnicalSendFlowError(errMsg)) {
            setTransactionError(errMsg);
          } else {
            setTransactionError('No se pudo preparar la transacción. Revisa tu conexión e inténtalo de nuevo.');
          }
          setIsComplete(true);
          return;
        }
        if (!userTransaction || !sponsorTransaction) {
          setTransactionError('Invalid prepare pack');
          setIsComplete(true);
          return;
        }

        // Step 3: Sign the user transaction with Algorand wallet
        setCurrentStep(2);

        // Load the stored wallet if not already loaded
        let currentAccount = algorandService.getCurrentAccount();
        if (!currentAccount) {
          const loaded = await algorandService.loadStoredWallet();
          if (!loaded) {
            console.warn('TransactionProcessingScreen: No stored wallet found, but proceeding to allow auto-healing via signTransactionBytes...');
            // We do NOT return here anymore. We let signTransactionBytes try to restore the wallet context derived from Auth.
          }
          currentAccount = algorandService.getCurrentAccount();
        }

        if (!currentAccount) {
          console.warn('TransactionProcessingScreen: Wallet still not loaded, hoping signTransactionBytes heals it...');
        }

        // Decode user transaction (base64 -> bytes)
        const userTxnBytes = Uint8Array.from(Buffer.from(userTransaction, 'base64'));

        // Sign the user transaction locally using deterministic wallet
        const signedUserTxnBytes = await algorandService.signTransactionBytes(userTxnBytes);
        const signedUserTxnB64 = Buffer.from(signedUserTxnBytes).toString('base64');

        let transactionId: string | undefined;
        let confirmedRound: number | undefined;
        try {
          const { submitSendViaWs } = await import('../services/sendWs');
          const submitRes = await withTimeout(
            submitSendViaWs(signedUserTxnB64, sponsorTransaction!),
            12000,
            'ws_submit'
          );
          if (!submitRes || !(submitRes.transactionId || submitRes.transaction_id)) {
            throw new Error('submit_failed');
          }
          transactionId = (submitRes.transactionId || submitRes.transaction_id) as string;
          const internalId = (submitRes.internalId || submitRes.internal_id) as string | undefined;
          confirmedRound = (submitRes.confirmedRound || submitRes.confirmed_round) as number | undefined;

          if (transactionData) {
            (transactionData as any).internalId = internalId;
          }
        } catch (wsSubmitErr: any) {
          console.error('TransactionProcessingScreen: WS submit failed:', wsSubmitErr);
          const errMsg = typeof wsSubmitErr === 'string' ? wsSubmitErr : (wsSubmitErr?.message || '');
          if (errMsg.includes('must optin') || errMsg.includes('missing from')) {
            const assetName = transactionData.tokenType || transactionData.currency || 'este token';
            setTransactionError(`La billetera de destino no está configurada para recibir ${assetName}. Deben agregar el token primero.`);
          } else if (errMsg.includes('Insufficient') && errMsg.includes('balance')) {
            const assetName = transactionData.tokenType || transactionData.currency || 'fondos';
            setTransactionError(`Saldo insuficiente. No tienes suficientes ${assetName} para realizar este envío.`);
          } else if (!isTechnicalSendFlowError(errMsg)) {
            setTransactionError(errMsg);
          } else {
            setTransactionError('No se pudo enviar la transacción. Revisa tu conexión e inténtalo de nuevo.');
          }
          setIsComplete(true);
          return;
        }
        try {
        } catch { }

        // Store lightweight transaction details for success screen
        if (transactionData) {
          (transactionData as any).transactionId = transactionId || '';
          (transactionData as any).transactionHash = transactionId || '';
          (transactionData as any).status = confirmedRound ? 'CONFIRMED' : 'SUBMITTED';
          (transactionData as any).confirmedRound = confirmedRound || 0;
        }

        // Mark as successful and let confirmation complete in background
        setTransactionSuccess(true);
        setIsComplete(true);

      } catch (error) {
        console.error('TransactionProcessingScreen: Error processing Algorand sponsored send:', error);
        setTransactionError('Failed to process Algorand transaction. Please try again.');
        setIsComplete(true);
      }
    };

    const processInviteSend = async () => {
      try {
        // Step 1: Verifying
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 600));

        // Step 2: Processing on blockchain (invite escrow)
        setCurrentStep(1);
        const assetType = (transactionData.tokenType || transactionData.currency || 'CUSD').toUpperCase() as 'CUSD' | 'CONFIO';
        const amountNum = parseFloat(transactionData.amount);
        const phone = transactionData.recipientPhone as string;
        const message = transactionData.memo || undefined;

        const res = await inviteSendService.createInviteForPhone(phone, undefined, amountNum, assetType, message);
        if (!res.success) {
          setTransactionError(res.error || 'No se pudo crear la invitación');
          setIsComplete(true);
          return;
        }

        // Step 3: Confirming
        setCurrentStep(2);
        if (res.txid) {
          (transactionData as any).transactionId = res.txid;
        }
        if (res.internalId) {
          (transactionData as any).internalId = res.internalId;
        }
        // Mark as submitted so Success screen shows "Confirmando…" until Celery confirms
        (transactionData as any).status = 'SUBMITTED';
        setTransactionSuccess(true);
        setIsComplete(true);
      } catch (error) {
        console.error('TransactionProcessingScreen: Error processing invite send:', error);
        setTransactionError('Error al procesar la invitación. Inténtalo de nuevo.');
        setIsComplete(true);
      }
    };

    const processCusdSwap = async () => {
      try {
        let amountBaseUnits = Math.floor(parseFloat(transactionData.amount) * 1_000_000).toString();

        const res = await withTimeout(buildAutoSwapTransactions({
          variables: {
            inputAssetType: 'CUSD',
            amount: amountBaseUnits
          }
        }), AUTO_SWAP_REQUEST_TIMEOUT_MS, 'build_auto_swap');

        const data = res.data?.buildAutoSwapTransactions;
        if (!data?.success) {
          throw new Error(data?.error || 'Failed to build intermediate swap');
        }

        const parsedData = parseAutoSwapPayload(data.transactions);
        const { internal_id, transactions, sponsor_transactions } = parsedData;

        // Sign user transactions
        const signedUserTxns = [];
        for (let i = 0; i < transactions.length; i++) {
          const userTxnB64 = transactions[i];
          const userTxnBytes = Uint8Array.from(Buffer.from(userTxnB64, 'base64'));
          const signedBytes = await algorandService.signTransactionBytes(userTxnBytes);
          const signedB64 = Buffer.from(signedBytes).toString('base64');
          signedUserTxns.push(signedB64);
        }

        // Submit the swap group
        const submitRes = await withTimeout(submitAutoSwapTransactions({
          variables: {
            internalId: internal_id,
            signedTransactions: signedUserTxns,
            sponsorTransactions: (sponsor_transactions || []).map((s: any) => typeof s === 'string' ? s : JSON.stringify(s))
          }
        }), AUTO_SWAP_REQUEST_TIMEOUT_MS, 'submit_auto_swap');

        if (!submitRes.data?.submitAutoSwapTransactions?.success) {
          throw new Error(submitRes.data?.submitAutoSwapTransactions?.error || 'Failed to submit intermediate swap');
        }
      } catch (err: any) {
        console.error('TransactionProcessingScreen: Error in cUSD to USDC swap:', err);
        throw new Error('Error al intercambiar el saldo a USDC. ' + err.message);
      }
    };

    const processAtomicBurnAndSend = async () => {
      try {
        setCurrentStep(1);

        const amountBaseUnits = Math.floor(parseFloat(transactionData.amount) * 1_000_000).toString();
        const recipientAddr = transactionData.recipientAddress;

        if (!recipientAddr) {
          throw new Error('No recipient address for atomic burn+send');
        }

        // Step 1: Build atomic group, retry once after cUSD app opt-in if required.
        let data: any = null;
        for (let attempt = 0; attempt < 2; attempt++) {
          const res = await withTimeout(buildBurnAndSend({
            variables: {
              amount: amountBaseUnits,
              recipientAddress: recipientAddr,
              note: transactionData.memo || undefined
            }
          }), AUTO_SWAP_REQUEST_TIMEOUT_MS, 'build_burn_and_send');

          data = res.data?.buildBurnAndSend;
          if (data?.success) break;

          const errMsg = data?.error || 'Failed to build burn+send';
          if (errMsg === 'requires_app_optin' && attempt === 0) {
            const optInResult = await cusdAppOptInService.handleAppOptIn(activeAccount);
            if (!optInResult.success) {
              throw new Error(optInResult.error || 'No se pudo completar la configuración inicial');
            }
            continue;
          }

          if (errMsg.includes('must optin') || errMsg.includes('Recipient must optin')) {
            const assetName = transactionData.tokenType || transactionData.currency || 'USDC';
            throw new Error(`La billetera de destino no está configurada para recibir ${assetName}. Deben agregar el token primero.`);
          }
          throw new Error(errMsg);
        }

        if (!data?.success) {
          throw new Error(data?.error || 'Failed to build burn+send');
        }

        const parsedData = parseAutoSwapPayload(data.transactions);
        const { internal_id, withdrawal_id, transactions, sponsor_transactions } = parsedData;

        // Step 2: Sign the user transactions (indices 1 and 4)
        setCurrentStep(2);

        // Load wallet if needed
        let currentAccount = algorandService.getCurrentAccount();
        if (!currentAccount) {
          await algorandService.loadStoredWallet();
        }

        const signedUserTxns: string[] = [];
        for (let i = 0; i < transactions.length; i++) {
          const txnB64 = transactions[i];
          const txnBytes = Uint8Array.from(Buffer.from(txnB64, 'base64'));
          const signedBytes = await algorandService.signTransactionBytes(txnBytes);
          const signedB64 = Buffer.from(signedBytes).toString('base64');
          signedUserTxns.push(signedB64);
        }

        // Step 3: Submit the complete atomic group
        const submitRes = await withTimeout(submitAutoSwapTransactions({
          variables: {
            internalId: internal_id,
            signedTransactions: signedUserTxns,
            sponsorTransactions: (sponsor_transactions || []).map((s: any) => typeof s === 'string' ? s : JSON.stringify(s)),
            withdrawalId: withdrawal_id || undefined
          }
        }), AUTO_SWAP_REQUEST_TIMEOUT_MS, 'submit_auto_swap');

        if (!submitRes.data?.submitAutoSwapTransactions?.success) {
          throw new Error(submitRes.data?.submitAutoSwapTransactions?.error || 'Failed to submit atomic burn+send');
        }

        const txid = submitRes.data.submitAutoSwapTransactions.txid;

        // Store transaction details for success screen
        if (transactionData) {
          (transactionData as any).transactionId = txid || '';
          (transactionData as any).transactionHash = txid || '';
          (transactionData as any).internalId = internal_id;
          (transactionData as any).status = 'SUBMITTED';
        }

        setTransactionSuccess(true);
        setIsComplete(true);
      } catch (err: any) {
        console.error('TransactionProcessingScreen: Error in atomic burn+send:', err);
        const errMsg = err?.message || '';
        if (errMsg.includes('La billetera de destino')) {
          setTransactionError(errMsg);
        } else if (errMsg.includes('Insufficient') && errMsg.includes('balance')) {
          setTransactionError('Saldo insuficiente. No tienes suficientes cUSD para realizar este envío.');
        } else {
          setTransactionError('Error al procesar el envío. ' + errMsg);
        }
        setIsComplete(true);
      }
    };

    const processUnifiedSend = async () => {
      try {
        // Step 1: Verifying transaction
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 1000));

        // If recipient is not on Confío and we have a phone, route to Invite flow
        if (transactionData.isOnConfio === false && transactionData.recipientPhone) {
          await processInviteSend();
        } else {
          // Pre-flight check: if we need to swap cUSD to USDC first
          if ((transactionData as any)?.needsCusdSwap) {
            await processAtomicBurnAndSend();
          } else {
            // Sponsored direct send for Confío friends or direct address
            await processAlgorandSponsoredSend();
          }
        }
      } catch (error: any) {
        console.error('TransactionProcessingScreen: Error processing send:', error);
        console.error('TransactionProcessingScreen: Error details:', {
          message: error.message,
          networkError: error.networkError,
          graphQLErrors: error.graphQLErrors,
          stack: error.stack
        });

        setTransactionError('No se pudo conectar con el servidor. Por favor, verifica tu conexión e inténtalo de nuevo.');
        setIsComplete(true);
      }
    };

    initializeProcessing();
  }, [bioChecked]); // Run after biometric check completes

  // Pulse animation for current step
  useEffect(() => {
    if (!isComplete) {
      Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {
            toValue: 1.2,
            duration: 1000,
            useNativeDriver: true,
          }),
          Animated.timing(pulseAnim, {
            toValue: 1,
            duration: 1000,
            useNativeDriver: true,
          }),
        ])
      ).start();
    }
  }, [currentStep, isComplete]);

  // Bounce animation for dots
  useEffect(() => {
    if (!isComplete) {
      bounceAnims.forEach((anim, index) => {
        Animated.loop(
          Animated.sequence([
            Animated.timing(anim, {
              toValue: 1,
              duration: 600,
              delay: index * 200,
              useNativeDriver: true,
            }),
            Animated.timing(anim, {
              toValue: 0,
              duration: 600,
              useNativeDriver: true,
            }),
          ])
        ).start();
      });
    }
  }, [currentStep, isComplete]);

  return (
    <ScrollView style={styles.container} showsVerticalScrollIndicator={false}>
      {/* Processing Header */}
      <View style={[styles.header, { backgroundColor: colors.primary, paddingTop: 8 }]}>
        <View style={styles.headerContent}>
          {/* Processing Animation */}
          <View style={styles.processingCircle}>
            {!isComplete ? (
              <>
                <Animated.View style={[styles.pulseCircle, { transform: [{ scale: pulseAnim }] }]} />
                <Icon name="loader" size={48} color={colors.primary} style={styles.spinner} />
              </>
            ) : (
              <Icon name="check-circle" size={48} color={colors.primary} />
            )}
          </View>

          <Text style={styles.headerTitle}>
            {isComplete ? '¡Casi listo!' : transactionData.action}
          </Text>

          <Text style={styles.headerAmount}>
            ${transactionData.amount} {transactionData.currency}
          </Text>

          <Text style={styles.headerSubtitle}>
            {transactionData.type === 'sent'
              ? `Para ${transactionData.recipient}`
              : `En ${transactionData.merchant}`
            }
          </Text>
        </View>
      </View>

      {/* Processing Steps */}
      <View style={styles.content}>
        <View style={styles.stepsContainer}>
          {processingSteps.map((step, index) => (
            <View key={index} style={styles.stepRow}>
              {/* Step Icon */}
              {index === currentStep && !isComplete ? (
                <Animated.View style={[
                  styles.stepIcon,
                  {
                    backgroundColor: index <= currentStep ? step.bgColor : '#F3F4F6',
                    transform: [{ scale: pulseAnim }]
                  }
                ]}>
                  <Icon
                    name={step.icon as any}
                    size={24}
                    color={index <= currentStep ? step.color : '#9CA3AF'}
                  />
                </Animated.View>
              ) : (
                <View style={[
                  styles.stepIcon,
                  {
                    backgroundColor: index <= currentStep ? step.bgColor : '#F3F4F6'
                  }
                ]}>
                  <Icon
                    name={step.icon as any}
                    size={24}
                    color={index <= currentStep ? step.color : '#9CA3AF'}
                  />
                </View>
              )}

              {/* Step Text */}
              <View style={styles.stepTextContainer}>
                <Text style={[
                  styles.stepText,
                  { color: index <= currentStep ? colors.text.primary : '#9CA3AF' }
                ]}>
                  {step.text}
                </Text>
                {index === currentStep && !isComplete && (
                  <View style={styles.dotsContainer}>
                    {bounceAnims.map((anim, dotIndex) => (
                      <Animated.View
                        key={dotIndex}
                        style={[
                          styles.dot,
                          {
                            transform: [{
                              translateY: anim.interpolate({
                                inputRange: [0, 1],
                                outputRange: [0, -8]
                              })
                            }]
                          }
                        ]}
                      />
                    ))}
                  </View>
                )}
              </View>

              {/* Checkmark */}
              {index < currentStep && (
                <Icon name="check-circle" size={20} color={colors.success} />
              )}
              {index === currentStep && isComplete && (
                <Icon name="check-circle" size={20} color={colors.success} />
              )}
            </View>
          ))}
        </View>

        {/* Progress Bar */}
        <View style={styles.progressContainer}>
          <View style={styles.progressBar}>
            <View
              style={[
                styles.progressFill,
                { width: `${((currentStep + 1) / processingSteps.length) * 100}%` }
              ]}
            />
          </View>
          <View style={styles.progressLabels}>
            <Text style={styles.progressLabel}>0%</Text>
            <Text style={styles.progressLabel}>50%</Text>
            <Text style={styles.progressLabel}>100%</Text>
          </View>
        </View>

        {/* Security Message */}
        <View style={styles.securityContainer}>
          <View style={styles.securityContent}>
            <Icon name="shield" size={20} color={colors.primary} />
            <Text style={styles.securityText}>
              <Text style={styles.securityBold}>Transacción segura</Text> • Protegido por blockchain
            </Text>
          </View>
        </View>

        {/* Processing Info */}
        <View style={styles.infoContainer}>
          <View style={styles.infoContent}>
            <Icon name="clock" size={16} color={colors.primary} />
            <View style={styles.infoTextContainer}>
              <Text style={styles.infoTitle}>¿Sabías que...?</Text>
              <Text style={styles.infoText}>
                Confío cubre las comisiones de red para que puedas transferir dinero completamente gratis.
                {supportCopy.processingLine}
              </Text>
            </View>
          </View>
        </View>

        {/* Completion message */}
        {isComplete && (
          <View style={styles.completionContainer}>
            <View style={styles.completionContent}>
              <Icon name="check-circle" size={32} color={colors.success} />
              <Text style={styles.completionTitle}>¡Transacción completada!</Text>
              <Text style={styles.completionText}>Redirigiendo a confirmación...</Text>
            </View>
          </View>
        )}
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
  processingCircle: {
    width: 96,
    height: 96,
    backgroundColor: '#ffffff',
    borderRadius: 48,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 24,
    marginBottom: 24,
    position: 'relative',
  },
  pulseCircle: {
    position: 'absolute',
    width: 96,
    height: 96,
    borderRadius: 48,
    backgroundColor: colors.primary,
    opacity: 0.2,
  },
  spinner: {
    transform: [{ rotate: '0deg' }],
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
  stepsContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 32,
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
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 24,
  },
  stepIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  stepTextContainer: {
    flex: 1,
  },
  stepText: {
    fontSize: 16,
    fontWeight: '500',
  },
  dotsContainer: {
    flexDirection: 'row',
    marginTop: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.primary,
    marginRight: 4,
  },
  progressContainer: {
    marginBottom: 24,
  },
  progressBar: {
    width: '100%',
    height: 8,
    backgroundColor: '#E5E7EB',
    borderRadius: 4,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  progressLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  progressLabel: {
    fontSize: 12,
    color: '#6B7280',
  },
  securityContainer: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 24,
    marginBottom: 16,
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
  securityContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  securityText: {
    fontSize: 14,
    color: '#6B7280',
    marginLeft: 8,
  },
  securityBold: {
    fontWeight: '600',
    color: colors.primary,
  },
  infoContainer: {
    backgroundColor: '#D1FAE5',
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
  },
  infoContent: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  infoTextContainer: {
    flex: 1,
    marginLeft: 8,
  },
  infoTitle: {
    fontSize: 12,
    fontWeight: '600',
    color: '#065F46',
    marginBottom: 4,
  },
  infoText: {
    fontSize: 12,
    color: '#047857',
    lineHeight: 16,
  },
  completionContainer: {
    backgroundColor: '#D1FAE5',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  completionContent: {
    alignItems: 'center',
  },
  completionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#065F46',
    marginTop: 8,
    marginBottom: 4,
  },
  completionText: {
    fontSize: 12,
    color: '#047857',
  },
}); 
