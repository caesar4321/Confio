import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  StatusBar,
  SafeAreaView,
  TextInput,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Modal,
  TouchableWithoutFeedback,
  Keyboard,
  FlatList,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { formatLocalDate, formatLocalTime } from '../utils/dateUtils';
import { useMutation, useQuery } from '@apollo/client';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { MainStackParamList } from '../types/navigation';
import { useCurrency } from '../hooks/useCurrency';
import { useAuth } from '../contexts/AuthContext';
import { SEND_P2P_MESSAGE, GET_P2P_TRADE, GET_USER_BANK_ACCOUNTS, UPDATE_P2P_TRADE_STATUS, CONFIRM_P2P_TRADE_STEP } from '../apollo/queries';
import { ExchangeRateDisplay } from '../components/ExchangeRateDisplay';
import { useSelectedCountryRate } from '../hooks/useExchangeRate';
import { useCountry } from '../contexts/CountryContext';
import { getCurrencySymbol, getCurrencyForCountry } from '../utils/currencyMapping';
import { useAccountManager } from '../hooks/useAccountManager';
import { useAccount } from '../contexts/AccountContext';
import { useNumberFormat } from '../utils/numberFormatting';

type TradeChatRouteProp = RouteProp<MainStackParamList, 'TradeChat'>;
type TradeChatNavigationProp = NativeStackNavigationProp<MainStackParamList, 'TradeChat'>;

interface Message {
  id: number;
  sender: 'system' | 'trader' | 'user';
  text: string;
  timestamp: Date;
  type: 'system' | 'text' | 'payment_info';
}

interface Trader {
  name: string;
  isOnline: boolean;
  verified: boolean;
  lastSeen: string;
  responseTime: string;
}

interface TradeData {
  amount: string;
  crypto: string;
  totalBs: string;
  paymentMethod: string;
  rate: string;
}

