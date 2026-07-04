import { Buffer } from 'buffer';
import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Dimensions,
  Animated,
  Easing,
  BackHandler,
  ScrollView,
  Alert,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
// GraphQL not used in WS-only flow
import { colors } from '../config/theme';
import { ProcessingHero } from '../components/common/ProcessingHero';
// Removed GET_INVOICES and AccountManager in WS-only flow
import { biometricAuthService } from '../services/biometricAuthService';
import { useAuth } from '../contexts/AuthContext';
import { getSupportCopy } from '../utils/supportMessaging';

type PaymentProcessingRouteProp = RouteProp<{
  PaymentProcessing: {
    transactionData: {
      type: 'payment';
      amount: string;
      currency: string;
      merchant: string;
      action: string;
      address?: string;
      message?: string;
      internalId?: string;
      idempotencyKey?: string;
      merchantBusinessId?: string | number;
      preflight?: boolean;
    };
  };
}, 'PaymentProcessing'>;

const { width } = Dimensions.get('window');

export const PaymentProcessingScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<PaymentProcessingRouteProp>();
  const { userProfile } = useAuth();
  const supportCopy = getSupportCopy(userProfile?.phoneCountry);
  const [currentStep, setCurrentStep] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [paymentResponse, setPaymentResponse] = useState<any>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [bioChecked, setBioChecked] = useState(false);

  const hasProcessedRef = useRef(false);
  const ranRef = useRef(false);

  // Helper function to format currency for display
  const formatCurrency = (currency: string): string => {
    if (currency === 'CUSD') return 'cUSD';
    if (currency === 'CONFIO') return 'CONFIO';
    if (currency === 'USDC') return 'USDC';
    return currency; // fallback
  };

  const { transactionData } = route.params;
  const prepared = (transactionData as any)?.prepared || null;

  const isValid = useMemo(() => {
    return (
      !!transactionData &&
      !!transactionData.amount &&
      !!transactionData.merchant &&
      transactionData.type === 'payment'
    );
  }, [transactionData]);

  // Debug logging to track when this screen is accessed (avoid heavy dumps)

  // Safety check - if no transaction data, go back
  useEffect(() => {
    if (!isValid) {      navigation.goBack();
    }
  }, [isValid, navigation]);

  // Animation values (persist across renders)
  const spinValue = useRef(new Animated.Value(0)).current;
  const pulseValue = useRef(new Animated.Value(1)).current;
  const spinAnimRef = useRef<Animated.CompositeAnimation | null>(null);
  const pulseAnimRef = useRef<Animated.CompositeAnimation | null>(null);

  // Processing steps
  const processingSteps = [
    {
      icon: 'shield',
      text: 'Verificando transacción',
      color: '#3B82F6',
      bgColor: '#DBEAFE'
    },
    {
      icon: 'zap',
      text: 'Procesando en blockchain',
      color: '#10B981',
      bgColor: '#D1FAE5'
    },
    {
      icon: 'check-circle',
      text: 'Confirmando...',
      color: '#22C55E',
      bgColor: '#DCFCE7'
    }
  ];

  // Require biometric before processing critical payment
  useEffect(() => {
    (async () => {
      if (bioChecked) return;
      const ok = await biometricAuthService.authenticate(
        'Autoriza esta operación crítica (pago)'
      );
      setBioChecked(true);
      if (!ok) {
        Alert.alert(
          'Se requiere biometría',
          Platform.OS === 'ios' ? 'Confirma con Face ID o Touch ID para continuar.' : 'Confirma con tu huella digital para continuar.',
          [{ text: 'Entendido', onPress: () => navigation.goBack() }]
        );
      }
    })();
  }, [bioChecked, navigation]);

  // Start spinning animation
  useEffect(() => {
    // reset value for fresh loop
    spinValue.setValue(0);
    spinAnimRef.current = Animated.loop(
      Animated.timing(spinValue, {
        toValue: 1,
        duration: 2000,
        easing: Easing.linear,
        useNativeDriver: true,
      })
    );
    spinAnimRef.current.start();

    return () => {
      if (spinAnimRef.current) {
        spinAnimRef.current.stop();
        spinAnimRef.current = null;
      }
    };
  }, [spinValue]);

  // Start pulse animation
  useEffect(() => {
    // reset value for fresh loop
    pulseValue.setValue(1);
    pulseAnimRef.current = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseValue, {
          toValue: 1.2,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(pulseValue, {
          toValue: 1,
          duration: 1000,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ])
    );
    pulseAnimRef.current.start();

    return () => {
      if (pulseAnimRef.current) {
        pulseAnimRef.current.stop();
        pulseAnimRef.current = null;
      }
    };
  }, [pulseValue]);

  // Process payment when screen loads
  useEffect(() => {

    if (!isValid || !transactionData.internalId || isProcessing || hasProcessedRef.current || !bioChecked) {
      return;
    }

    // Ensure this effect runs only once per mount
    if (ranRef.current) return;
    ranRef.current = true;

    const processPaymentWsOnly = async () => {
      if (isProcessing || hasProcessedRef.current) {
        return;
      }

      hasProcessedRef.current = true;
      setIsProcessing(true);

      try {
        const now = () => (typeof performance !== 'undefined' && (performance as any).now ? (performance as any).now() : Date.now());
        const t0 = now();

        // update UI steps
        setCurrentStep(0); // verifying
        setCurrentStep(1); // processing
        setCurrentStep(2); // signing/submitting

        // Ensure we have a prepared pack; if not, prepare via WS now
        let wsPack = prepared && Array.isArray(prepared.transactions) && prepared.transactions.length === 4
          ? prepared
          : null;

        if (!wsPack) {
          const { prepareViaWs } = await import('../services/payWs');
          const amt = parseFloat(String(transactionData.amount || '0'));
          const assetType = String(transactionData.currency || 'cUSD').toUpperCase();
          const note = `Invoice ${transactionData.internalId}`;
          const pack = await prepareViaWs({
            amount: amt,
            assetType,
            internalId: transactionData.internalId,
            note,
            recipientBusinessId: (transactionData as any).merchantBusinessId
          });
          if (!pack || !Array.isArray((pack as any).transactions) || (pack as any).transactions.length !== 4) {
            throw new Error('WS prepare failed or invalid pack');
          }
          wsPack = {
            transactions: (pack as any).transactions,
            paymentId: (pack as any).internalId || (pack as any).internal_id || (pack as any).paymentId || (pack as any).payment_id || transactionData.internalId,
            groupId: (pack as any).groupId || (pack as any).group_id
          } as any;
        }

        // Sign required transactions
        const algorandServiceModule = await import('../services/algorandService');
        const algorandService = algorandServiceModule.default;
        const { submitViaWs } = await import('../services/payWs');

        const transactions = (wsPack as any).transactions;

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

            // We need active account info. We can't use hook here easily as we are in async function, 
            // but we can assume default 'personal' 0 if not available, OR rely on service auto-healing for complex cases.
            // However, explicit restore is safer. Let's try to get it from AccountManager if possible or default.
            // Actually, for Pay, it's usually the main account.

            // Note: In this screen we don't have direct access to 'activeAccount' from useAccount hook inside this callback easily 
            // without passing it in. But we can use the default or just rely on the fact that createOrRestoreWallet 
            // will default to personal/0 if not provided, which matches 99% of use cases.
            // Better: Import AuthService to get context.
            const { AuthService } = await import('../services/authService');
            const authService = AuthService.getInstance();
            const accountContext = await authService.getActiveAccountContext();

            await secureDeterministicWallet.createOrRestoreWallet(
              iss,
              oauthData.subject,
              aud,
              oauthData.provider,
              accountContext.type,
              accountContext.index,
              accountContext.businessId
            );
          }
        } catch (err) {
        }

        const tSignStart = now();
        const signedTransactions: any[] = [];
        for (let i = 0; i < transactions.length; i++) {
          const txn = transactions[i];
          const needsSignature = txn.needs_signature || txn.needsSignature || false;
          const isSigned = txn.signed || false;
          const txnIndex = txn.index !== undefined ? txn.index : i;
          if (needsSignature && !isSigned) {
            const txnData = txn.transaction;
            const txnBytes = Uint8Array.from(Buffer.from(txnData, 'base64'));
            const signedTxnBytes = await algorandService.signTransactionBytes(txnBytes);
            const signedTxnB64 = Buffer.from(signedTxnBytes).toString('base64');
            signedTransactions.push({ index: txnIndex, transaction: signedTxnB64 });
          } else {
            signedTransactions.push({ index: txnIndex, transaction: txn.transaction });
          }
        }
        const tSignEnd = now();

        const paymentIdForSubmit = ((wsPack as any)?.paymentId as string) || (transactionData.internalId as string);
        const wsRes = await submitViaWs(signedTransactions, paymentIdForSubmit);
        if (!wsRes || (!wsRes.transactionId && !(wsRes as any).transaction_id)) {
          throw new Error('WS submit failed');
        }
        const txid = (wsRes as any).transactionId || (wsRes as any).transaction_id;
        const round = (wsRes as any).confirmedRound || (wsRes as any).confirmed_round;
        setIsComplete(true);
        // Include paymentTransaction.internalId for QR verification on success screen
        setPaymentResponse({
          blockchainTxId: txid,
          blockchainRound: round,
          paymentTransaction: { internalId: paymentIdForSubmit }
        });
        return;
        /*
        // Log current account context for debugging
        try {
          const accountManager = AccountManager.getInstance();
          const activeContext = await accountManager.getActiveAccountContext();
        } catch (error) {
        }
        
        // Step 1: Verifying transaction (no artificial delay)
        setCurrentStep(0);
        // Step 2: Processing in blockchain (start immediately without delay)
        setCurrentStep(1);
        
        // Step 3: Prefer reusing existing payment group from pre-dispatch
        setCurrentStep(2);
        // Prefer idempotency key passed from Confirmation to avoid duplicate creation
        const idempotencyKey = transactionData.idempotencyKey || `pay_${transactionData.invoiceId}_${Math.floor(Date.now() / 60000)}`;
        const tCreateStart = now();
        let data: any = null;
        let usedExisting = false;
        try {
          const { apolloClient } = await import('../apollo/client');
          const { gql } = await import('@apollo/client');
          const GET_INVOICE_FOR_PROCESSING = gql`
            query GetInvoiceForProcessing($invoiceId: String!) {
              invoice(invoiceId: $invoiceId) {
                invoiceId
                paymentTransactions {
                  internalId
                  status
                  blockchainData
                  createdAt
                }
              }
            }
          `;
          const res = await apolloClient.query({
            query: GET_INVOICE_FOR_PROCESSING,
            variables: { invoiceId: transactionData.invoiceId },
            fetchPolicy: 'network-only'
          });
          const inv = res.data?.invoice;
          const pts: any[] = inv?.paymentTransactions || [];
          const candidate = pts.find((pt) => {
            if (!pt?.blockchainData) return false;
            try {
              const bd = typeof pt.blockchainData === 'string' ? JSON.parse(pt.blockchainData) : pt.blockchainData;
              return Array.isArray(bd?.transactions) && bd.transactions.length === 4;
            } catch { return false; }
          });
          if (candidate) {
            // Mimic the structure as if PayInvoice returned
            data = {
              payInvoice: {
                paymentTransaction: {
                  internalId: candidate.internalId,
                  blockchainData: candidate.blockchainData,
                },
                success: true
              }
            };
            usedExisting = true;
          }
        } catch (e) {
          // ignore and fallback to PayInvoice
        }
        if (!usedExisting) {
          const resp = await payInvoice({ variables: { invoiceId: transactionData.invoiceId, idempotencyKey } });
          data = resp.data;
        }
        const tCreateEnd = now();


        // Check if we have blockchain transactions to sign
        if (data?.payInvoice?.paymentTransaction?.blockchainData) {
          
          try {
            // Import AlgorandService using default import pattern that works
            const algorandServiceModule = await import('../services/algorandService');
            const algorandService = algorandServiceModule.default;
            const { apolloClient } = await import('../apollo/client');
            const { SUBMIT_SPONSORED_PAYMENT } = await import('../apollo/mutations');
            // Ensure OAuth subject exists (from Keychain). No external fallback here.
            try {
              const { oauthStorage } = await import('../services/oauthStorageService');
              await oauthStorage.getOAuthSubject();
            } catch (oauthCheckErr) {
            }
            
            // Parse blockchainData if it's a string (GraphQL returns it as JSON string)
            let blockchainData = data.payInvoice.paymentTransaction.blockchainData;
            if (typeof blockchainData === 'string') {
              blockchainData = JSON.parse(blockchainData);
            }
            
            // Handle Solution 1: Server provides ALL 4 transactions
            const transactions = blockchainData.transactions || [];
            
            
            // Sign the transactions that require user signature
            const tSignStart = now();
            const signedTransactions = [];
            
            // Solution 1: Process all 4 transactions from server
            if (transactions.length === 4) {
              
              for (let i = 0; i < transactions.length; i++) {
                const txn = transactions[i];
                const needsSignature = txn.needs_signature || txn.needsSignature || false;
                const isSigned = txn.signed || false;
                const txnIndex = txn.index !== undefined ? txn.index : i;
                
                
                if (needsSignature && !isSigned) {
                  // User needs to sign this transaction (indexes 1 and 2)
                  
                  try {
                    // Get the actual transaction data
                    const txnData = txn.transaction;
                    
                    // Debug the transaction before signing
                    
                    // Decode transaction (base64 -> bytes)
                    const txnBytes = Uint8Array.from(Buffer.from(txnData, 'base64'));
                    
                    // Sign the transaction locally using deterministic wallet
                    const signedTxnBytes = await algorandService.signTransactionBytes(txnBytes);
                    const signedTxnB64 = Buffer.from(signedTxnBytes).toString('base64');
                    
                    signedTransactions.push({
                      index: txnIndex,
                      transaction: signedTxnB64
                    });
                  } catch (signError) {
                    throw new Error(`Failed to sign transaction ${txnIndex}: ${signError.message}`);
                  }
                } else {
                  // Already signed by sponsor (indexes 0 and 3) or doesn't need signature
                  
                  // The transaction data might already be the signed transaction bytes
                  // Check if it's already base64 or if it's raw bytes that need encoding
                  let txnData = txn.transaction;
                  
                  // If the transaction is already base64, use it as-is
                  // Otherwise it should be encoded properly by the server
                  
                  signedTransactions.push({
                    index: txnIndex,
                    transaction: txnData
                  });
                }
              }
            } else {
              // No 4-transaction group received              throw new Error(`Invalid transaction format: Expected 4 transactions, received ${transactions.length}`);
            }
            
            const tSignEnd = now();
            const tSubmitStart = now();
            try {
            } catch {}
            
            // Verify all transactions have valid base64
            for (const txn of signedTransactions) {
              try {
                const decoded = Buffer.from(txn.transaction, 'base64');
              } catch (e) {
              }
            }
            
            // Submit via WebSocket first
            const { submitViaWs } = await import('../services/payWs');
            const wsRes = await submitViaWs(signedTransactions, data.payInvoice.paymentTransaction.internalId);
            let submitResult: any = null;
            let tSubmitEnd = now();
            if (wsRes && (wsRes.transactionId || wsRes.transaction_id)) {
              try {
              } catch {}
              setIsComplete(true);
              setPaymentResponse({
                ...data.payInvoice,
                blockchainTxId: (wsRes as any).transactionId || (wsRes as any).transaction_id,
                blockchainRound: (wsRes as any).confirmedRound || (wsRes as any).confirmed_round
              });
              return;
            }

            // Fallback to GraphQL mutation
            submitResult = await apolloClient.mutate({
              mutation: SUBMIT_SPONSORED_PAYMENT,
              variables: {
                signedTransactions: JSON.stringify(signedTransactions),
                internalId: data.payInvoice.paymentTransaction.internalId
              }
            });
            tSubmitEnd = now();
            
            if (submitResult.data?.submitSponsoredPayment?.success) {
              try {
              } catch {}
              setIsComplete(true);
              setPaymentResponse({
                ...data.payInvoice,
                blockchainTxId: submitResult.data.submitSponsoredPayment.transactionId,
                blockchainRound: submitResult.data.submitSponsoredPayment.confirmedRound
              });
            } else {
              throw new Error(submitResult.data?.submitSponsoredPayment?.error || 'Failed to submit blockchain payment');
            }
          } catch (blockchainError: any) {
            // Show error - opt-ins should have been handled during invoice generation
            setPaymentError(`Error en el pago blockchain: ${blockchainError.message || 'Error desconocido'}`);
            setIsComplete(false);
            // Don't set payment response - payment failed
          }
        } else if (data?.payInvoice?.success) {
          // No blockchain data - database-only payment
          setIsComplete(true);
          setPaymentResponse(data.payInvoice);
        } else if (data?.payInvoice) {
          // Handle idempotency/atomic races by fetching existing payment and proceeding
          const errList: string[] = data.payInvoice.errors || [];
          const errText = (errList && errList.join(' ')) || '';
          const isIdempotencyOrAtomic = errText.includes('unique_payment_idempotency') || errText.toLowerCase().includes('atomic');
          if (isIdempotencyOrAtomic) {
            try {
              const { apolloClient } = await import('../apollo/client');
              const { GET_INVOICES } = await import('../apollo/queries');
              // Try a few quick attempts to pick up the created payment
              for (let i = 0; i < 3; i++) {
                const res = await apolloClient.query({ query: GET_INVOICES, fetchPolicy: 'network-only' });
                const inv = (res.data?.invoices || []).find((it: any) => it.invoiceId === transactionData.invoiceId);
                const pt = inv?.paymentTransactions?.find((p: any) => p && p.blockchainData && (p.blockchainData.transactions || p.blockchainData.transactions?.length));
                if (pt && pt.blockchainData && pt.blockchainData.transactions && pt.blockchainData.transactions.length === 4) {
                  // Reuse the signing+submit path with recovered data
                  let blockchainData = pt.blockchainData;
                  if (typeof blockchainData === 'string') {
                    try { blockchainData = JSON.parse(blockchainData); } catch {}
                  }
                  const transactions = blockchainData.transactions || [];
                  const internalId = pt.internalId;

                  // Sign needed transactions
                  const tSignStart = now();
                  const signedTransactions: any[] = [];
                  const algorandServiceModule = await import('../services/algorandService');
                  const algorandService = algorandServiceModule.default;
                  for (let j = 0; j < transactions.length; j++) {
                    const txn = transactions[j];
                    const needsSignature = txn.needs_signature || txn.needsSignature || false;
                    const isSigned = txn.signed || false;
                    const txnIndex = txn.index !== undefined ? txn.index : j;
                    if (needsSignature && !isSigned) {
                      const txnData = txn.transaction;
                      const txnBytes = Uint8Array.from(Buffer.from(txnData, 'base64'));
                      const signedTxnBytes = await algorandService.signTransactionBytes(txnBytes);
                      const signedTxnB64 = Buffer.from(signedTxnBytes).toString('base64');
                      signedTransactions.push({ index: txnIndex, transaction: signedTxnB64 });
                    } else {
                      signedTransactions.push({ index: txnIndex, transaction: txn.transaction });
                    }
                  }
                  const tSignEnd = now();
                  // Submit via WS first
                  const { submitViaWs } = await import('../services/payWs');
                  const tSubmitStart = now();
                  const wsRes = await submitViaWs(signedTransactions, internalId);
                  let tSubmitEnd = now();
                  if (wsRes && (wsRes.transactionId || wsRes.transaction_id)) {
                    try {
                    } catch {}
                    setIsComplete(true);
                    setPaymentResponse({ paymentTransaction: { internalId: internalId } });
                    return;
                  }
                  // Fallback HTTP GraphQL
                  const { apolloClient: apollo2 } = await import('../apollo/client');
                  const { SUBMIT_SPONSORED_PAYMENT } = await import('../apollo/mutations');
                  const submitResult = await apollo2.mutate({
                    mutation: SUBMIT_SPONSORED_PAYMENT,
                    variables: { signedTransactions: JSON.stringify(signedTransactions), internalId }
                  });
                  tSubmitEnd = now();
                  if (submitResult.data?.submitSponsoredPayment?.success) {
                    try {
                    } catch {}
                    setIsComplete(true);
                    setPaymentResponse({ paymentTransaction: { internalId: internalId } });
                    return;
                  }
                }
                // small delay before next attempt
                await new Promise(r => setTimeout(r, 250));
              }
            } catch (e) {
            }
          }
          // Fallback: show error
          setIsComplete(true);
          setPaymentResponse(data.payInvoice);
        } else {
          const errors = data?.payInvoice?.errors || ['Error desconocido'];          setPaymentError(errors.join(', '));
        }
        */
      } catch (error) {
        setPaymentError('Error al procesar el pago. Inténtalo de nuevo.');
      } finally {
        setIsProcessing(false);
      }
    };

    processPaymentWsOnly();
  }, [isValid, transactionData.internalId, bioChecked]);



  // Navigate to success screen after completion or handle errors
  useEffect(() => {
    if (isComplete || paymentError) {
      const successDelayMs = 0; // navigate immediately after submit
      const timer = setTimeout(() => {
        if (paymentError) {
          // Show error alert and navigate to home instead of going back
          Alert.alert(
            'Error en el Pago',
            paymentError,
            [
              {
                text: 'Entendido',
                onPress: () => {
                  // Navigate to home screen instead of going back
                  (navigation as any).navigate('BottomTabs', { screen: 'Home' });
                }
              }
            ]
          );
        } else {
          // Navigate to payment success screen
          // paymentResponse structure varies between WS-only (flat) and Mutation (nested)
          // valid paths: .blockchainTxId, .paymentTransaction.transactionHash, .transaction_id
          const rawHash =
            paymentResponse?.blockchainTxId ||
            paymentResponse?.paymentTransaction?.transactionHash ||
            paymentResponse?.transaction_id ||
            '';

          const isPlaceholderHash = rawHash.startsWith('pending_blockchain_') || rawHash.startsWith('temp_') || rawHash.toLowerCase() === 'pending';
          const txHash = isPlaceholderHash ? '' : rawHash;
          // Status is always SUBMITTED initially - blockchain confirmation comes later via Celery task
          const status = 'SUBMITTED';
          const successData = {
            type: 'payment',
            amount: transactionData.amount,
            currency: transactionData.currency,
            recipient: transactionData.merchant,
            merchant: transactionData.merchant,
            recipientAddress: '', // Will be filled by backend
            merchantAddress: '', // Will be filled by backend
            message: transactionData.message || '',
            address: transactionData.address || '',
            transactionHash: txHash,
            // Use undefined instead of empty string so QR code section properly hides when no internalId
            internalId: paymentResponse?.paymentTransaction?.internalId || undefined,
            status,
          };


          (navigation as any).navigate('PaymentSuccess', {
            transactionData: successData
          });
        }
      }, successDelayMs);

      return () => clearTimeout(timer);
    }
  }, [isComplete, paymentError, navigation, transactionData, paymentResponse]);

  // Prevent back navigation during processing
  useEffect(() => {
    const onBackPress = () => {
      // Block back navigation during processing to prevent double payments
      return true; // Return true to prevent default back behavior
    };

    // Add event listener for hardware back button
    const subscription = BackHandler.addEventListener('hardwareBackPress', onBackPress);

    // Cleanup function to remove event listener
    return () => {
      subscription.remove();
    };
  }, []);

  // Cleanup effect to reset state when screen unmounts
  useEffect(() => {
    return () => {
      setCurrentStep(0);
      setIsComplete(false);
      setIsProcessing(false);
      hasProcessedRef.current = false;
    };
  }, []);

  const spin = useMemo(
    () =>
      spinValue.interpolate({
        inputRange: [0, 1],
        outputRange: ['0deg', '360deg'],
      }),
    [spinValue]
  );

  // Don't render anything if not valid
  if (!isValid) {
    return null;
  }

  return (
    <SafeAreaView style={styles.container}>
      <ProcessingHero
        title={isComplete ? '¡Casi listo!' : transactionData.action}
        amount={`$${transactionData.amount} ${formatCurrency(transactionData.currency)}`}
        hint={`En ${transactionData.merchant}`}
        complete={isComplete}
      />

      {/* Current step: one quiet living line instead of the steps card */}
      {!isComplete && !paymentError && (
        <View style={styles.stepLine}>
          <Text style={styles.stepText}>{processingSteps[currentStep].text}</Text>
          <View style={styles.loadingDots}>
            <View style={styles.dot} />
            <View style={styles.dot} />
            <View style={styles.dot} />
          </View>
        </View>
      )}

      {paymentError && (
        <View style={styles.errorCard}>
          <Icon name="alert-circle" size={20} color={colors.error.icon} />
          <View style={{ flex: 1 }}>
            <Text style={styles.errorTitle}>Error en el pago</Text>
            <Text style={styles.errorText}>{paymentError}</Text>
            <Text style={styles.errorSubtext}>Redirigiendo de vuelta...</Text>
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
    </SafeAreaView>
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
  loadingDots: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  dot: {
    width: 5,
    height: 5,
    borderRadius: 2.5,
    backgroundColor: colors.primary,
  },
  errorCard: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginHorizontal: 24,
    marginTop: 12,
    backgroundColor: colors.error.background,
    borderWidth: 1,
    borderColor: colors.error.border,
    borderRadius: 12,
    padding: 14,
  },
  errorTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.error.text,
    marginBottom: 2,
  },
  errorText: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.error.text,
  },
  errorSubtext: {
    fontSize: 12,
    color: colors.error.text,
    opacity: 0.8,
    marginTop: 4,
  },
  securityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingBottom: 24,
    paddingHorizontal: 32,
  },
  securityText: {
    fontSize: 13,
    color: colors.text.secondary,
  },
});
