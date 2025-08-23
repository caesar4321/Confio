import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Dimensions,
  Animated,
  Easing,
  SafeAreaView,
  BackHandler,
  ScrollView,
  Alert,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { useMutation } from '@apollo/client';
import { PAY_INVOICE } from '../apollo/queries';
import { colors } from '../config/theme';
import { GET_INVOICES } from '../apollo/queries'; // Added this import for cache update
import { AccountManager } from '../utils/accountManager';

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
      invoiceId?: string;
      idempotencyKey?: string;
      preflight?: boolean;
    };
  };
}, 'PaymentProcessing'>;

const { width } = Dimensions.get('window');

export const PaymentProcessingScreen = () => {
  const navigation = useNavigation();
  const route = useRoute<PaymentProcessingRouteProp>();
  const [currentStep, setCurrentStep] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [paymentResponse, setPaymentResponse] = useState<any>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  
  // Generate idempotency key once per screen instance
  const idempotencyKeyRef = useRef<string | null>(null);
  const hasProcessedRef = useRef(false);
  const ranRef = useRef(false);
  
  // Generate unique idempotency key
  useEffect(() => {
    if (!idempotencyKeyRef.current) {
      const timestamp = Date.now();
      const random = Math.random().toString(36).substring(2, 15);
      idempotencyKeyRef.current = `pay_${timestamp}_${random}`;
    }
  }, []);

  // GraphQL mutation for paying invoice
  const [payInvoice] = useMutation(PAY_INVOICE, {
    update: (cache, { data }) => {
      if (data?.payInvoice?.success) {
        console.log('PaymentProcessingScreen: Updating Apollo cache after successful payment');
        
        // Update the GET_INVOICES query cache to reflect the new status
        try {
          const existingInvoices = cache.readQuery({ query: GET_INVOICES });
          if (existingInvoices && typeof existingInvoices === 'object' && 'invoices' in existingInvoices && Array.isArray(existingInvoices.invoices)) {
            const updatedInvoices = existingInvoices.invoices.map((invoice: any) => {
              if (invoice.invoiceId === transactionData.invoiceId) {
                return {
                  ...invoice,
                  status: 'PAID',
                  paidByUser: data.payInvoice.invoice.paidByUser,
                  paidAt: data.payInvoice.invoice.paidAt,
                  paymentTransactions: data.payInvoice.paymentTransaction ? [data.payInvoice.paymentTransaction] : []
                };
              }
              return invoice;
            });
            
            cache.writeQuery({
              query: GET_INVOICES,
              data: { invoices: updatedInvoices }
            });
            console.log('PaymentProcessingScreen: Cache updated successfully');
          }
        } catch (error) {
          console.log('PaymentProcessingScreen: Cache update error (non-critical):', error);
        }
      }
    }
  });

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
  console.log('PaymentProcessingScreen: Screen mounted', {
    amount: transactionData?.amount,
    currency: transactionData?.currency,
    merchant: transactionData?.merchant,
    hasInvoiceId: !!transactionData?.invoiceId,
    hasIdemKey: !!transactionData?.idempotencyKey,
  });

  // Safety check - if no transaction data, go back
  useEffect(() => {
    if (!isValid) {
      console.warn('PaymentProcessingScreen: Invalid transaction data, navigating back');
      navigation.goBack();
    }
  }, [isValid, navigation]);

  // Animation values
  const spinValue = new Animated.Value(0);
  const pulseValue = new Animated.Value(1);

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

  // Start spinning animation
  useEffect(() => {
    const spinAnimation = Animated.loop(
      Animated.timing(spinValue, {
        toValue: 1,
        duration: 2000,
        easing: Easing.linear,
        useNativeDriver: true,
      })
    );
    spinAnimation.start();

    return () => spinAnimation.stop();
  }, []);

  // Start pulse animation
  useEffect(() => {
    const pulseAnimation = Animated.loop(
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
    pulseAnimation.start();

    return () => pulseAnimation.stop();
  }, []);

  // Process payment when screen loads
  useEffect(() => {
    console.log('PaymentProcessingScreen: useEffect triggered', {
      isValid,
      hasInvoiceId: !!transactionData.invoiceId,
      invoiceId: transactionData.invoiceId,
      isProcessing,
      hasProcessedRef: hasProcessedRef.current,
      transactionData
    });
    
    if (!isValid || !transactionData.invoiceId || isProcessing || hasProcessedRef.current) {
      console.log('PaymentProcessingScreen: Returning early from useEffect', {
        reason: !isValid ? 'not valid' : 
                !transactionData.invoiceId ? 'no invoiceId' : 
                isProcessing ? 'already processing' : 
                'already processed'
      });
      return;
    }

    // Ensure this effect runs only once per mount
    if (ranRef.current) return;
    ranRef.current = true;

  const processPayment = async () => {
      if (isProcessing || hasProcessedRef.current) {
        console.log('PaymentProcessingScreen: Payment already in progress, skipping duplicate request');
        return;
      }
      
      hasProcessedRef.current = true;
      setIsProcessing(true);
      
      try {
        const now = () => (typeof performance !== 'undefined' && (performance as any).now ? (performance as any).now() : Date.now());
        const t0 = now();
        console.log('PaymentProcessingScreen: Starting payment processing for invoice:', transactionData.invoiceId);

        // If prepared transactions were provided by Confirmation, use them directly
        if (prepared && Array.isArray(prepared.transactions) && prepared.transactions.length === 4) {
          try {
            const algorandServiceModule = await import('../services/algorandService');
            const algorandService = algorandServiceModule.default;
            const { apolloClient } = await import('../apollo/client');
            const { SUBMIT_SPONSORED_PAYMENT } = await import('../apollo/mutations');

            console.log('PaymentProcessingScreen: Using prepared transactions from Confirmation');
            const transactions = prepared.transactions;
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
            const submitResult = await apolloClient.mutate({
              mutation: SUBMIT_SPONSORED_PAYMENT,
              variables: { signedTransactions: JSON.stringify(signedTransactions), paymentId: prepared.paymentId || transactionData.invoiceId }
            });
            if (!submitResult.data?.submitSponsoredPayment?.success) {
              throw new Error(submitResult.data?.submitSponsoredPayment?.error || 'Failed to submit blockchain payment');
            }
            console.log('PaymentProcessingScreen: Blockchain payment confirmed:', submitResult.data.submitSponsoredPayment);
            setIsComplete(true);
            setPaymentResponse({ blockchainTxId: submitResult.data.submitSponsoredPayment.transactionId, blockchainRound: submitResult.data.submitSponsoredPayment.confirmedRound });
            return;
          } catch (e) {
            console.error('PaymentProcessingScreen: Prepared path failed:', e);
            throw e;
          }
        }
        
        // Log current account context for debugging
        try {
          const accountManager = AccountManager.getInstance();
          const activeContext = await accountManager.getActiveAccountContext();
          console.log('PaymentProcessingScreen - Active account context:', {
            type: activeContext.type,
            index: activeContext.index,
            accountId: `${activeContext.type}_${activeContext.index}`
          });
        } catch (error) {
          console.log('PaymentProcessingScreen - Could not get account context:', error);
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
                  paymentTransactionId
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
            console.log('PaymentProcessingScreen: Found existing group; proceeding directly to signing');
            // Mimic the structure as if PayInvoice returned
            data = {
              payInvoice: {
                paymentTransaction: {
                  paymentTransactionId: candidate.paymentTransactionId,
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
          console.log('PaymentProcessingScreen: Calling payInvoice mutation with idempotency key:', idempotencyKey);
          const resp = await payInvoice({ variables: { invoiceId: transactionData.invoiceId, idempotencyKey } });
          data = resp.data;
        }
        const tCreateEnd = now();

        console.log('PaymentProcessingScreen: Mutation response received', {
          hasBlockchainData: !!data?.payInvoice?.paymentTransaction?.blockchainData,
          status: data?.payInvoice?.paymentTransaction?.status,
        });

        // Check if we have blockchain transactions to sign
        if (data?.payInvoice?.paymentTransaction?.blockchainData) {
          console.log('PaymentProcessingScreen: Blockchain transactions detected, proceeding with signing');
          
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
              console.log('PaymentProcessingScreen: OAuth pre-check failed (non-fatal):', oauthCheckErr);
            }
            
            // Parse blockchainData if it's a string (GraphQL returns it as JSON string)
            let blockchainData = data.payInvoice.paymentTransaction.blockchainData;
            if (typeof blockchainData === 'string') {
              console.log('PaymentProcessingScreen: Parsing blockchainData JSON string');
              blockchainData = JSON.parse(blockchainData);
            }
            
            // Handle Solution 1: Server provides ALL 4 transactions
            const transactions = blockchainData.transactions || [];
            
            console.log('PaymentProcessingScreen: Received transactions from server:', transactions.length);
            
            // Sign the transactions that require user signature
            const tSignStart = now();
            const signedTransactions = [];
            
            // Solution 1: Process all 4 transactions from server
            if (transactions.length === 4) {
              console.log('PaymentProcessingScreen: Using Solution 1 - all 4 transactions from server');
              
              for (let i = 0; i < transactions.length; i++) {
                const txn = transactions[i];
                const needsSignature = txn.needs_signature || txn.needsSignature || false;
                const isSigned = txn.signed || false;
                const txnIndex = txn.index !== undefined ? txn.index : i;
                
                console.log(`PaymentProcessingScreen: Tx ${txnIndex} - type: ${txn.type}, needsSignature: ${needsSignature}, signed: ${isSigned}`);
                
                if (needsSignature && !isSigned) {
                  // User needs to sign this transaction (indexes 1 and 2)
                  console.log(`PaymentProcessingScreen: Signing transaction at index ${txnIndex} (type: ${txn.type})`);
                  
                  try {
                    // Get the actual transaction data
                    const txnData = txn.transaction;
                    
                    // Debug the transaction before signing
                    console.log(`PaymentProcessingScreen: Tx ${txnIndex} base64 preview: ${String(txnData).substring(0, 20)}...`);
                    
                    // Decode transaction (base64 -> bytes)
                    const txnBytes = Uint8Array.from(Buffer.from(txnData, 'base64'));
                    console.log(`PaymentProcessingScreen: Tx ${txnIndex} decoded to ${txnBytes.length} bytes`);
                    
                    // Sign the transaction locally using deterministic wallet
                    const signedTxnBytes = await algorandService.signTransactionBytes(txnBytes);
                    const signedTxnB64 = Buffer.from(signedTxnBytes).toString('base64');
                    
                    signedTransactions.push({
                      index: txnIndex,
                      transaction: signedTxnB64
                    });
                  } catch (signError) {
                    console.error(`PaymentProcessingScreen: Failed to sign transaction ${txnIndex}:`, signError);
                    throw new Error(`Failed to sign transaction ${txnIndex}: ${signError.message}`);
                  }
                } else {
                  // Already signed by sponsor (indexes 0 and 3) or doesn't need signature
                  console.log(`PaymentProcessingScreen: Tx ${txnIndex} already signed or doesn't need signature (type: ${txn.type}, signed: ${isSigned})`);
                  
                  // The transaction data might already be the signed transaction bytes
                  // Check if it's already base64 or if it's raw bytes that need encoding
                  let txnData = txn.transaction;
                  
                  // If the transaction is already base64, use it as-is
                  // Otherwise it should be encoded properly by the server
                  console.log(`PaymentProcessingScreen: Using pre-signed transaction data for index ${txnIndex}`);
                  
                  signedTransactions.push({
                    index: txnIndex,
                    transaction: txnData
                  });
                }
              }
            } else {
              // No 4-transaction group received
              console.error('PaymentProcessingScreen: Invalid transaction count - expected 4 transactions');
              throw new Error(`Invalid transaction format: Expected 4 transactions, received ${transactions.length}`);
            }
            
            const tSignEnd = now();
            console.log('PaymentProcessingScreen: Submitting signed transactions to blockchain');
            const tSubmitStart = now();
            try {
              console.log('PaymentProcessingScreen: Signed transactions prepared', {
                count: signedTransactions.length,
                indexes: signedTransactions.map((t: any) => t.index)
              });
            } catch {}
            
            // Verify all transactions have valid base64
            for (const txn of signedTransactions) {
              try {
                const decoded = Buffer.from(txn.transaction, 'base64');
                console.log(`PaymentProcessingScreen: Tx ${txn.index} base64 valid (${decoded.length} bytes)`);
              } catch (e) {
                console.error(`PaymentProcessingScreen: Tx ${txn.index} has invalid base64`);
              }
            }
            
            // Submit the signed transactions
            // The mutation will detect if it's a 4-txn group (2 user transactions) and reconstruct sponsor transactions
            const submitResult = await apolloClient.mutate({
              mutation: SUBMIT_SPONSORED_PAYMENT,
              variables: {
                signedTransactions: JSON.stringify(signedTransactions),
                paymentId: data.payInvoice.paymentTransaction.paymentTransactionId
              }
            });
            const tSubmitEnd = now();
            
            if (submitResult.data?.submitSponsoredPayment?.success) {
              console.log('PaymentProcessingScreen: Blockchain payment confirmed:', submitResult.data.submitSponsoredPayment);
              try {
                console.log('[Payment][Perf]', {
                  create_ms: Math.round(tCreateEnd - tCreateStart),
                  sign_ms: Math.round(tSignEnd - tSignStart),
                  submit_ms: Math.round(tSubmitEnd - tSubmitStart),
                  total_ms: Math.round(tSubmitEnd - t0)
                });
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
            console.error('PaymentProcessingScreen: Blockchain payment failed:', blockchainError);
            // Show error - opt-ins should have been handled during invoice generation
            setPaymentError(`Error en el pago blockchain: ${blockchainError.message || 'Error desconocido'}`);
            setIsComplete(false);
            // Don't set payment response - payment failed
          }
        } else if (data?.payInvoice?.success) {
          // No blockchain data - database-only payment
          console.log('PaymentProcessingScreen: Database payment successful (no blockchain):', data.payInvoice);
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
                  console.log('PaymentProcessingScreen: Recovered existing payment after race; proceeding to sign');
                  // Reuse the signing+submit path with recovered data
                  let blockchainData = pt.blockchainData;
                  if (typeof blockchainData === 'string') {
                    try { blockchainData = JSON.parse(blockchainData); } catch {}
                  }
                  const transactions = blockchainData.transactions || [];
                  const paymentId = pt.paymentTransactionId;

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
                  // Submit
                  const { apolloClient: apollo2 } = await import('../apollo/client');
                  const { SUBMIT_SPONSORED_PAYMENT } = await import('../apollo/mutations');
                  const tSubmitStart = now();
                  const submitResult = await apollo2.mutate({
                    mutation: SUBMIT_SPONSORED_PAYMENT,
                    variables: { signedTransactions: JSON.stringify(signedTransactions), paymentId }
                  });
                  const tSubmitEnd = now();
                  if (submitResult.data?.submitSponsoredPayment?.success) {
                    console.log('PaymentProcessingScreen: Blockchain payment confirmed (recovered path):', submitResult.data.submitSponsoredPayment);
                    try {
                      console.log('[Payment][Perf]', {
                        create_ms: Math.round(tCreateEnd - tCreateStart),
                        sign_ms: Math.round(tSignEnd - tSignStart),
                        submit_ms: Math.round(tSubmitEnd - tSubmitStart),
                        total_ms: Math.round(tSubmitEnd - t0)
                      });
                    } catch {}
                    setIsComplete(true);
                    setPaymentResponse({ paymentTransaction: { paymentTransactionId: paymentId } });
                    return;
                  }
                }
                // small delay before next attempt
                await new Promise(r => setTimeout(r, 250));
              }
            } catch (e) {
              console.warn('PaymentProcessingScreen: Recovery after race failed:', e);
            }
          }
          // Fallback: show error
          console.log('PaymentProcessingScreen: Payment response received:', data.payInvoice);
          setIsComplete(true);
          setPaymentResponse(data.payInvoice);
        } else {
          const errors = data?.payInvoice?.errors || ['Error desconocido'];
          console.error('PaymentProcessingScreen: Payment failed:', errors);
          setPaymentError(errors.join(', '));
        }
      } catch (error) {
        console.error('PaymentProcessingScreen: Payment error:', error);
        setPaymentError('Error al procesar el pago. Inténtalo de nuevo.');
      } finally {
        setIsProcessing(false);
      }
    };

    processPayment();
  }, [isValid, transactionData.invoiceId, payInvoice]);



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
          const rawHash = paymentResponse?.paymentTransaction?.transactionHash || '';
          const isPlaceholderHash = rawHash.startsWith('pending_blockchain_') || rawHash.startsWith('temp_') || rawHash.toLowerCase() === 'pending';
          const txHash = isPlaceholderHash ? '' : rawHash;
          const status = txHash ? 'CONFIRMED' : 'SUBMITTED';
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
            paymentTransactionId: paymentResponse?.paymentTransaction?.paymentTransactionId || '',
            status,
          };
          
          console.log('PaymentProcessingScreen: Navigating to PaymentSuccess with data:', successData);
          
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
      console.log('PaymentProcessingScreen: Back button blocked during processing');
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
      console.log('PaymentProcessingScreen: Screen unmounting, cleaning up state');
      setCurrentStep(0);
      setIsComplete(false);
      setIsProcessing(false);
      hasProcessedRef.current = false;
    };
  }, []);

  const spin = spinValue.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  // Don't render anything if not valid
  if (!isValid) {
    return null;
  }

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView style={styles.scrollView} showsVerticalScrollIndicator={false}>
        {/* Processing Header */}
        <View style={[styles.header, { backgroundColor: colors.primary }]}>
          <View style={styles.headerContent}>
            {/* Processing Animation */}
            <View style={styles.processingIcon}>
              {!isComplete ? (
                <>
                  <Animated.View style={[styles.spinner, { transform: [{ rotate: spin }] }]}>
                    <Icon name="loader" size={48} color={colors.primary} />
                  </Animated.View>
                  <Animated.View 
                    style={[
                      styles.pulseEffect, 
                      { 
                        backgroundColor: colors.primary,
                        opacity: 0.2,
                        transform: [{ scale: pulseValue }]
                      }
                    ]} 
                  />
                </>
              ) : (
                <Icon name="check-circle" size={48} color={colors.primary} />
              )}
            </View>
            
            <Text style={styles.headerTitle}>
              {isComplete ? '¡Casi listo!' : transactionData.action}
            </Text>
            
            <Text style={styles.amountText}>
              ${transactionData.amount} {formatCurrency(transactionData.currency)}
            </Text>
            
            <Text style={styles.merchantText}>
              En {transactionData.merchant}
            </Text>
          </View>
        </View>

        {/* Processing Steps */}
        <View style={styles.content}>
        <View style={styles.stepsCard}>
          <View style={styles.stepsContainer}>
            {processingSteps.map((step, index) => (
              <View key={index} style={styles.stepRow}>
                {/* Step Icon */}
                <View style={[
                  styles.stepIcon,
                  { 
                    backgroundColor: index <= currentStep ? step.bgColor : '#F3F4F6',
                    transform: [{ scale: index === currentStep ? 1.1 : 1 }]
                  }
                ]}>
                  <Icon 
                    name={step.icon as any} 
                    size={24} 
                    color={index <= currentStep ? step.color : '#9CA3AF'} 
                  />
                </View>

                {/* Step Text */}
                <View style={styles.stepTextContainer}>
                  <Text style={[
                    styles.stepText,
                    { color: index <= currentStep ? '#1F2937' : '#9CA3AF' }
                  ]}>
                    {step.text}
                  </Text>
                  {index === currentStep && !isComplete && (
                    <View style={styles.loadingDots}>
                      <View style={styles.dot} />
                      <View style={styles.dot} />
                      <View style={styles.dot} />
                    </View>
                  )}
                </View>

                {/* Checkmark */}
                {index < currentStep && (
                  <Icon name="check-circle" size={20} color="#22C55E" />
                )}
                {index === currentStep && isComplete && (
                  <Icon name="check-circle" size={20} color="#22C55E" />
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
                  { 
                    backgroundColor: colors.primary,
                    width: `${((currentStep + 1) / processingSteps.length) * 100}%`
                  }
                ]} 
              />
            </View>
            <View style={styles.progressLabels}>
              <Text style={styles.progressLabel}>0%</Text>
              <Text style={styles.progressLabel}>50%</Text>
              <Text style={styles.progressLabel}>100%</Text>
            </View>
          </View>
        </View>

        {/* Security Message */}
        <View style={styles.securityCard}>
          <View style={styles.securityContent}>
            <Icon name="shield" size={20} color={colors.primary} />
            <Text style={styles.securityText}>
              <Text style={styles.securityBold}>Transacción segura</Text> • Protegido por blockchain
            </Text>
          </View>
        </View>

        {/* Processing Info */}
        <View style={styles.infoCard}>
          <View style={styles.infoContent}>
            <Icon name="clock" size={16} color="#059669" />
            <View style={styles.infoTextContainer}>
              <Text style={styles.infoTitle}>¿Sabías que...?</Text>
              <Text style={styles.infoText}>
                Confío cubre las comisiones de red para que puedas transferir dinero completamente gratis. 
                ¡Apoyamos a la comunidad venezolana! 🇻🇪
              </Text>
            </View>
          </View>
        </View>

        {/* Completion message */}
        {isComplete && (
          <View style={styles.completionCard}>
            <View style={styles.completionContent}>
              <Icon name="check-circle" size={32} color="#22C55E" />
              <Text style={styles.completionTitle}>¡Transacción completada!</Text>
              <Text style={styles.completionText}>Redirigiendo a confirmación...</Text>
            </View>
          </View>
        )}

        {/* Error message */}
        {paymentError && (
          <View style={styles.errorCard}>
            <View style={styles.errorContent}>
              <Icon name="alert-circle" size={32} color="#EF4444" />
              <Text style={styles.errorTitle}>Error en el pago</Text>
              <Text style={styles.errorText}>{paymentError}</Text>
              <Text style={styles.errorSubtext}>Redirigiendo de vuelta...</Text>
            </View>
          </View>
        )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  scrollView: {
    flex: 1,
  },
  header: {
    paddingTop: 48,
    paddingBottom: 48,
    paddingHorizontal: 16,
  },
  headerContent: {
    alignItems: 'center',
  },
  processingIcon: {
    width: 96,
    height: 96,
    backgroundColor: 'white',
    borderRadius: 48,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
    position: 'relative',
  },
  spinner: {
    position: 'absolute',
  },
  pulseEffect: {
    position: 'absolute',
    width: 96,
    height: 96,
    borderRadius: 48,
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 8,
  },
  amountText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: 'white',
    marginBottom: 16,
  },
  merchantText: {
    fontSize: 18,
    color: 'rgba(255,255,255,0.9)',
  },
  content: {
    flex: 1,
    paddingHorizontal: 16,
    marginTop: -32,
    paddingBottom: 40,
  },
  stepsCard: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 32,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
  },
  stepsContainer: {
    gap: 24,
  },
  stepRow: {
    flexDirection: 'row',
    alignItems: 'center',
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
  loadingDots: {
    flexDirection: 'row',
    marginTop: 4,
    gap: 4,
  },
  dot: {
    width: 8,
    height: 8,
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  progressContainer: {
    marginTop: 32,
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
  securityCard: {
    backgroundColor: 'white',
    borderRadius: 16,
    padding: 24,
    marginTop: 24,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 2,
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
    color: '#059669',
  },
  infoCard: {
    backgroundColor: '#ECFDF5',
    borderRadius: 16,
    padding: 16,
    marginTop: 16,
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
    color: '#065F46',
    fontWeight: '600',
    marginBottom: 4,
  },
  infoText: {
    fontSize: 12,
    color: '#047857',
  },
  completionCard: {
    backgroundColor: '#F0FDF4',
    borderRadius: 16,
    padding: 16,
    marginTop: 16,
    borderWidth: 1,
    borderColor: '#BBF7D0',
  },
  completionContent: {
    alignItems: 'center',
  },
  completionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#166534',
    marginTop: 8,
    marginBottom: 4,
  },
  completionText: {
    fontSize: 12,
    color: '#15803D',
  },
  errorCard: {
    backgroundColor: '#FEF2F2',
    borderRadius: 16,
    padding: 16,
    marginTop: 16,
    borderWidth: 1,
    borderColor: '#FECACA',
  },
  errorContent: {
    alignItems: 'center',
  },
  errorTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#DC2626',
    marginTop: 8,
    marginBottom: 4,
  },
  errorText: {
    fontSize: 14,
    color: '#DC2626',
    textAlign: 'center',
    marginBottom: 4,
  },
  errorSubtext: {
    fontSize: 12,
    color: '#EF4444',
  },
}); 