export const TradeChatScreen: React.FC = () => {
  const navigation = useNavigation<TradeChatNavigationProp>();
  const route = useRoute<TradeChatRouteProp>();
  const { offer, crypto, amount, tradeType, tradeId, selectedPaymentMethodId, initialStep, tradeStatus } = route.params;
  const { userProfile } = useAuth();
  const { activeAccount, accounts, getActiveAccountContext } = useAccount();
  const { formatNumber, formatCurrency } = useNumberFormat();
  
  // Get the current active account context
  const [currentAccountContext, setCurrentAccountContext] = useState<any>(null);
  
  useEffect(() => {
    const loadAccountContext = async () => {
      const context = await getActiveAccountContext();
      setCurrentAccountContext(context);
      console.log('🔍 Loaded account context:', context);
      
      // Also log trade details to understand who is who
      if (tradeDetailsData?.p2pTrade) {
        const trade = tradeDetailsData.p2pTrade;
        console.log('📊 Trade participants:', {
          buyer: trade.buyer,
          buyerUser: trade.buyerUser,
          buyerBusiness: trade.buyerBusiness,
          seller: trade.seller,
          sellerUser: trade.sellerUser,
          sellerBusiness: trade.sellerBusiness,
          buyerType: trade.buyerType,
          sellerType: trade.sellerType,
          iAmBuyer: tradeType === 'buy',
          myRole: tradeType === 'buy' ? 'buyer' : 'seller'
        });
        
        // Log my current role in the trade
        console.log('🎭 My role in this trade:', {
          myUserId: userProfile?.id,
          myActiveAccountId: activeAccount?.id,
          myActiveAccountType: activeAccount?.type,
          myBusinessId: activeAccount?.business?.id,
          isPersonalAccount: activeAccount?.type === 'personal',
          isBusinessAccount: activeAccount?.type === 'business',
          tradeRole: tradeType
        });
      }
    };
    loadAccountContext();
  }, [tradeDetailsData, activeAccount, userProfile]);
  
  // Currency formatting
  const { formatAmount } = useCurrency();
  
  // Get current market exchange rate for comparison (based on selected country)
  const { rate: marketRate } = useSelectedCountryRate();
  
  // Get currency information
  const { selectedCountry } = useCountry();
  
  // Get currency directly from trade data
  const getCurrencyInfo = () => {
    // First check if we have currency from navigation params (most reliable for new trades)
    if (route.params?.tradeCurrencyCode) {
      const navCurrencyCode = route.params.tradeCurrencyCode;
      const navCurrencySymbol = getCurrencySymbol(navCurrencyCode);
      
      // Always show currency code instead of symbol to avoid confusion
      const displaySymbol = navCurrencyCode;
      
      console.log('💱 Currency from navigation params:', {
        currencyCode: navCurrencyCode,
        currencySymbol: displaySymbol,
        countryCode: route.params.tradeCountryCode,
        source: 'navigation params'
      });
      
      return { currencyCode: navCurrencyCode, currencySymbol: displaySymbol, source: 'navigation' };
    }
    
    // Use trade's currency if available from GraphQL query
    if (tradeDetailsData?.p2pTrade?.currencyCode) {
      const tradeCurrencyCode = tradeDetailsData.p2pTrade.currencyCode;
      const tradeCurrencySymbol = getCurrencySymbol(tradeCurrencyCode);
      
      // Always show currency code instead of symbol to avoid confusion
      const displaySymbol = tradeCurrencyCode;
      
      console.log('💱 Currency from trade query:', {
        currencyCode: tradeCurrencyCode,
        currencySymbol: displaySymbol,
        countryCode: tradeDetailsData.p2pTrade.countryCode,
        source: 'trade query'
      });
      
      return { currencyCode: tradeCurrencyCode, currencySymbol: displaySymbol, source: 'trade' };
    }
    
    // Fallback to offer's country if trade data not loaded yet
    const offerCountryCode = offer.countryCode;
    const tradeCountry = ['', '', offerCountryCode, ''];
    const currencyCode = getCurrencyForCountry(tradeCountry);
    const currencySymbol = getCurrencySymbol(currencyCode);
    
    // Always show currency code instead of symbol to avoid confusion
    const displaySymbol = currencyCode;
    
    console.log('💱 Currency from offer (fallback):', {
      offerCountryCode,
      currencyCode,
      currencySymbol: displaySymbol,
      source: 'offer fallback'
    });
    
    return { currencyCode, currencySymbol: displaySymbol, source: 'offer' };
  };
  
  const { currencyCode, currencySymbol } = getCurrencyInfo();
  
  // Fetch trade details
  const { data: tradeDetailsData, loading: tradeLoading, refetch: refetchTradeDetails } = useQuery(GET_P2P_TRADE, {
    variables: { id: tradeId },
    skip: !tradeId,
    fetchPolicy: 'cache-and-network',
    onCompleted: (data) => {
      console.log('🔍 Trade details loaded:', {
        tradeId,
        hasData: !!data?.p2pTrade,
        status: data?.p2pTrade?.status,
        offer: data?.p2pTrade?.offer,
        paymentMethod: data?.p2pTrade?.paymentMethod,
        offerCountryCode: data?.p2pTrade?.offer?.countryCode,
        tradeCountryCode: data?.p2pTrade?.countryCode,
        tradeCurrencyCode: data?.p2pTrade?.currencyCode,
        paymentMethodCountry: data?.p2pTrade?.paymentMethod?.bank?.country,
        fullData: data
      });
    }
  });
  
  // Fetch user's bank accounts - server determines context from JWT
  const { data: bankAccountsData, loading: bankAccountsLoading, error: bankAccountsError } = useQuery(GET_USER_BANK_ACCOUNTS, {
    fetchPolicy: 'network-only', // Force fresh data
    onCompleted: (data) => {
      console.log('✅ Bank accounts query completed');
      console.log('Number of bank accounts:', data?.userBankAccounts?.length || 0);
      if (data?.userBankAccounts) {
        data.userBankAccounts.forEach((account: any, index: number) => {
          console.log(`Bank account ${index + 1}:`, {
            id: account.id,
            paymentMethod: account.paymentMethod?.displayName,
            accountHolderName: account.accountHolderName,
            accountId: account.account?.id,
            accountType: account.account?.accountType
          });
        });
      }
    },
    onError: (error) => {
      console.error('❌ Bank accounts query error:', error);
    }
  });
  
  // Log query state
  useEffect(() => {
    console.log('Bank accounts query state:', {
      loading: bankAccountsLoading,
      error: bankAccountsError,
      hasData: !!bankAccountsData,
      dataLength: bankAccountsData?.userBankAccounts?.length
    });
  }, [bankAccountsLoading, bankAccountsError, bankAccountsData]);
  
  // Log the active account being used
  console.log('Active account for bank accounts query:', {
    id: activeAccount?.id,
    type: activeAccount?.type,
    name: activeAccount?.name,
    businessId: activeAccount?.business?.id,
    businessName: activeAccount?.business?.name,
    fullAccount: activeAccount
  });
  
  console.log('All accounts:', accounts);
  console.log('User profile:', userProfile);
  
  // Debug logs moved to useEffect to avoid render issues
  useEffect(() => {
    console.log('Trade type:', computedTradeType, '- User is:', computedTradeType === 'sell' ? 'seller' : 'buyer');
    console.log('🎯 Trade state:', {
      currentTradeStep,
      tradeType: computedTradeType,
      routeTradeType: tradeType,
      hasSharedPaymentDetails,
      tradeStatus: tradeDetailsData?.p2pTrade?.status,
      shouldShowMarkAsPaidButton: currentTradeStep === 2 && computedTradeType === 'buy',
      shouldShowReleaseFundsButton: currentTradeStep === 3 && computedTradeType === 'sell',
      forceUpdate,
      timestamp: new Date().toISOString()
    });
  }, [currentTradeStep, computedTradeType, tradeType, hasSharedPaymentDetails, tradeDetailsData?.p2pTrade?.status, forceUpdate]);
  
  // Helper function to get step from trade status
  const getStepFromStatus = (status: string) => {
    switch (status) {
      case 'PENDING': return 1;
      case 'PAYMENT_PENDING': return 2;
      case 'PAYMENT_SENT': return 3;
      case 'PAYMENT_CONFIRMED': return 4;
      case 'PAYMENT_RECEIVED': return 4;  // When seller confirms receipt
      case 'CRYPTO_RELEASED': return 4;   // When crypto is released
      case 'COMPLETED': return 4;
      case 'CANCELLED': return 1;
      default: return 1;
    }
  };
  
  const [message, setMessage] = useState('');
  const [currentTradeStep, setCurrentTradeStep] = useState(() => {
    // Initialize based on trade status if available
    if (tradeStatus) {
      return getStepFromStatus(tradeStatus);
    }
    return initialStep || 1;
  });
  const [hasSharedPaymentDetails, setHasSharedPaymentDetails] = useState(() => {
    // Initialize based on trade status if available
    if (tradeStatus) {
      return getStepFromStatus(tradeStatus) >= 2;
    }
    return false;
  });

  // State for computed trade type
  const [computedTradeType, setComputedTradeType] = useState(tradeType);
  const computedTradeTypeRef = useRef(tradeType);
  
  // Update ref whenever computedTradeType changes
  useEffect(() => {
    computedTradeTypeRef.current = computedTradeType;
  }, [computedTradeType]);
  
  // Update computed trade type when trade data loads
  useEffect(() => {
    if (!tradeDetailsData?.p2pTrade || !userProfile?.id) return;
    
    const trade = tradeDetailsData.p2pTrade;
    const myUserId = String(userProfile.id);
    
    // Check if I'm the buyer
    const iAmBuyer = (
      (trade.buyerUser && String(trade.buyerUser.id) === myUserId) ||
      (trade.buyer && String(trade.buyer.id) === myUserId)
    );
    
    // Check if I'm the seller
    const iAmSeller = (
      (trade.sellerUser && String(trade.sellerUser.id) === myUserId) ||
      (trade.seller && String(trade.seller.id) === myUserId)
    );
    
    const newComputedType = iAmBuyer ? 'buy' : iAmSeller ? 'sell' : tradeType;
    
    console.log('[TradeChatScreen] Computing trade type:', {
      myUserId,
      buyerUserId: trade.buyerUser?.id,
      sellerUserId: trade.sellerUser?.id,
      iAmBuyer,
      iAmSeller,
      oldType: computedTradeType,
      newType: newComputedType
    });
    
    if (newComputedType !== computedTradeType) {
      setComputedTradeType(newComputedType);
    }
  }, [tradeDetailsData?.p2pTrade, userProfile?.id]);

  // Update trade step when status changes from polling
  useEffect(() => {
    if (tradeDetailsData?.p2pTrade?.status) {
      const newStep = getStepFromStatus(tradeDetailsData.p2pTrade.status);
      console.log('[TradeChatScreen] Status update detected:', {
        status: tradeDetailsData.p2pTrade.status,
        currentStep: currentTradeStep,
        newStep,
        computedTradeType,
      });
      
      // Only update if step has changed
      if (newStep !== currentTradeStep) {
        setCurrentTradeStep(newStep);
        
        // Update payment details shared state based on new step
        if (newStep >= 2) {
          setHasSharedPaymentDetails(true);
        }
        
        // Force re-render of action buttons
        setForceUpdate(prev => prev + 1);
      }
    }
  }, [tradeDetailsData?.p2pTrade?.status]);
  const [forceUpdate, setForceUpdate] = useState(0); // Force update counter
  const [timeRemaining, setTimeRemaining] = useState(900); // 15 minutes in seconds
  const [messages, setMessages] = useState<Message[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [typingUser, setTypingUser] = useState<string | null>(null);
  const [isSecurityNoticeDismissed, setIsSecurityNoticeDismissed] = useState(false);
  const [showPaymentMethodSelector, setShowPaymentMethodSelector] = useState(false);
  
  // Check if trade is disputed
  const isTradeDisputed = tradeDetailsData?.p2pTrade?.status === 'DISPUTED' || tradeStatus === 'DISPUTED';
  const [availablePaymentAccounts, setAvailablePaymentAccounts] = useState<any[]>([]);

  const messagesListRef = useRef<FlatList>(null);
  const messageHandlerRef = useRef<(data: any) => void>();
  
  // GraphQL mutation for sending messages
  const [sendMessage, { loading: sendingMessage }] = useMutation(SEND_P2P_MESSAGE);
  
  // GraphQL mutation for updating trade status
  const [updateTradeStatus, { loading: updatingTradeStatus }] = useMutation(UPDATE_P2P_TRADE_STATUS, {
    update: (cache, { data }) => {
      if (data?.updateP2pTradeStatus?.trade) {
        // Update the GET_P2P_TRADE query in cache
        cache.modify({
          id: cache.identify({ __typename: 'P2PTrade', id: tradeId }),
          fields: {
            status: () => data.updateP2pTradeStatus.trade.status
          }
        });
      }
    }
  });
  
  // GraphQL mutation for confirming trade steps
  const [confirmTradeStep, { loading: confirmingTradeStep }] = useMutation(CONFIRM_P2P_TRADE_STEP, {
    update: (cache, { data }) => {
      if (data?.confirmP2pTradeStep?.trade) {
        // Update the GET_P2P_TRADE query in cache
        cache.modify({
          id: cache.identify({ __typename: 'P2PTrade', id: tradeId }),
          fields: {
            status: () => data.confirmP2pTradeStep.trade.status,
            escrow: () => data.confirmP2pTradeStep.trade.escrow
          }
        });
      }
    }
  });
  
  // WebSocket reference for real-time features
  const websocket = useRef<WebSocket | null>(null);
  
  // Sync trade step with actual trade status from server
  useEffect(() => {
    if (tradeDetailsData?.p2pTrade?.status) {
      const newStep = getStepFromStatus(tradeDetailsData.p2pTrade.status);
      console.log('📊 Syncing trade step with status:', {
        status: tradeDetailsData.p2pTrade.status,
        currentStep: currentTradeStep,
        newStep: newStep,
        tradeType: tradeType,
        isBuyer: tradeType === 'buy',
        shouldShowMarkAsPaidButton: newStep === 2 && tradeType === 'buy',
        shouldShowReleaseFundsButton: newStep === 3 && tradeType === 'sell',
        timestamp: new Date().toISOString()
      });
      
      // Use functional updates to ensure we're always working with latest state
      setCurrentTradeStep(prevStep => {
        if (prevStep !== newStep) {
          console.log('🔄 GraphQL sync: updating step from', prevStep, 'to', newStep);
        }
        return newStep;
      });
      
      // Always set hasSharedPaymentDetails if we're in step 2 or higher
      if (newStep >= 2) {
        setHasSharedPaymentDetails(prevShared => {
          if (!prevShared) {
            console.log('🔄 GraphQL sync: setting hasSharedPaymentDetails to true');
          }
          return true;
        });
      }
      
      // Force re-render
      setForceUpdate(prev => prev + 1);
    }
  }, [tradeDetailsData?.p2pTrade?.status]);

  // WebSocket connection for real-time updates
  useEffect(() => {
    if (!tradeId) {
      return;
    }

    const connectWebSocket = async () => {
      try {
        console.log('🔄 Connecting to WebSocket for real-time updates...');
        
        // Get JWT token from Keychain
        const Keychain = require('react-native-keychain');
        const { AUTH_KEYCHAIN_SERVICE, AUTH_KEYCHAIN_USERNAME } = require('../services/authService');
        
        const credentials = await Keychain.getGenericPassword({
          service: AUTH_KEYCHAIN_SERVICE,
          username: AUTH_KEYCHAIN_USERNAME
        });
        
        let token = '';
        if (credentials) {
          try {
            const tokens = JSON.parse(credentials.password);
            token = tokens.accessToken || '';
          } catch (error) {
            console.error('❌ Error parsing tokens for WebSocket:', error);
          }
        }
        
        if (!token) {
          console.error('❌ No JWT token available');
          setIsConnected(false);
          return;
        }
        
        // Use the raw WebSocket endpoint for real-time updates
        const apiUrl = require('../config/env').getApiUrl();
        const wsBaseUrl = apiUrl.replace('http://', 'ws://').replace('https://', 'wss://').replace('/graphql/', '/');
        
        // JWT token now contains account context securely
        const wsUrl = `${wsBaseUrl}ws/trade/${tradeId}/?token=${encodeURIComponent(token)}`;
        
        console.log('🔌 WebSocket URL with JWT auth:', wsUrl.replace(token, 'TOKEN_HIDDEN'));
        
        websocket.current = new WebSocket(wsUrl);
        
        websocket.current.onopen = () => {
          console.log('✅ WebSocket connected for trade:', tradeId);
          setIsConnected(true);
        };
        
        websocket.current.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            console.log('📨 WebSocket message received:', {
              type: data.type,
              data: data,
              timestamp: new Date().toISOString()
            });
            // Use the ref to call the latest version of the handler
            if (messageHandlerRef.current) {
              messageHandlerRef.current(data);
            }
          } catch (error) {
            console.error('❌ Error parsing WebSocket message:', error);
          }
        };
        
        websocket.current.onclose = (event) => {
          console.log('❌ WebSocket disconnected:', event.code, event.reason);
          setIsConnected(false);
          
          // Reconnect if not a deliberate close
          if (event.code !== 1000) {
            setTimeout(() => {
              if (!websocket.current || websocket.current.readyState === WebSocket.CLOSED) {
                connectWebSocket();
              }
            }, 3000);
          }
        };
        
        websocket.current.onerror = (error) => {
          console.error('❌ WebSocket error:', error);
          setIsConnected(false);
        };
        
      } catch (error) {
        console.error('Failed to create WebSocket connection:', error);
      }
    };

    connectWebSocket();

    // Cleanup on unmount
    return () => {
      if (websocket.current) {
        websocket.current.close();
      }
    };
  }, [tradeId, activeAccount?.id]);

  // Update the message handler ref on every render to avoid stale closures
  messageHandlerRef.current = (data: any) => {
    // Helper function to determine if message is from current user's perspective
    const isMessageFromCurrentUser = (senderId: number | string, senderBusinessId?: number | string) => {
      // Convert IDs to strings for consistent comparison
      const senderIdStr = String(senderId);
      const senderBusinessIdStr = senderBusinessId ? String(senderBusinessId) : undefined;
      const userProfileIdStr = userProfile?.id ? String(userProfile.id) : '';
      
      // Get active account info
      if (!activeAccount) {
        console.warn('No active account available for message sender check');
        return false;
      }
      
      console.log('🎯 Checking message sender:', {
        activeAccountType: activeAccount.type,
        activeAccountId: activeAccount.id,
        activeBusinessId: activeAccount.business?.id,
        senderId: senderIdStr,
        senderBusinessId: senderBusinessIdStr,
        userProfileId: userProfileIdStr,
        isPersonalMatch: activeAccount.type === 'personal' && senderIdStr === userProfileIdStr && !senderBusinessIdStr,
        isBusinessMatch: activeAccount.type === 'business' && senderBusinessIdStr === String(activeAccount.business?.id)
      });
      
      // For business accounts
      if (activeAccount.type === 'business' && activeAccount.business?.id) {
        // Message is from current user if sender business ID matches active business ID
        return senderBusinessIdStr === String(activeAccount.business.id);
      }
      
      // For personal accounts
      if (activeAccount.type === 'personal') {
        // Message is from current user if sender ID matches user profile ID and no business ID
        return senderIdStr === userProfileIdStr && !senderBusinessIdStr;
      }
      
      return false;
    };
    
    switch (data.type) {
      case 'chat_history':
        console.log('📜 Received chat history:', data.messages.length, 'messages');
        data.messages.forEach((msg: any, idx: number) => {
          console.log(`Message ${idx}:`, {
            senderId: msg.sender.id,
            senderBusinessId: msg.sender.businessId,
            senderType: msg.sender.type,
            isFromCurrentUser: isMessageFromCurrentUser(msg.sender.id, msg.sender.businessId)
          });
        });
        const mappedMessages = data.messages.map((msg: any) => ({
          id: msg.id,
          sender: isMessageFromCurrentUser(msg.sender.id, msg.sender.businessId) ? 'user' : 'trader',
          text: msg.content,
          timestamp: new Date(msg.createdAt),
          type: msg.messageType.toLowerCase()
        }));
        
        // Reverse messages for inverted FlatList (newest first)
        const reversedMessages = [...mappedMessages].reverse();
        
        console.log('📊 Setting messages from chat history:', {
          messageCount: reversedMessages.length,
          firstMessage: reversedMessages[0]?.text?.substring(0, 50),
          lastMessage: reversedMessages[reversedMessages.length - 1]?.text?.substring(0, 50),
          firstTimestamp: reversedMessages[0]?.timestamp,
          lastTimestamp: reversedMessages[reversedMessages.length - 1]?.timestamp,
          reversed: true
        });
        
        setMessages(reversedMessages);
        break;
        
      case 'chat_message':
        console.log('💬 New message received:', {
          senderId: data.message.sender.id,
          senderBusinessId: data.message.sender.businessId,
          senderType: data.message.sender.type,
          isFromCurrentUser: isMessageFromCurrentUser(data.message.sender.id, data.message.sender.businessId)
        });
        const newMessage: Message = {
          id: data.message.id,
          sender: isMessageFromCurrentUser(data.message.sender.id, data.message.sender.businessId) ? 'user' : 'trader',
          text: data.message.content,
          timestamp: new Date(data.message.createdAt),
          type: data.message.messageType.toLowerCase()
        };
        
        setMessages(prev => {
          // Check if message already exists (prevent duplicates)
          const exists = prev.some(msg => msg.id === newMessage.id);
          if (exists) return prev;
          // Add new message at the beginning (messages are in descending order for inverted FlatList)
          return [newMessage, ...prev];
        });
        break;
        
      case 'typing_indicator':
        if (data.user_id !== userProfile?.id) {
          setTypingUser(data.is_typing ? data.username : null);
        }
        break;
        
      case 'trade_status_update':
        console.log('🔄 Trade status updated via WebSocket:', {
          fullData: data,
          status: data.status,
          currentTradeStep,
          computedTradeType,
          routeTradeType: tradeType,
          updatedBy: data.updated_by,
          myUserId: userProfile?.id,
          isOtherUserUpdate: data.updated_by !== String(userProfile?.id)
        });
        
        // Update the local state with the new status
        if (data.status) {
          const newStep = getStepFromStatus(data.status);
          console.log('📊 Calculating new step:', {
            receivedStatus: data.status,
            newStep,
            currentStep: currentTradeStep,
            willUpdate: newStep !== currentTradeStep,
            computedTradeType: computedTradeTypeRef.current,
            shouldShowMarkAsPaid: newStep === 2 && computedTradeTypeRef.current === 'buy',
            shouldShowReleaseFunds: newStep === 3 && computedTradeTypeRef.current === 'sell'
          });
          
          // Update states using functional updates to ensure we get the latest values
          setCurrentTradeStep(prevStep => {
            console.log('✅ Updating trade step from WebSocket:', prevStep, '->', newStep);
            return newStep;
          });
          
          // Always update hasSharedPaymentDetails if in step 2+
          if (newStep >= 2) {
            setHasSharedPaymentDetails(prevShared => {
              console.log('✅ Setting hasSharedPaymentDetails to true (was:', prevShared, ')');
              return true;
            });
          }
          
          // Force a re-render to ensure UI updates
          setForceUpdate(prev => prev + 1);
          
          // Log button visibility after state updates
          setTimeout(() => {
            console.log('🔘 Button visibility check after WebSocket update:', {
              step: currentTradeStep,
              type: computedTradeTypeRef.current,
              shouldShowMarkAsPaid: currentTradeStep === 2 && computedTradeTypeRef.current === 'buy',
              shouldShowReleaseFunds: currentTradeStep === 3 && computedTradeTypeRef.current === 'sell',
              forceUpdate: forceUpdate,
              timestamp: new Date().toISOString()
            });
          }, 100);
            
          // Add a system message for status changes
          // Show message even if we initiated it, as other user needs to see the update
          let systemText = '';
          switch (data.status) {
            case 'PAYMENT_PENDING':
              systemText = '💳 El vendedor ha compartido los datos de pago.';
              break;
            case 'PAYMENT_SENT':
              systemText = '✅ El comprador ha marcado el pago como enviado.';
              break;
            case 'PAYMENT_CONFIRMED':
              systemText = '🎉 El vendedor ha confirmado la recepción del pago.';
              break;
            case 'COMPLETED':
              systemText = '✅ Intercambio completado exitosamente.';
              break;
            case 'DISPUTED':
              systemText = '⚠️ Este intercambio ha sido reportado y está en disputa. Un moderador revisará el caso.';
              break;
          }
          
          if (systemText) {
            const systemMessage: Message = {
              id: Date.now() + Math.random(),
              sender: 'system',
              text: systemText,
              timestamp: new Date(),
              type: 'system',
            };
            setMessages(prev => [systemMessage, ...prev]);
          }
          
          // Navigate both buyer and seller to rating screen when trade is completed
          if ((data.status === 'PAYMENT_CONFIRMED' || data.status === 'COMPLETED') && data.updated_by !== String(userProfile?.id)) {
            // This is the person receiving the completion notification
            setTimeout(() => {
              const tradeData = tradeDetailsData?.p2pTrade;
              
              // Determine who is rating whom based on the current user's role
              const iAmBuyer = tradeType === 'buy';
              const counterpartyInfo = iAmBuyer 
                ? (tradeData?.sellerUser || tradeData?.seller) 
                : (tradeData?.buyerUser || tradeData?.buyer);
              
              // Get the actual stats for the counterparty
              const counterpartyStats = iAmBuyer 
                ? tradeData?.sellerStats 
                : tradeData?.buyerStats;
              
              console.log('🎯 Rating navigation - Stats debug:', {
                iAmBuyer,
                tradeType,
                buyerInfo: tradeData?.buyer,
                sellerInfo: tradeData?.seller,
                buyerStats: tradeData?.buyerStats,
                sellerStats: tradeData?.sellerStats,
                counterpartyStats,
                offerStats: tradeData?.offer?.userStats,
              });
              
              // Use the stats if available, otherwise fallback to default
              const stats = counterpartyStats || {
                isVerified: false,
                completedTrades: 0,
                successRate: 0,
              };
              
              // If I'm the buyer, I rate the seller. If I'm the seller, I rate the buyer.
              const ratingTargetName = iAmBuyer ? 'vendedor' : 'comprador';
              
              // Check if already rated
              if (tradeData?.hasRating) {
                Alert.alert('Ya calificado', 'Ya has calificado este intercambio.');
                return;
              }
              
              navigation.navigate('TraderRating', {
                tradeId,
                trader: {
                  name: iAmBuyer 
                    ? (tradeData?.sellerDisplayName || `${counterpartyInfo?.firstName || ''} ${counterpartyInfo?.lastName || ''}`.trim() || counterpartyInfo?.username || 'Vendedor')
                    : (tradeData?.buyerDisplayName || `${counterpartyInfo?.firstName || ''} ${counterpartyInfo?.lastName || ''}`.trim() || counterpartyInfo?.username || 'Comprador'),
                  verified: stats.isVerified || false,
                  completedTrades: stats.completedTrades || 0,
                  successRate: stats.successRate || 0,
                },
                tradeDetails: {
                  amount: amount,
                  crypto: crypto,
                  totalPaid: (parseFloat(amount) * parseFloat(offer.rate)).toFixed(2),
                  method: tradeData?.paymentMethod?.displayName || 'N/A',
                  date: formatLocalDate(new Date().toISOString()),
                  duration: `${Math.floor((900 - timeRemaining) / 60)} minutos`,
                }
              });
            }, 2000); // Give time to see the completion message
          }
          
          // Always refetch to ensure all data is synced
          if (refetchTradeDetails) {
            console.log('🔄 Refetching trade details after WebSocket update');
            refetchTradeDetails();
          }
          
          // Force a re-render to update button visibility immediately
          // This ensures the UI updates even if the user initiated the change
          console.log('🎯 After WebSocket update - Button visibility check:', {
            currentTradeStep: newStep,
            tradeType,
            hasSharedPaymentDetails: newStep >= 2,
            shouldShowMarkAsPaidButton: newStep === 2 && tradeType === 'buy',
            shouldShowReleaseFundsButton: newStep === 3 && tradeType === 'sell',
            timestamp: new Date().toISOString()
          });
          
        }
        break;
        
      case 'error':
        console.error('WebSocket error:', data.message);
        break;
    }
  };
  
  // Mock data for development when no tradeId
  useEffect(() => {
    if (!tradeId) {
      console.warn('No tradeId provided, using mock data');
      setMessages([
        // Messages in descending order (newest first) for inverted FlatList
        {
          id: 7,
          sender: 'trader',
          text: '📋 Datos de Pago - Banco de Venezuela\n\n👤 Titular: Juan Pérez\n🏦 Banco: Banco de Venezuela\n💳 Número de cuenta: 0102-1234-5678-9012\n📝 Tipo de cuenta: Corriente\n🆔 Cédula: V-12.345.678',
          timestamp: new Date(Date.now() - 150000),
          type: 'payment_info'
        },
        {
          id: 6,
          sender: 'system',
          text: '💳 Datos de pago compartidos',
          timestamp: new Date(Date.now() - 180000),
          type: 'system'
        },
        {
          id: 5,
          sender: 'user',
          text: 'Gracias, reviso y te aviso.',
          timestamp: new Date(Date.now() - 200000),
          type: 'text'
        },
        {
          id: 4,
          sender: 'trader',
          text: 'Te envío los datos bancarios por aquí.',
          timestamp: new Date(Date.now() - 210000),
          type: 'text'
        },
        {
          id: 3,
          sender: 'user',
          text: 'Perfecto, estoy listo para hacer el pago.',
          timestamp: new Date(Date.now() - 240000),
          type: 'text'
        },
        {
          id: 2,
          sender: 'trader',
          text: '¡Hola! Gracias por elegir mi oferta. Te envío los datos para el pago.',
          timestamp: new Date(Date.now() - 270000),
          type: 'text'
        },
        {
          id: 1,
          sender: 'system',
          text: 'Intercambio iniciado. Tienes 15 minutos para completar el pago.',
          timestamp: new Date(Date.now() - 300000),
          type: 'system'
        }
      ]);
      setIsConnected(false);
    }
  }, [tradeId]);

  // Send typing indicator via WebSocket
  const sendTypingIndicator = (isTyping: boolean) => {
    if (websocket.current && websocket.current.readyState === WebSocket.OPEN) {
      websocket.current.send(JSON.stringify({
        type: 'typing',
        isTyping: isTyping
      }));
    }
    setIsTyping(isTyping);
  };

  // Trader data from route params
  const trader: Trader = {
    name: offer.name,
    isOnline: offer.isOnline,
    verified: offer.userStats?.isVerified || false, // Use real verification status from userStats
    lastSeen: offer.lastSeen,
    responseTime: offer.responseTime
  };

  // Trade data calculated from route params
  const fiatAmount = parseFloat(amount) * parseFloat(offer.rate);
  // Fix crypto display format
  const displayCrypto = crypto === 'CUSD' ? 'cUSD' : crypto;
  
  // Get payment method name from route params
  // Handle both object and string formats for payment methods
  const selectedPaymentMethod = selectedPaymentMethodId 
    ? offer.paymentMethods.find(pm => typeof pm === 'object' ? pm.id === selectedPaymentMethodId : false)
    : offer.paymentMethods[0];
    
  // Extract payment method name handling both string and object formats
  const paymentMethodName = typeof selectedPaymentMethod === 'string' 
    ? selectedPaymentMethod 
    : (selectedPaymentMethod?.displayName || selectedPaymentMethod?.name || 'Unknown');
  
  // Get the currency directly from trade data
  const displayCurrencyCode = tradeDetailsData?.p2pTrade?.currencyCode || currencyCode;
  // Always show currency code instead of symbol to avoid confusion
  const displayCurrencySymbol = displayCurrencyCode;
  
  console.log('💱 Currency determination:', {
    tradeCountryCode: tradeDetailsData?.p2pTrade?.countryCode,
    tradeCurrencyCode: tradeDetailsData?.p2pTrade?.currencyCode,
    displayCurrencyCode,
    displayCurrencySymbol,
    source: tradeDetailsData?.p2pTrade?.currencyCode ? 'trade' : 'fallback'
  });
  
  const tradeData: TradeData = {
    amount: amount,
    crypto: displayCrypto,
    totalBs: `${displayCurrencySymbol} ${formatNumber(fiatAmount)}`, // Use user's locale formatting
    paymentMethod: paymentMethodName,
    rate: offer.rate
  };

  // Timer effect
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeRemaining(prev => {
        if (prev <= 1) {
          clearInterval(timer);
          Alert.alert('Tiempo Expirado', 'El tiempo para completar el pago ha expirado.');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  // Monitor trade status for dispute
  useEffect(() => {
    if (tradeDetailsData?.p2pTrade?.status === 'DISPUTED' && !isTradeDisputed) {
      // Add system message when trade becomes disputed
      const systemMessage: Message = {
        id: Date.now() + Math.random(),
        sender: 'system',
        text: '⚠️ Este intercambio ha sido reportado y está en disputa. Un moderador revisará el caso.',
        timestamp: new Date(),
        type: 'system',
      };
      setMessages(prev => [systemMessage, ...prev]);
    }
  }, [tradeDetailsData?.p2pTrade?.status, isTradeDisputed]);

  // Debug messages state
  useEffect(() => {
    console.log('📨 Messages updated:', messages.length, 'messages');
    console.log('📨 Current user ID:', userProfile?.id);
    messages.forEach((msg, index) => {
      console.log(`📨 Message ${index}:`, {
        id: msg.id,
        sender: msg.sender,
        text: msg.text.substring(0, 30) + '...',
        isUser: msg.sender === 'user'
      });
    });
  }, [messages]);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => {
        messagesListRef.current?.scrollToEnd({ animated: true });
      }, 100);
    }
  }, [messages]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
  };

  const getStepText = (step: number) => {
    const steps: { [key: number]: string } = {
      1: "Realizar pago",
      2: "Confirmar pago", 
      3: "Esperando verificación",
      4: "Completado"
    };
    return steps[step] || "En proceso";
  };

  const handleGoBack = () => {
    // Navigate back to Exchange screen with active trades tab
    navigation.navigate('BottomTabs', { screen: 'Exchange' });
  };

  const handleAbandonTrade = () => {
    Alert.alert(
      '¿Abandonar intercambio?',
      'Esta acción cancelará el intercambio y no podrás recuperarlo. ¿Estás seguro?',
      [
        {
          text: 'Cancelar',
          style: 'cancel',
        },
        {
          text: 'Abandonar',
          style: 'destructive',
          onPress: () => {
            // Here you would typically call an API to cancel the trade
            Alert.alert('Intercambio cancelado', 'El intercambio ha sido cancelado.');
            navigation.navigate('BottomTabs', { screen: 'Exchange' });
          },
        },
      ]
    );
  };

  const handleViewTrade = () => {
    // Navigate to trade details or back to exchange
    navigation.navigate('BottomTabs', { screen: 'Exchange' });
  };

  const [showConfirmPaidModal, setShowConfirmPaidModal] = useState(false);

  const handleMarkAsPaid = () => {
    setShowConfirmPaidModal(true);
  };
  
  const handleSharePaymentDetails = async () => {
    try {
      console.log('=== SHARE PAYMENT DETAILS DEBUG ===');
      console.log('Trade details data:', tradeDetailsData);
      console.log('Selected payment method ID from route:', selectedPaymentMethodId);
      console.log('Offer from route:', offer);
      
      // Get the payment method from the trade or from the selected ID
      let paymentMethod = tradeDetailsData?.p2pTrade?.paymentMethod;
      
      // If not in trade details, find from offer using selectedPaymentMethodId
      if (!paymentMethod && selectedPaymentMethodId && offer.paymentMethods) {
        paymentMethod = offer.paymentMethods.find(pm => pm.id === selectedPaymentMethodId);
      }
      
      // Fallback to first payment method if still not found
      if (!paymentMethod && offer.paymentMethods && offer.paymentMethods.length > 0) {
        paymentMethod = offer.paymentMethods[0];
      }
      
      console.log('Payment method resolved to:', paymentMethod);
      console.log('Bank accounts loading:', bankAccountsLoading);
      console.log('Bank accounts error:', bankAccountsError);
      console.log('Bank accounts data:', bankAccountsData);
      
      if (!paymentMethod) {
        Alert.alert('Error', 'No se encontró el método de pago');
        return;
      }
      
      // Log all user's payment methods for debugging
      console.log('User payment methods:');
      bankAccountsData?.userBankAccounts?.forEach((account: any) => {
        console.log(`  - ${account.paymentMethod?.displayName} (ID: ${account.paymentMethod?.id}, Name: ${account.paymentMethod?.name})`);
      });
      
      console.log('Looking for payment method:', {
        id: paymentMethod.id,
        name: paymentMethod.name,
        displayName: paymentMethod.displayName
      });
      
      // Find all user's bank accounts for this payment method
      // Try matching by ID first, then by name as fallback
      const matchingAccounts = bankAccountsData?.userBankAccounts?.filter(
        (account: any) => {
          const matchById = account.paymentMethod?.id === paymentMethod.id;
          const matchByName = account.paymentMethod?.name === paymentMethod.name;
          console.log(`Checking account ${account.paymentMethod?.displayName}:`, {
            matchById,
            matchByName,
            accountPmId: account.paymentMethod?.id,
            accountPmName: account.paymentMethod?.name,
            targetPmId: paymentMethod.id,
            targetPmName: paymentMethod.name
          });
          return matchById || matchByName;
        }
      ) || [];
      
      if (matchingAccounts.length === 0) {
        Alert.alert('Error', `No tienes configurado el método de pago: ${paymentMethod.displayName || paymentMethod.name}`);
        return;
      }
      
      // If multiple accounts exist for the same payment method, show selector
      if (matchingAccounts.length > 1) {
        setAvailablePaymentAccounts(matchingAccounts);
        setShowPaymentMethodSelector(true);
        return;
      }
      
      // If only one account, use it directly
      const userBankAccount = matchingAccounts[0];
      
      // Share the payment details directly with the single account
      await sharePaymentDetailsWithAccount(userBankAccount);
      
    } catch (error) {
      console.error('Error sharing payment details:', error);
      Alert.alert('Error', 'No se pudieron compartir los datos de pago');
    }
  };

  const sharePaymentDetailsWithAccount = async (userBankAccount: any) => {
    try {
      // First, update the trade status to PAYMENT_PENDING
      const { data: updateData } = await updateTradeStatus({
        variables: {
          input: {
            tradeId: tradeId,
            status: 'PAYMENT_PENDING',
            paymentNotes: 'Datos de pago compartidos por el vendedor'
          }
        }
      });
      
      if (!updateData?.updateP2pTradeStatus?.success) {
        const errorMessage = updateData?.updateP2pTradeStatus?.errors?.join(', ') || 'Error al actualizar el estado';
        Alert.alert('Error', errorMessage);
        return;
      }
      
      const paymentMethod = userBankAccount.paymentMethod;
      
      // Format the payment details
      let paymentDetails = `📋 Datos de Pago - ${paymentMethod.displayName || paymentMethod.name}\n\n`;
      paymentDetails += `👤 Titular: ${userBankAccount.accountHolderName}\n`;
      
      // Check provider type from either source
      const providerType = paymentMethod.providerType || userBankAccount.paymentMethod?.providerType;
      
      if (providerType === 'bank' && userBankAccount.accountNumber) {
        paymentDetails += `🏦 Banco: ${userBankAccount.bank?.name || paymentMethod.bank?.name || userBankAccount.paymentMethod?.bank?.name}\n`;
        paymentDetails += `💳 Número de cuenta: ${userBankAccount.accountNumber}\n`;
        if (userBankAccount.accountType) {
          paymentDetails += `📝 Tipo de cuenta: ${userBankAccount.accountType}\n`;
        }
      }
      
      // For fintech like DaviPlata, always show phone if available
      if (userBankAccount.phoneNumber) {
        paymentDetails += `📱 Teléfono: ${userBankAccount.phoneNumber}\n`;
      }
      
      if (userBankAccount.email) {
        paymentDetails += `📧 Email: ${userBankAccount.email}\n`;
      }
      
      if (userBankAccount.username) {
        paymentDetails += `👤 Usuario: ${userBankAccount.username}\n`;
      }
      
      if (userBankAccount.identificationNumber) {
        const identificationLabel = userBankAccount.country?.identificationName || 'Identificación';
        paymentDetails += `🆔 ${identificationLabel}: ${userBankAccount.identificationNumber}\n`;
      }
      
      console.log('=== PAYMENT DETAILS TO SEND ===');
      console.log(paymentDetails);
      console.log('=== END PAYMENT DETAILS ===');
      
      // Send the payment details as a message
      await sendMessage({
        variables: {
          input: {
            tradeId: tradeId,
            content: paymentDetails,
            messageType: 'TEXT'
          }
        }
      });
      
      // Update local state to reflect new status
      setCurrentTradeStep(2);
      setHasSharedPaymentDetails(true);
      
      // Close selector modal if open
      setShowPaymentMethodSelector(false);
      setAvailablePaymentAccounts([]);
      
      // Add system message
      const systemMessage: Message = {
        id: Date.now() + Math.random(), // Use timestamp + random for unique ID
        sender: 'system',
        text: '💳 Datos de pago compartidos. El comprador ahora puede realizar el pago.',
        timestamp: new Date(),
        type: 'system',
      };
      setMessages(prev => [systemMessage, ...prev]); // Add at beginning (descending order)
      
      // Refetch trade details to get updated status (with a small delay to ensure backend has processed)
      if (refetchTradeDetails) {
        console.log('🔄 Refetching trade details after sharing payment info...');
        // Add a small delay to ensure backend has processed the update
        setTimeout(async () => {
          const refetchResult = await refetchTradeDetails();
          console.log('📊 Refetch result:', {
            newStatus: refetchResult?.data?.p2pTrade?.status,
            previousStatus: tradeDetailsData?.p2pTrade?.status,
            currentStep: currentTradeStep,
            tradeType: tradeType
          });
        }, 1000); // 1 second delay
      }
      
      // Debug the current state after sharing payment details
      console.log('✅ Payment details shared successfully:', {
        currentTradeStep,
        tradeStatus: tradeDetailsData?.p2pTrade?.status,
        tradeType,
        shouldBuyerSeeMarkAsPaidButton: currentTradeStep === 2 && tradeType === 'buy'
      });
      
    } catch (error) {
      console.error('Error sharing payment details:', error);
      Alert.alert('Error', 'No se pudieron compartir los datos de pago');
    }
  };

  const confirmMarkAsPaid = async () => {
    setShowConfirmPaidModal(false);
    
    try {
      // Confirm payment sent using the new mutation
      const { data } = await confirmTradeStep({
        variables: {
          input: {
            tradeId: tradeId,
            confirmationType: 'PAYMENT_SENT',
            reference: '', // User can add this later if needed
            notes: 'Pago marcado como enviado por el comprador'
          }
        }
      });
      
      if (data?.confirmP2pTradeStep?.success) {
        // Update local state to reflect new status
        setCurrentTradeStep(3);
        
        // Add system message
        const systemMessage: Message = {
          id: Date.now() + Math.random(), // Use timestamp + random for unique ID
          sender: 'system',
          text: '✅ Has marcado el pago como completado. El vendedor debe confirmar la recepción.',
          timestamp: new Date(),
          type: 'system',
        };
        setMessages(prev => [systemMessage, ...prev]); // Add at beginning (descending order)
        
        // Refetch trade details to get updated status and escrow info
        if (refetchTradeDetails) {
          refetchTradeDetails();
        }
      } else {
        const errorMessage = data?.confirmP2pTradeStep?.errors?.join(', ') || 'Error al actualizar el estado';
        Alert.alert('Error', errorMessage);
      }
    } catch (error) {
      console.error('Error confirming payment sent:', error);
      Alert.alert('Error', 'No se pudo actualizar el estado del intercambio. Por favor intenta de nuevo.');
    }
  };
  
  const handleReleaseFunds = () => {
    Alert.alert(
      'Confirmar liberación de fondos',
      '¿Has verificado que recibiste el pago completo? Una vez liberados los fondos, no se pueden recuperar.',
      [
        {
          text: 'Cancelar',
          style: 'cancel'
        },
        {
          text: 'Sí, liberar fondos',
          onPress: confirmReleaseFunds,
          style: 'destructive'
        }
      ]
    );
  };
  
  const confirmReleaseFunds = async () => {
    try {
      // First confirm payment received
      const { data: confirmData } = await confirmTradeStep({
        variables: {
          input: {
            tradeId: tradeId,
            confirmationType: 'PAYMENT_RECEIVED',
            notes: 'Pago confirmado por el vendedor'
          }
        }
      });
      
      if (confirmData?.confirmP2pTradeStep?.success) {
        // Then immediately release the crypto
        const { data } = await confirmTradeStep({
          variables: {
            input: {
              tradeId: tradeId,
              confirmationType: 'CRYPTO_RELEASED',
              notes: 'Fondos liberados al comprador'
            }
          }
        });
      
      if (data?.confirmP2pTradeStep?.success) {
          // Update local state to reflect new status
          setCurrentTradeStep(4);
          
          // Add system message
          const systemMessage: Message = {
            id: Date.now() + Math.random(), // Use timestamp + random for unique ID
            sender: 'system',
            text: '🎉 ¡Intercambio completado exitosamente! Los fondos han sido liberados.',
            timestamp: new Date(),
            type: 'system',
          };
          setMessages(prev => [systemMessage, ...prev]); // Add at beginning (descending order)
          
          // Show success alert and navigate to rating
          Alert.alert(
          '¡Éxito!',
          'El intercambio se ha completado exitosamente. Los fondos han sido liberados al comprador.',
          [
            {
              text: 'Calificar al comprador',
              onPress: () => {
                // Navigate to rating screen
                const tradeData = tradeDetailsData?.p2pTrade;
                
                // Determine who is rating whom based on the current user's role
                const iAmSeller = tradeType === 'sell';
                const counterpartyInfo = iAmSeller 
                  ? (tradeData?.buyerUser || tradeData?.buyer) 
                  : (tradeData?.sellerUser || tradeData?.seller);
                
                // Get the actual stats for the counterparty
                const counterpartyStats = iAmSeller 
                  ? tradeData?.buyerStats 
                  : tradeData?.sellerStats;
                
                console.log('🎯 Seller rating navigation - Stats debug:', {
                  iAmSeller,
                  tradeType,
                  buyerInfo: tradeData?.buyer,
                  sellerInfo: tradeData?.seller,
                  buyerStats: tradeData?.buyerStats,
                  sellerStats: tradeData?.sellerStats,
                  counterpartyStats,
                  offerStats: tradeData?.offer?.userStats,
                });
                
                // Use the stats if available, otherwise fallback to default
                const stats = counterpartyStats || {
                  isVerified: false,
                  completedTrades: 0,
                  successRate: 0,
                };
                
                // Check if already rated
                if (tradeData?.hasRating) {
                  Alert.alert('Ya calificado', 'Ya has calificado este intercambio.');
                  return;
                }
                
                navigation.navigate('TraderRating', {
                  tradeId,
                  trader: {
                    name: iAmSeller 
                      ? (tradeData?.buyerDisplayName || `${counterpartyInfo?.firstName || ''} ${counterpartyInfo?.lastName || ''}`.trim() || counterpartyInfo?.username || 'Comprador')
                      : (tradeData?.sellerDisplayName || `${counterpartyInfo?.firstName || ''} ${counterpartyInfo?.lastName || ''}`.trim() || counterpartyInfo?.username || 'Vendedor'),
                    verified: stats.isVerified || false,
                    completedTrades: stats.completedTrades || 0,
                    successRate: stats.successRate || 0,
                  },
                  tradeDetails: {
                    amount: amount,
                    crypto: crypto,
                    totalPaid: (parseFloat(amount) * parseFloat(offer.rate)).toFixed(2),
                    method: tradeData?.paymentMethod?.displayName || 'N/A',
                    date: formatLocalDate(new Date().toISOString()),
                    duration: `${Math.floor((900 - timeRemaining) / 60)} minutos`,
                  }
                });
              }
            }
          ]
        );
        
        // Refetch trade details to get updated status
        if (refetchTradeDetails) {
          refetchTradeDetails();
        }
      } else {
        const errorMessage = data?.confirmP2pTradeStep?.errors?.join(', ') || 'Error al liberar los fondos';
        Alert.alert('Error', errorMessage);
      }
      } else {
        const errorMessage = confirmData?.confirmP2pTradeStep?.errors?.join(', ') || 'Error al confirmar el pago';
        Alert.alert('Error', errorMessage);
      }
    } catch (error) {
      console.error('Error releasing funds:', error);
      Alert.alert('Error', 'No se pudieron liberar los fondos. Por favor intenta de nuevo.');
    }
  };

  const handleSendMessage = async () => {
    if (message.trim() && tradeId && !sendingMessage) {
      const messageContent = message.trim();
      setMessage(''); // Clear input immediately for better UX
      
      try {
        // Send message via GraphQL mutation
        await sendMessage({
          variables: {
            input: {
              tradeId: tradeId,
              content: messageContent,
              messageType: 'TEXT'
            }
          }
        });
        
        // Stop typing indicator
        sendTypingIndicator(false);
        
      } catch (error) {
        console.error('Error sending message:', error);
        Alert.alert('Error', 'No se pudo enviar el mensaje. Intenta de nuevo.');
        // Restore message text if failed
        setMessage(messageContent);
      }
    } else if (!tradeId) {
      Alert.alert('Error', 'ID de intercambio no encontrado.');
    } else if (!isConnected) {
      Alert.alert('Sin conexión', 'No hay conexión al chat. Intenta de nuevo.');
    }
  };

  const formatTimestamp = (timestamp: Date) => {
    // Convert to ISO string to ensure proper handling
    return formatLocalTime(timestamp.toISOString());
  };

  const MessageBubble: React.FC<{ msg: Message }> = ({ msg }) => {
    const isUser = msg.sender === 'user';
    const isSystem = msg.sender === 'system';
    const isPaymentInfo = msg.type === 'payment_info';

    if (isSystem) {
      return (
        <View style={styles.systemMessageContainer}>
          <View style={styles.systemMessage}>
            <Icon name="info" size={12} color={colors.accent} style={styles.systemIcon} />
            <Text style={styles.systemMessageText}>{msg.text}</Text>
          </View>
        </View>
      );
    }

    if (isPaymentInfo) {
      const isPaymentFromUser = msg.sender === 'user';
      return (
        <View style={[styles.paymentInfoContainer, isPaymentFromUser ? styles.userPaymentInfoContainer : styles.traderPaymentInfoContainer]}>
          <View style={[styles.paymentInfoBubble, isPaymentFromUser ? styles.userPaymentInfoBubble : styles.traderPaymentInfoBubble]}>
            <View style={styles.paymentInfoHeader}>
              <Icon name="credit-card" size={16} color={isPaymentFromUser ? '#ffffff' : colors.primary} style={styles.paymentIcon} />
              <Text style={[styles.paymentInfoTitle, isPaymentFromUser && styles.userPaymentInfoTitle]}>Datos de pago compartidos</Text>
            </View>
            <Text style={[styles.paymentInfoText, isPaymentFromUser && styles.userPaymentInfoText]}>{msg.text}</Text>
            <Text style={[styles.paymentInfoTimestamp, isPaymentFromUser && styles.userPaymentInfoTimestamp]}>
              {formatTimestamp(msg.timestamp)}
            </Text>
          </View>
        </View>
      );
    }

    return (
      <View style={[styles.messageContainer, isUser ? styles.userMessageContainer : styles.traderMessageContainer]}>
        <View style={[styles.messageBubble, isUser ? styles.userMessageBubble : styles.traderMessageBubble]}>
          <Text style={[styles.messageText, isUser ? styles.userMessageText : styles.traderMessageText]}>
            {msg.text}
          </Text>
          <Text style={[styles.messageTimestamp, isUser ? styles.userMessageTimestamp : styles.traderMessageTimestamp]}>
            {formatTimestamp(msg.timestamp)}
          </Text>
        </View>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="dark-content" backgroundColor="#fff" />
      
      {/* Header */}
      <View style={styles.headerRow}>
        {/* Left: Back Button */}
        <TouchableOpacity onPress={handleGoBack} style={styles.backButton}>
          <Icon name="arrow-left" size={24} color="#374151" />
        </TouchableOpacity>

        {/* Center: Trader Info */}
        <View style={styles.headerCenter}>
          <View style={styles.traderInfo}>
            <View style={styles.avatarContainer}>
              <Text style={styles.avatarText}>{trader.name.charAt(0)}</Text>
              {trader.isOnline && <View style={styles.onlineIndicator} />}
            </View>
            <View style={styles.traderDetails}>
              <View style={styles.traderNameRow}>
                <Text style={styles.traderName}>{trader.name}</Text>
                {trader.verified && (
                  <Icon name="shield" size={16} color={colors.accent} style={styles.verifiedIcon} />
                )}
              </View>
              <View style={styles.traderStatus}>
                <Icon 
                  name={isConnected ? "wifi" : "wifi-off"} 
                  size={12} 
                  color={isConnected ? "#10B981" : "#EF4444"} 
                  style={styles.statusIcon} 
                />
                <Text style={styles.statusText}>
                  {isConnected ? 'Chat conectado' : 'Conectando...'}
                </Text>
                {typingUser && (
                  <Text style={styles.typingText}>• {typingUser} está escribiendo...</Text>
                )}
              </View>
            </View>
          </View>
        </View>

        {/* Right: Abandonar Button - Hidden during disputes */}
        {!isTradeDisputed && (
          <TouchableOpacity 
            style={styles.abandonButton}
            onPress={handleAbandonTrade}
          >
            <Text style={styles.abandonButtonText}>Abandonar</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Trade Status Banner */}
      <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
        <View style={styles.tradeStatusBanner}>
          <View style={styles.tradeStatusHeader}>
            <View style={styles.tradeInfo}>
              <Icon name="trending-up" size={16} color={colors.primary} style={styles.tradeIcon} />
              <Text style={styles.tradeAmount}>
                {tradeType === 'buy' 
                  ? `${formatNumber(parseFloat(tradeData.amount))} ${tradeData.crypto} por ${tradeData.totalBs}` 
                  : `${tradeData.totalBs} por ${formatNumber(parseFloat(tradeData.amount))} ${tradeData.crypto}`}
              </Text>
            </View>
            <View style={styles.tradeProgress}>
              <Text style={styles.stepIndicator}>Paso {currentTradeStep}/4</Text>
              <View style={styles.timerBadge}>
                <Text style={styles.timerText}>{formatTime(timeRemaining)}</Text>
              </View>
            </View>
          </View>
          
          <View style={styles.tradeStatusFooter}>
            <Text style={styles.stepText}>{getStepText(currentTradeStep)}</Text>
            <View style={styles.progressBar}>
              <View 
                style={[styles.progressFill, { width: `${(currentTradeStep / 4) * 100}%` }]} 
              />
            </View>
          </View>
          
          {/* Rate Comparison */}
          <View style={styles.rateComparison}>
            <View style={styles.rateComparisonRow}>
              <Text style={styles.rateLabel}>Tasa de este intercambio:</Text>
              <Text style={styles.rateValue}>{formatNumber(parseFloat(tradeData.rate))} {displayCurrencyCode}/USD</Text>
            </View>
            {marketRate && (
              <View style={styles.rateComparisonRow}>
                <Text style={styles.rateLabel}>Tasa actual del mercado:</Text>
                <Text style={[styles.rateValue, styles.marketRate]}>{formatNumber(marketRate)} {displayCurrencyCode}/USD</Text>
                {(() => {
                  const tradeRate = parseFloat(tradeData.rate);
                  const difference = ((tradeRate - marketRate) / marketRate) * 100;
                  const isGood = tradeType === 'buy' ? difference < 0 : difference > 0;
                  
                  if (Math.abs(difference) > 1) { // Only show if difference > 1%
                    return (
                      <Text style={[styles.rateDifference, isGood ? styles.goodRate : styles.badRate]}>
                        {difference > 0 ? '+' : ''}{formatNumber(difference, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%
                      </Text>
                    );
                  }
                  return null;
                })()}
              </View>
            )}
          </View>
        </View>
      </TouchableWithoutFeedback>

      {/* Quick Actions - Key prop added to force re-render */}
      {/* For Buyers - Mark as Paid (show in step 2 - PAYMENT_PENDING status) */}
      {currentTradeStep === 2 && computedTradeType === 'buy' && (
        <TouchableWithoutFeedback key={`mark-paid-${currentTradeStep}-${forceUpdate}`} onPress={Keyboard.dismiss}>
          <View style={styles.paymentActionBanner}>
            <View style={styles.paymentActionContent}>
              <View style={styles.paymentActionInfo}>
                <Icon name="credit-card" size={16} color="#2563EB" style={styles.paymentActionIcon} />
                <Text style={styles.paymentActionText}>¿Ya realizaste el pago?</Text>
              </View>
              <TouchableOpacity onPress={handleMarkAsPaid} style={styles.markAsPaidButton}>
                <Text style={styles.markAsPaidButtonText}>Marcar como pagado</Text>
              </TouchableOpacity>
            </View>
          </View>
        </TouchableWithoutFeedback>
      )}
      
      {/* For Sellers - Release Funds - Key prop added to force re-render */}
      {currentTradeStep === 3 && computedTradeType === 'sell' && (
        <TouchableWithoutFeedback key={`release-funds-${currentTradeStep}-${forceUpdate}`} onPress={Keyboard.dismiss}>
          <View style={[styles.paymentActionBanner, { backgroundColor: '#D1FAE5' }]}>
            <View style={styles.paymentActionContent}>
              <View style={styles.paymentActionInfo}>
                <Icon name="check-circle" size={16} color="#059669" style={styles.paymentActionIcon} />
                <Text style={[styles.paymentActionText, { color: '#065F46' }]}>¿Recibiste el pago?</Text>
              </View>
              <TouchableOpacity onPress={handleReleaseFunds} style={[styles.markAsPaidButton, { backgroundColor: '#059669' }]}>
                <Text style={styles.markAsPaidButtonText}>Liberar fondos</Text>
              </TouchableOpacity>
            </View>
          </View>
        </TouchableWithoutFeedback>
      )}

      {/* Security Notice */}
      {!isSecurityNoticeDismissed && (
        <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
          <View style={styles.securityNotice}>
            <View style={styles.securityContent}>
              <Icon name="alert-triangle" size={16} color="#D97706" style={styles.securityIcon} />
              <View style={styles.securityTextContainer}>
                <Text style={styles.securityTitle}>Seguridad:</Text>
                <Text style={styles.securityText}>• Solo comparte información bancaria en este chat seguro</Text>
                <Text style={styles.securityText}>• Nunca envíes criptomonedas antes de confirmar el pago</Text>
                <Text style={styles.securityText}>• No compartas comprobantes por fotos (vulnerables a edición)</Text>
              </View>
            </View>
            <TouchableOpacity 
              onPress={() => setIsSecurityNoticeDismissed(true)} 
              style={styles.securityDismissButton}
            >
              <Text style={styles.securityDismissButtonText}>Entiendo</Text>
            </TouchableOpacity>
          </View>
        </TouchableWithoutFeedback>
      )}

      {/* Dispute Banner */}
      {isTradeDisputed && (
        <View style={styles.disputeBanner}>
          <Icon name="alert-triangle" size={16} color="#DC2626" style={styles.disputeIcon} />
          <View style={styles.disputeTextContainer}>
            <Text style={styles.disputeTitle}>Intercambio en disputa</Text>
            <Text style={styles.disputeText}>
              Este intercambio está siendo revisado por nuestro equipo de soporte. 
              El chat permanece abierto para facilitar la resolución.
            </Text>
          </View>
        </View>
      )}

      {/* Messages and Input Container */}
      <KeyboardAvoidingView 
        style={styles.chatContainer} 
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={0}
      >
        {/* Messages Area */}
        <TouchableWithoutFeedback onPress={Keyboard.dismiss}>
          <View style={styles.messagesContainer}>
            {messages.length === 0 ? (
              <View style={styles.emptyMessagesContainer}>
                <Text style={styles.emptyMessagesText}>
                  No hay mensajes aún...
                </Text>
              </View>
            ) : (
              <FlatList
                ref={messagesListRef}
                data={messages}
                renderItem={({ item }) => <MessageBubble key={item.id} msg={item} />}
                keyExtractor={(item) => item.id.toString()}
                style={styles.messagesScroll}
                contentContainerStyle={styles.messagesContent}
                showsVerticalScrollIndicator={false}
                keyboardShouldPersistTaps="handled"
                keyboardDismissMode="on-drag"
                inverted={true}
                // FlatList optimizations for chat
                initialNumToRender={20}
                maxToRenderPerBatch={10}
                windowSize={21}
                removeClippedSubviews={true}
                updateCellsBatchingPeriod={50}
                maintainVisibleContentPosition={{
                  minIndexForVisible: 0,
                  autoscrollToTopThreshold: 10,
                }}
                // Scroll to bottom on new messages
                onContentSizeChange={() => {
                  if (messages.length > 0) {
                    messagesListRef.current?.scrollToEnd({ animated: true });
                  }
                }}
              />
            )}
          </View>
        </TouchableWithoutFeedback>

        {/* Message Input */}
        <TouchableWithoutFeedback>
          <View style={styles.inputContainer}>
            {isTradeDisputed ? (
              <View style={styles.disputedInputContainer}>
                <Icon name="alert-triangle" size={16} color="#DC2626" style={styles.disputedInputIcon} />
                <Text style={styles.disputedInputText}>
                  Chat bloqueado durante la disputa. El equipo de soporte revisará este intercambio.
                </Text>
              </View>
            ) : (
              <View style={styles.inputRow}>
          {/* Share Payment Details Button - Only show for seller in step 1 */}
          {computedTradeType === 'sell' && currentTradeStep === 1 && (
            <TouchableOpacity 
              onPress={handleSharePaymentDetails}
              onLongPress={() => Alert.alert('Compartir Datos de Pago', 'Comparte los datos de tu método de pago seleccionado con el comprador')}
              style={styles.sharePaymentButton}
            >
              <Icon name="credit-card" size={20} color={colors.primary} />
            </TouchableOpacity>
          )}
          
          
          {/* Request Payment Details Button - Only show for buyer in step 1 */}
          {computedTradeType === 'buy' && currentTradeStep === 1 && (
            <TouchableOpacity 
              onPress={() => {
                Alert.alert(
                  'Solicitar Datos de Pago', 
                  'Puedes solicitar al vendedor que comparta los datos de pago a través del chat.',
                  [{ text: 'OK' }]
                );
              }}
              style={[styles.sharePaymentButton, { backgroundColor: '#FEF3C7' }]}
            >
              <Icon name="help-circle" size={20} color="#F59E0B" />
            </TouchableOpacity>
          )}
          
          <View style={styles.inputWrapper}>
            <TextInput
              style={styles.textInput}
              value={message}
              onChangeText={(text) => {
                setMessage(text);
                
                // Send typing indicator
                if (text.trim() && !isTyping) {
                  setIsTyping(true);
                  sendTypingIndicator(true);
                  
                  // Stop typing after 2 seconds of no typing
                  setTimeout(() => {
                    setIsTyping(false);
                    sendTypingIndicator(false);
                  }, 2000);
                } else if (!text.trim() && isTyping) {
                  setIsTyping(false);
                  sendTypingIndicator(false);
                }
              }}
              placeholder="Escribe un mensaje..."
              placeholderTextColor="#9CA3AF"
              multiline
              maxLength={500}
            />
          </View>
          
          <TouchableOpacity 
            onPress={handleSendMessage}
            disabled={!message.trim() || sendingMessage}
            style={[styles.sendButton, (!message.trim() || sendingMessage) && styles.sendButtonDisabled]}
          >
            <Icon 
              name={sendingMessage ? "loader" : "send"} 
              size={20} 
              color={(message.trim() && !sendingMessage) ? '#ffffff' : '#9CA3AF'} 
            />
          </TouchableOpacity>
              </View>
            )}
          </View>
        </TouchableWithoutFeedback>
      </KeyboardAvoidingView>

      {/* Confirmation Modal for Marcar como pagado */}
      <Modal
        visible={showConfirmPaidModal}
        transparent
        animationType="fade"
        onRequestClose={() => setShowConfirmPaidModal(false)}
      >
        <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', justifyContent: 'center', alignItems: 'center' }}>
          <View style={{ backgroundColor: '#fff', borderRadius: 16, padding: 24, width: '80%', alignItems: 'center' }}>
            <Icon name="alert-triangle" size={32} color="#F59E42" style={{ marginBottom: 12 }} />
            <Text style={{ fontWeight: 'bold', fontSize: 18, marginBottom: 8 }}>¿Confirmar que realizaste el pago?</Text>
            <Text style={{ color: '#6B7280', textAlign: 'center', marginBottom: 20 }}>
              Solo marca como pagado si ya realizaste la transferencia. Falsos reportes pueden resultar en suspensión de tu cuenta.
            </Text>
            <View style={{ flexDirection: 'row', gap: 12 }}>
              <TouchableOpacity
                style={{ backgroundColor: '#F3F4F6', paddingVertical: 12, paddingHorizontal: 20, borderRadius: 8, marginRight: 8 }}
                onPress={() => setShowConfirmPaidModal(false)}
              >
                <Text style={{ color: '#374151', fontWeight: '600' }}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={{ backgroundColor: colors.primary, paddingVertical: 12, paddingHorizontal: 20, borderRadius: 8 }}
                onPress={confirmMarkAsPaid}
              >
                <Text style={{ color: '#fff', fontWeight: '600' }}>Sí, ya pagué</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Payment Method Account Selector Modal */}
      <Modal
        visible={showPaymentMethodSelector}
        transparent
        animationType="slide"
        onRequestClose={() => setShowPaymentMethodSelector(false)}
      >
        <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', justifyContent: 'flex-end' }}>
          <View style={{ backgroundColor: '#fff', borderTopLeftRadius: 20, borderTopRightRadius: 20, paddingTop: 24, paddingBottom: 32, maxHeight: '80%' }}>
            <View style={{ paddingHorizontal: 24, marginBottom: 16 }}>
              <Text style={{ fontWeight: 'bold', fontSize: 18, color: '#1F2937', marginBottom: 8 }}>Seleccionar Cuenta</Text>
              <Text style={{ color: '#6B7280', fontSize: 14 }}>
                Tienes múltiples cuentas para este método de pago. Selecciona cuál deseas compartir:
              </Text>
            </View>
            
            <FlatList
              data={availablePaymentAccounts}
              keyExtractor={(item) => item.id}
              renderItem={({ item, index }) => {
                const getAccountTypeLabel = (type: string) => {
                  const labels: { [key: string]: string } = {
                    'ahorro': 'Ahorros',
                    'corriente': 'Corriente',
                    'nomina': 'Nómina',
                  };
                  return labels[type] || type;
                };
                
                return (
                  <TouchableOpacity
                    style={{
                      paddingHorizontal: 24,
                      paddingVertical: 16,
                      borderBottomWidth: index < availablePaymentAccounts.length - 1 ? 1 : 0,
                      borderBottomColor: '#E5E7EB',
                    }}
                    onPress={() => sharePaymentDetailsWithAccount(item)}
                  >
                    <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                      <View style={{
                        width: 48,
                        height: 48,
                        borderRadius: 24,
                        backgroundColor: colors.primaryLight,
                        justifyContent: 'center',
                        alignItems: 'center',
                        marginRight: 12,
                      }}>
                        <Icon 
                          name={item.paymentMethod?.providerType === 'bank' ? 'credit-card' : 'smartphone'} 
                          size={20} 
                          color={colors.primary} 
                        />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={{ fontWeight: '600', fontSize: 16, color: '#1F2937', marginBottom: 2 }}>
                          {item.accountHolderName}
                        </Text>
                        <Text style={{ fontSize: 14, color: '#6B7280' }}>
                          {item.accountNumber ? 
                            `****${item.accountNumber.slice(-4)}` : 
                            (item.phoneNumber || item.email || item.username)
                          }
                          {item.accountType && ` • ${getAccountTypeLabel(item.accountType)}`}
                        </Text>
                        {item.isDefault && (
                          <Text style={{ fontSize: 12, color: colors.primary, marginTop: 2 }}>
                            Cuenta predeterminada
                          </Text>
                        )}
                      </View>
                      <Icon name="chevron-right" size={20} color="#9CA3AF" />
                    </View>
                  </TouchableOpacity>
                );
              }}
              showsVerticalScrollIndicator={true}
              style={{ maxHeight: 400 }}
            />
            
            <TouchableOpacity
              style={{
                marginTop: 16,
                marginHorizontal: 24,
                paddingVertical: 12,
                backgroundColor: '#F3F4F6',
                borderRadius: 8,
                alignItems: 'center',
              }}
              onPress={() => {
                setShowPaymentMethodSelector(false);
                setAvailablePaymentAccounts([]);
              }}
            >
              <Text style={{ color: '#374151', fontWeight: '600' }}>Cancelar</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#F9FAFB',
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
    backgroundColor: '#fff',
  },
  backButton: {
    padding: 4,
    marginRight: 12,
  },
  headerCenter: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
  },
  traderInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  avatarContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    position: 'relative',
  },
  avatarText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#6B7280',
  },
  onlineIndicator: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#10B981',
    borderWidth: 2,
    borderColor: '#fff',
  },
  traderDetails: {
    flex: 1,
  },
  traderNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  traderName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  verifiedIcon: {
    marginLeft: 4,
  },
  traderStatus: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  statusIcon: {
    marginRight: 4,
  },
  statusText: {
    fontSize: 12,
    color: '#6B7280',
  },
  typingText: {
    fontSize: 12,
    color: '#10B981',
    fontStyle: 'italic',
    marginLeft: 8,
  },
  viewTradeButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  viewTradeButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  tradeStatusBanner: {
    backgroundColor: '#ECFDF5',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#D1FAE5',
  },
  tradeStatusHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  tradeInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  tradeIcon: {
    marginRight: 8,
  },
  tradeAmount: {
    fontSize: 14,
    color: '#065F46',
    fontWeight: '600',
  },
  tradeProgress: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  stepIndicator: {
    fontSize: 12,
    color: '#059669',
    marginRight: 8,
  },
  timerBadge: {
    backgroundColor: '#D1FAE5',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  timerText: {
    fontSize: 12,
    color: '#065F46',
    fontWeight: '600',
  },
  tradeStatusFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stepText: {
    fontSize: 12,
    color: '#065F46',
  },
  progressBar: {
    width: 96,
    height: 4,
    backgroundColor: '#D1FAE5',
    borderRadius: 2,
  },
  progressFill: {
    height: 4,
    backgroundColor: '#059669',
    borderRadius: 2,
  },
  quickActionsBanner: {
    backgroundColor: '#FEF3C7',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#FDE68A',
  },
  quickActionsContent: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  quickActionsInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  quickActionsIcon: {
    marginRight: 8,
  },
  quickActionsText: {
    fontSize: 14,
    color: '#92400E',
  },
  markAsPaidButton: {
    backgroundColor: '#2563EB',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  markAsPaidButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  paymentActionBanner: {
    backgroundColor: '#DBEAFE',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#93C5FD',
  },
  paymentActionContent: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  paymentActionInfo: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  paymentActionIcon: {
    marginRight: 8,
  },
  paymentActionText: {
    fontSize: 14,
    color: '#1E40AF',
    fontWeight: '600',
  },
  securityNotice: {
    backgroundColor: '#FEF3C7',
    padding: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#FDE68A',
  },
  securityContent: {
    flexDirection: 'row',
  },
  securityIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  securityTextContainer: {
    flex: 1,
  },
  securityTitle: {
    fontSize: 12,
    color: '#92400E',
    fontWeight: '600',
    marginBottom: 4,
  },
  securityText: {
    fontSize: 12,
    color: '#92400E',
    lineHeight: 16,
  },
  securityDismissButton: {
    backgroundColor: '#92400E',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 6,
    alignSelf: 'flex-end',
    marginTop: 12,
  },
  securityDismissButtonText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '600',
  },
  chatContainer: {
    flex: 1,
    backgroundColor: '#fff',
  },
  messagesContainer: {
    flex: 1,
  },
  emptyMessagesContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyMessagesText: {
    color: '#6B7280',
    fontStyle: 'italic',
  },
  messagesScroll: {
    flex: 1,
  },
  messagesContent: {
    padding: 16,
    paddingTop: 8,
    paddingBottom: 8,
    flexGrow: 1,
  },
  systemMessageContainer: {
    alignItems: 'center',
    marginVertical: 8,
  },
  systemMessage: {
    backgroundColor: '#DBEAFE',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    flexDirection: 'row',
    alignItems: 'center',
  },
  systemIcon: {
    marginRight: 4,
  },
  systemMessageText: {
    fontSize: 12,
    color: '#1E40AF',
  },
  paymentInfoContainer: {
    marginBottom: 12,
  },
  userPaymentInfoContainer: {
    alignItems: 'flex-end',
  },
  traderPaymentInfoContainer: {
    alignItems: 'flex-start',
  },
  paymentInfoBubble: {
    borderWidth: 1,
    borderColor: '#BBF7D0',
    padding: 16,
    borderRadius: 16,
    maxWidth: '80%',
  },
  paymentInfoHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  paymentIcon: {
    marginRight: 8,
  },
  paymentInfoTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#166534',
  },
  paymentInfoText: {
    fontSize: 14,
    color: '#1F2937',
    fontFamily: 'monospace',
    lineHeight: 20,
  },
  paymentInfoTimestamp: {
    fontSize: 12,
    color: '#059669',
    marginTop: 8,
  },
  messageContainer: {
    marginBottom: 12,
  },
  userMessageContainer: {
    alignItems: 'flex-end',
  },
  traderMessageContainer: {
    alignItems: 'flex-start',
  },
  messageBubble: {
    maxWidth: '80%',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 16,
  },
  userMessageBubble: {
    backgroundColor: colors.primary,
    borderBottomRightRadius: 4,
  },
  traderMessageBubble: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    borderBottomLeftRadius: 4,
  },
  messageText: {
    fontSize: 14,
    lineHeight: 20,
  },
  userMessageText: {
    color: '#fff',
  },
  traderMessageText: {
    color: '#1F2937',
  },
  messageTimestamp: {
    fontSize: 12,
    marginTop: 4,
  },
  userMessageTimestamp: {
    color: '#D1FAE5',
  },
  traderMessageTimestamp: {
    color: '#6B7280',
  },
  inputContainer: {
    backgroundColor: '#fff',
    padding: 16,
    paddingBottom: 16,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: -2,
    },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 8,
  },
  inputRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
  },
  inputWrapper: {
    flex: 1,
    marginRight: 8,
    backgroundColor: '#F9FAFB',
    borderWidth: 1,
    borderColor: '#D1D5DB',
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  textInput: {
    fontSize: 16,
    color: '#1F2937',
    maxHeight: 100,
    textAlignVertical: 'top',
    minHeight: 40,
    paddingHorizontal: 0,
    paddingVertical: Platform.OS === 'android' ? 8 : 12,
  },
  sendButton: {
    backgroundColor: colors.primary,
    width: 44,
    height: 44,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendButtonDisabled: {
    backgroundColor: '#E5E7EB',
  },
  sharePaymentButton: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#E0F2FE',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  userPaymentInfoBubble: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
    borderBottomRightRadius: 4,
  },
  traderPaymentInfoBubble: {
    backgroundColor: '#F0FDF4',
    borderColor: '#BBF7D0',
    borderBottomLeftRadius: 4,
  },
  userPaymentInfoTitle: {
    color: '#ffffff',
  },
  userPaymentInfoText: {
    color: '#ffffff',
  },
  userPaymentInfoTimestamp: {
    color: '#ffffff',
  },
  abandonButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#EF4444',
    marginLeft: 12,
  },
  abandonButtonText: {
    color: '#EF4444',
    fontSize: 14,
    fontWeight: '600',
  },
  rateComparison: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#D1FAE5',
  },
  rateComparisonRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  rateLabel: {
    fontSize: 11,
    color: '#065F46',
  },
  rateValue: {
    fontSize: 11,
    fontWeight: '600',
    color: '#065F46',
    fontFamily: 'monospace',
  },
  marketRate: {
    color: '#059669',
  },
  rateDifference: {
    fontSize: 10,
    fontWeight: '600',
    marginLeft: 8,
    paddingHorizontal: 4,
    paddingVertical: 1,
    borderRadius: 4,
  },
  goodRate: {
    backgroundColor: '#D1FAE5',
    color: '#065F46',
  },
  badRate: {
    backgroundColor: '#FEE2E2',
    color: '#DC2626',
  },
  // Dispute styles
  disputeBanner: {
    backgroundColor: '#FEE2E2',
    padding: 12,
    flexDirection: 'row',
    alignItems: 'flex-start',
    borderBottomWidth: 1,
    borderBottomColor: '#FECACA',
  },
  disputeIcon: {
    marginRight: 8,
    marginTop: 2,
  },
  disputeTextContainer: {
    flex: 1,
  },
  disputeTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#DC2626',
    marginBottom: 2,
  },
  disputeText: {
    fontSize: 12,
    color: '#7F1D1D',
    lineHeight: 16,
  },
  disputedInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    paddingHorizontal: 16,
  },
  disputedInputIcon: {
    marginRight: 8,
  },
  disputedInputText: {
    fontSize: 14,
    color: '#DC2626',
    textAlign: 'center',
  },
}); 