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
import { ProcessingHero } from '../components/common/ProcessingHero';

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

const withTimeout = async <T,>(promise: Promise<T>, ms: number, label: string): Promise<T> => {
  return await Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`timeout:${label}`)), ms)
    )
  ]);
};

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
  // BSC sponsored rail (send/bsc_flow.py). `bscSend` routes to the 7702
  // batch instead of the Algorand path. `bscTokenType` names an EXPLICIT
  // token shape (D/E) and must stay undefined for a dollar-value send —
  // that's what lets the server keep its eligibility fork (cUSD+ to an
  // eligible Confío recipient, atomic redeem-to-USDT for everyone else).
  bscSend?: boolean;
  bscTokenType?: 'CUSD_PLUS' | 'CONFIO';
  // Sending to someone who is NOT on Confío yet: the money goes into the BSC
  // invite escrow instead of to an address (send/invite_bsc_flow.py). A
  // different contract and a different batch from `bscSend`, so it is its own
  // flag — and here the token IS explicit, because the escrow must be told
  // what it is holding.
  bscInvite?: boolean;
  bscInviteToken?: 'CUSD_PLUS' | 'CONFIO';
  senderName?: string;
  sender?: string;
  recipientName?: string;
  preparedInvite?: {
    userTransaction: { txn: string; groupId?: string; first?: number; last?: number; gh?: string; gen?: string };
    sponsorTransactions: Array<{ txn: string; index: number }>;
    groupId?: string;
    invitationId: string;
  } | null;
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
  const pulseLoopRef = useRef<Animated.CompositeAnimation | null>(null);
  const bounceLoopRefs = useRef<Animated.CompositeAnimation[]>([]);

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
    // Watchdog: fail fast if processing stalls. It must sit ABOVE the rail's
    // own timeout, never below it — declaring failure while the send is still
    // in flight is worse than waiting, because the user goes back, retries,
    // and the minute-keyed idempotency key has rolled by then: two sends.
    // Algorand settles in seconds. A BSC sponsored send legitimately runs
    // much longer (prepare + sign + submit + bscWaitForReceipt, which alone
    // has a 120s budget before throwing its own, better-worded error), so
    // the backstop only fires once that has had its chance. The common case
    // is now far quicker — the sponsor usually reports the execution it saw
    // and the client never polls — but the watchdog sizes the WORST case.
    const watchdogMs = ((transactionData as any)?.bscSend || (transactionData as any)?.bscInvite)
      ? 180000 : 20000;
    const watchdog = setTimeout(() => {
      if (isComplete) return;
      setTransactionError('La transacción tardó demasiado. Revisa tu conexión e inténtalo de nuevo.');
      setIsComplete(true);
    }, watchdogMs);

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
        } else {        }
      } catch (error) {
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
        } else {          setTransactionError(data?.payInvoice?.errors?.join('\n') || 'Error al procesar el pago');
          setIsComplete(true);
        }
      } catch (error) {
        setTransactionError('Error al procesar el pago. Por favor, inténtalo de nuevo.');
        setIsComplete(true);
      }
    };

    const processSend = async () => {
      try {

        // All sends now go through the same mutation
        await processUnifiedSend();
      } catch (error) {
        setTransactionError('Error al procesar la transacción. Por favor, inténtalo de nuevo.');
        setIsComplete(true);
      }
    };

    const processAlgorandSponsoredSend = async () => {
      try {
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
        } else {          setTransactionError('No recipient information available');
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
          if (!loaded) {            // We do NOT return here anymore. We let signTransactionBytes try to restore the wallet context derived from Auth.
          }
          currentAccount = algorandService.getCurrentAccount();
        }

        if (!currentAccount) {        }

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

        const preparedInvite = transactionData.preparedInvite;
        const res = preparedInvite
          ? await inviteSendService.submitPreparedInvite(preparedInvite)
          : await (async () => {
              const prepared = await inviteSendService.prepareInvite(phone, undefined, amountNum, assetType, message);
              if (!prepared.success || !prepared.prepared) {
                return { success: false, error: prepared.error || 'No se pudo preparar la invitación' };
              }
              if (transactionData) {
                (transactionData as any).preparedInvite = prepared.prepared;
                (transactionData as any).idempotencyKey = prepared.prepared.invitationId;
              }
              return inviteSendService.submitPreparedInvite(prepared.prepared);
            })();

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
        const invitationId =
          res.invitationId ||
          preparedInvite?.invitationId ||
          (transactionData as any).preparedInvite?.invitationId ||
          (transactionData as any).idempotencyKey;
        if (invitationId) {
          (transactionData as any).invitationId = invitationId;
          (transactionData as any).idempotencyKey = invitationId;
        }
        // Mark as submitted so Success screen shows "Confirmando…" until Celery confirms
        (transactionData as any).status = 'SUBMITTED';
        setTransactionSuccess(true);
        setIsComplete(true);
      } catch (error) {
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

    // BSC send (cUSD+/USDT/CONFIO via sponsored 7702) — the server picks the
    // call shape; this screen just signs and reports. Reached from the
    // contact send (dollar value, recipient on Confío) and from the
    // address send (which may also name an explicit token). A send to someone
    // NOT on Confío goes to processBscInvite instead.
    const processBscSponsoredSend = async () => {
      const { sendBscDollar, BSC_SEND_ERRORS } = await import('../services/bscSend');
      // Every BSC RPC (nonce reads, receipt polling) goes through our server,
      // never a public node — the transport is a module-level singleton, so
      // installing here covers entries that reached this screen without
      // passing through a savings flow first.
      const { installBscServerTransport } = await import('../services/bscServerRpc');
      installBscServerTransport();
      try {
        setCurrentStep(1);
        setCurrentStep(2);
        const res = await sendBscDollar({
          amount: transactionData.amount,
          recipientUserId: transactionData.recipientUserId,
          recipientPhone: transactionData.recipientUserId
            ? undefined
            : transactionData.recipientPhone,
          recipientAddress: (transactionData as any).recipientAddress,
          memo: transactionData.memo || '',
          idempotencyKey: transactionData.idempotencyKey,
          tokenType: transactionData.bscTokenType,
        });
        // On a dollar send the server picks the funding source, so what
        // LANDED can differ from what was asked (an eligible Confío
        // recipient receives cUSD+, an external address receives USDT).
        // Name the delivered token so the success screen can't claim the
        // wrong one.
        const delivered: Record<string, string> = {
          CUSD_PLUS: 'cUSD+', USDT: 'USDT', CONFIO: 'CONFIO',
        };
        if (res?.tokenType && delivered[res.tokenType]) {
          transactionData.currency = delivered[res.tokenType];
        }
        // `pending` = broadcast, receipt not observed in time. Treat it as
        // SENT, not failed: the server's confirm task settles it from the
        // chain, and the history row is already there. Showing an error here
        // invites a retry whose minute-keyed idempotency key has rolled,
        // which is exactly how the same money left twice.
        (transactionData as any).transactionHash = res?.txHash || (transactionData as any).transactionHash;
        // sendId IS the SendTransaction internal_id — the handle the success
        // screen polls settlement with. Without it that screen has nothing to
        // ask about and would sit on 'Confirmando…' forever.
        if (res?.sendId) (transactionData as any).internalId = res.sendId;
        // ALWAYS 'SUBMITTED', never CONFIRMED from here. Holding a receipt is
        // not the same as the transaction being final: on BSC a block is only
        // committed once the validator set has voted on it, and until then a
        // reorg can still take it back. 'Confirmado' is the CELERY confirm
        // task's word, read from the server row — the success screen polls
        // for it, which is why claiming it locally is both wrong and
        // unnecessary. (On Algorand this distinction never existed: the
        // first block is final.)
        (transactionData as any).status = 'SUBMITTED';
        setTransactionSuccess(true);
        setIsComplete(true);
      } catch (e: any) {
        const code = e?.message || '';
        setTransactionError(
          BSC_SEND_ERRORS[code]
          || 'No se pudo enviar. Revisa tu conexión e inténtalo de nuevo.',
        );
        setIsComplete(true);
      }
    };

    // BSC invite (cUSD+/CONFIO locked in ConfioInviteEscrow for a phone that
    // isn't a Confío user yet). The sponsor releases it when they join; the
    // inviter can reclaim after 7 days from the transaction detail screen.
    const processBscInvite = async () => {
      const { createBscInvite, BSC_INVITE_ERRORS } = await import('../services/inviteBsc');
      // Every BSC RPC (nonce reads, receipt polling) goes through our server,
      // never a public node.
      const { installBscServerTransport } = await import('../services/bscServerRpc');
      installBscServerTransport();
      try {
        setCurrentStep(1);
        const res = await createBscInvite({
          phone: transactionData.recipientPhone as string,
          amount: transactionData.amount,
          tokenType: (transactionData as any).bscInviteToken || 'CUSD_PLUS',
        });
        setCurrentStep(2);
        (transactionData as any).transactionHash = res.txHash;
        (transactionData as any).transactionId = res.txHash;
        // The server's invite id is the stable retry key AND what the reclaim
        // button needs later, so it replaces the local key the send screen
        // guessed before prepare had answered.
        (transactionData as any).invitationId = res.inviteId;
        (transactionData as any).idempotencyKey = res.inviteId;
        // Always SUBMITTED: on BSC a block isn't final until the validator set
        // has voted, so 'Confirmado' is the server confirm task's word to say.
        (transactionData as any).status = 'SUBMITTED';
        setTransactionSuccess(true);
        setIsComplete(true);
      } catch (e: any) {
        const code = e?.message || '';
        setTransactionError(
          BSC_INVITE_ERRORS[code]
          || 'No se pudo enviar la invitación. Revisa tu conexión e inténtalo de nuevo.',
        );
        setIsComplete(true);
      }
    };

    const processUnifiedSend = async () => {
      try {
        // Step 1: Verifying transaction
        setCurrentStep(0);
        await new Promise(resolve => setTimeout(resolve, 1000));

        if ((transactionData as any)?.bscInvite && transactionData.recipientPhone) {
          await processBscInvite();
        } else if ((transactionData as any)?.bscSend) {
          await processBscSponsoredSend();
        } else if (transactionData.isOnConfio === false && transactionData.recipientPhone) {
          // If recipient is not on Confío and we have a phone, route to Invite flow
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
        setTransactionError('No se pudo conectar con el servidor. Por favor, verifica tu conexión e inténtalo de nuevo.');
        setIsComplete(true);
      }
    };

    initializeProcessing();
  }, [bioChecked]); // Run after biometric check completes

  // Pulse animation for current step
  useEffect(() => {
    pulseLoopRef.current?.stop();
    if (!isComplete) {
      pulseLoopRef.current = Animated.loop(
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
      );
      pulseLoopRef.current.start();
    }
    return () => {
      pulseLoopRef.current?.stop();
      pulseAnim.stopAnimation();
    };
  }, [currentStep, isComplete]);

  // Bounce animation for dots
  useEffect(() => {
    bounceLoopRefs.current.forEach((animation) => animation.stop());
    bounceLoopRefs.current = [];
    if (!isComplete) {
      bounceAnims.forEach((anim, index) => {
        const loop = Animated.loop(
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
        );
        bounceLoopRefs.current.push(loop);
        loop.start();
      });
    }
    return () => {
      bounceLoopRefs.current.forEach((animation) => animation.stop());
      bounceLoopRefs.current = [];
      bounceAnims.forEach((anim) => anim.stopAnimation());
    };
  }, [currentStep, isComplete]);

  return (
    <View style={styles.container}>
      <ProcessingHero
        title={isComplete ? '¡Casi listo!' : transactionData.action}
        amount={`$${transactionData.amount} ${transactionData.currency}`}
        hint={transactionData.type === 'sent'
          ? `Para ${transactionData.recipient}`
          : `En ${transactionData.merchant}`}
        complete={isComplete && transactionSuccess}
      />

      {/* Current step: one quiet living line instead of the steps card */}
      {!isComplete && (
        <View style={styles.stepLine}>
          <Text style={styles.stepText}>{processingSteps[currentStep].text}</Text>
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
                        outputRange: [0, -5]
                      })
                    }]
                  }
                ]}
              />
            ))}
          </View>
        </View>
      )}

      <View style={{ flex: 1 }} />

      <View style={styles.securityRow}>
        <Icon name="shield" size={16} color={colors.primaryDark} />
        <Text style={styles.securityText}>
          Transacción segura · Confío cubre la comisión de red
        </Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  stepLine: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: 4,
  },
  stepText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.secondary,
  },
  dotsContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 3,
  },
  dot: {
    width: 5,
    height: 5,
    borderRadius: 2.5,
    backgroundColor: colors.primary,
  },
  securityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingBottom: 48,
    paddingHorizontal: 32,
  },
  securityText: {
    fontSize: 13,
    color: colors.text.secondary,
  },
});
