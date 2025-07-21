import React, { useState, useRef, useEffect } from 'react';
import { 
  View, 
  Text, 
  StyleSheet, 
  TouchableOpacity, 
  TextInput, 
  ScrollView, 
  Platform,
  Animated,
  Dimensions,
  Modal,
  TouchableWithoutFeedback,
  FlatList,
  Alert,
  type TextInput as TextInputType,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { useQuery } from '@apollo/client';
import { MainStackParamList } from '../types/navigation';
import { countries, Country } from '../utils/countries';
import { useCountrySelection } from '../hooks/useCountrySelection';
import { useCurrency } from '../hooks/useCurrency';
import { GET_P2P_OFFERS, GET_P2P_PAYMENT_METHODS, GET_MY_P2P_TRADES } from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';

// Colors from the design
const colors = {
  primary: '#34d399', // emerald-400
  primaryText: '#34d399',
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  secondaryText: '#8b5cf6',
  accent: '#3b82f6', // blue-500
  accentText: '#3b82f6',
  neutral: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  dark: '#111827', // gray-900
};

const { width } = Dimensions.get('window');

// Enhanced mock data for offers
const mockOffers = {
  cUSD: [
    {
      id: 1,
      name: "Maria L.",
      completedTrades: 248,
      successRate: 99.2,
      responseTime: "2 min",
      rate: "36.10",
      available: "1,500.00",
      limit: "100.00 - 1,500.00",
      paymentMethods: ["Banco Venezuela", "Pago Móvil", "Efectivo"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    },
    {
      id: 2,
      name: "Carlos F.",
      completedTrades: 124,
      successRate: 98.5,
      responseTime: "5 min",
      rate: "36.05",
      available: "800.00",
      limit: "50.00 - 800.00",
      paymentMethods: ["Mercantil", "Banesco", "Efectivo"],
      isOnline: false,
      verified: true,
      lastSeen: "Hace 15 min"
    },
    {
      id: 3,
      name: "Ana P.",
      completedTrades: 310,
      successRate: 99.7,
      responseTime: "1 min",
      rate: "36.00",
      available: "950.00",
      limit: "100.00 - 950.00",
      paymentMethods: ["Banco Venezuela", "Zelle"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    },
    {
      id: 4,
      name: "Pedro M.",
      completedTrades: 178,
      successRate: 97.8,
      responseTime: "8 min",
      rate: "35.95",
      available: "2,300.00",
      limit: "200.00 - 2,300.00",
      paymentMethods: ["Mercantil", "PayPal", "Efectivo"],
      isOnline: false,
      verified: true,
      lastSeen: "Hace 1 hora"
    },
    {
      id: 5,
      name: "Laura S.",
      completedTrades: 89,
      successRate: 96.5,
      responseTime: "12 min",
      rate: "35.90",
      available: "600.00",
      limit: "50.00 - 600.00",
      paymentMethods: ["Banesco", "Pago Móvil"],
      isOnline: true,
      verified: false,
      lastSeen: "Activo ahora"
    },
    {
      id: 6,
      name: "Roberto C.",
      completedTrades: 456,
      successRate: 99.5,
      responseTime: "3 min",
      rate: "35.88",
      available: "1,800.00",
      limit: "150.00 - 1,800.00",
      paymentMethods: ["Banco Venezuela", "Mercantil", "Efectivo"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    },
    {
      id: 7,
      name: "Sofia R.",
      completedTrades: 67,
      successRate: 94.2,
      responseTime: "15 min",
      rate: "35.85",
      available: "400.00",
      limit: "25.00 - 400.00",
      paymentMethods: ["Zelle", "PayPal"],
      isOnline: false,
      verified: false,
      lastSeen: "Hace 30 min"
    },
    {
      id: 8,
      name: "Miguel A.",
      completedTrades: 203,
      successRate: 98.1,
      responseTime: "6 min",
      rate: "35.80",
      available: "1,200.00",
      limit: "100.00 - 1,200.00",
      paymentMethods: ["Banesco", "Pago Móvil", "Efectivo"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    },
    {
      id: 9,
      name: "Carmen V.",
      completedTrades: 145,
      successRate: 97.3,
      responseTime: "10 min",
      rate: "35.75",
      available: "750.00",
      limit: "75.00 - 750.00",
      paymentMethods: ["Banco Venezuela", "Zelle"],
      isOnline: false,
      verified: true,
      lastSeen: "Hace 2 horas"
    },
    {
      id: 10,
      name: "Diego T.",
      completedTrades: 321,
      successRate: 99.1,
      responseTime: "4 min",
      rate: "35.70",
      available: "1,600.00",
      limit: "200.00 - 1,600.00",
      paymentMethods: ["Mercantil", "Banesco", "PayPal"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    }
  ],
  CONFIO: [
    {
      id: 7,
      name: "Juan V.",
      completedTrades: 89,
      successRate: 95.8,
      responseTime: "18 min",
      rate: "3.65",
      available: "2,000.00",
      limit: "100.00 - 2,000.00",
      paymentMethods: ["Efectivo"],
      isOnline: false,
      verified: false,
      lastSeen: "Hace 4 horas"
    },
    {
      id: 8,
      name: "Laura M.",
      completedTrades: 356,
      successRate: 99.1,
      responseTime: "4 min",
      rate: "3.63",
      available: "1,200.00",
      limit: "50.00 - 1,200.00",
      paymentMethods: ["Mercantil", "Banesco", "PayPal"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    },
    {
      id: 9,
      name: "Roberto S.",
      completedTrades: 112,
      successRate: 98.7,
      responseTime: "7 min",
      rate: "3.60",
      available: "3,500.00",
      limit: "100.00 - 3,500.00",
      paymentMethods: ["Banco Venezuela", "Mercantil", "Pago Móvil"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    },
    {
      id: 10,
      name: "Carla D.",
      completedTrades: 201,
      successRate: 97.3,
      responseTime: "10 min",
      rate: "3.58",
      available: "1,800.00",
      limit: "200.00 - 1,800.00",
      paymentMethods: ["Banco Venezuela", "Zelle"],
      isOnline: false,
      verified: true,
      lastSeen: "Hace 2 horas"
    },
    {
      id: 11,
      name: "Valentina K.",
      completedTrades: 78,
      successRate: 95.8,
      responseTime: "18 min",
      rate: "3.55",
      available: "500.00",
      limit: "50.00 - 500.00",
      paymentMethods: ["Efectivo"],
      isOnline: false,
      verified: false,
      lastSeen: "Hace 4 horas"
    },
    {
      id: 12,
      name: "Fernando L.",
      completedTrades: 267,
      successRate: 98.7,
      responseTime: "7 min",
      rate: "3.52",
      available: "1,100.00",
      limit: "100.00 - 1,100.00",
      paymentMethods: ["Banco Venezuela", "Mercantil", "Pago Móvil"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    },
    {
      id: 13,
      name: "Isabella N.",
      completedTrades: 198,
      successRate: 97.9,
      responseTime: "9 min",
      rate: "3.50",
      available: "900.00",
      limit: "100.00 - 900.00",
      paymentMethods: ["Banesco", "Zelle"],
      isOnline: false,
      verified: true,
      lastSeen: "Hace 1 hora"
    },
    {
      id: 14,
      name: "Matias P.",
      completedTrades: 412,
      successRate: 99.3,
      responseTime: "3 min",
      rate: "3.48",
      available: "2,500.00",
      limit: "250.00 - 2,500.00",
      paymentMethods: ["Mercantil", "PayPal", "Efectivo"],
      isOnline: true,
      verified: true,
      lastSeen: "Activo ahora"
    }
  ],
};

// Payment methods will be computed from server data inside the component

type Offer = typeof mockOffers.cUSD[0];

// Define the trade type based on the GraphQL schema
interface ActiveTrade {
  id: string;
  trader: {
    name: string;
    isOnline: boolean;
    verified: boolean;
    lastSeen: string;
    responseTime: string;
  };
  amount: string;
  crypto: string;
  totalBs: string;
  step: number;
  totalSteps: number;
  timeRemaining: number; // seconds
  status: string;
  paymentMethod: string;
  rate: string;
  tradeType: 'buy' | 'sell';
}

export const ExchangeScreen = () => {
  // Use centralized country selection hook
  const { selectedCountry, showCountryModal, selectCountry, openCountryModal, closeCountryModal } = useCountrySelection();
  
  // Use currency system based on selected country
  const { currency, formatAmount, exchangeRate } = useCurrency();
  
  // Get current account context
  const { activeAccount } = useAccount();

  const [activeTab, setActiveTab] = useState<'buy' | 'sell'>('buy');
  const [selectedCrypto, setSelectedCrypto] = useState<'cUSD' | 'CONFIO'>('cUSD');
  const [amount, setAmount] = useState('');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState('Todos los métodos');
  const [minRate, setMinRate] = useState('');
  const [maxRate, setMaxRate] = useState('');
  const [filterVerified, setFilterVerified] = useState(false);
  const [filterOnline, setFilterOnline] = useState(false);
  const [filterHighVolume, setFilterHighVolume] = useState(false);
  const scrollY = useRef(new Animated.Value(0)).current;
  const refreshRotation = useRef(new Animated.Value(0)).current;

  // Fetch real P2P offers from database
  const { data: offersData, loading: offersLoading, error: offersError, refetch } = useQuery(GET_P2P_OFFERS, {
    variables: {
      exchangeType: activeTab === 'buy' ? 'SELL' : 'BUY', // If user wants to buy, show sell offers
      tokenType: selectedCrypto,
      paymentMethod: null, // Will be properly set in useEffect when we have payment methods data
      countryCode: selectedCountry?.[2] // Pass the selected country code (e.g., 'AS', 'VE', etc.)
    },
    fetchPolicy: 'cache-and-network', // Use cache while fetching new data
    notifyOnNetworkStatusChange: false, // Prevent re-renders on network status changes
    // pollInterval: 30000, // Disabled to prevent re-renders while typing
  });

  // Fetch payment methods from server based on selected country
  const { data: paymentMethodsData, loading: paymentMethodsLoading, refetch: refetchPaymentMethods } = useQuery(GET_P2P_PAYMENT_METHODS, {
    variables: {
      countryCode: selectedCountry?.[2]
    },
    skip: !selectedCountry,
    fetchPolicy: 'no-cache', // Completely bypass cache
    notifyOnNetworkStatusChange: false // Prevent re-renders on network status changes
  });

  // Fetch user's active trades filtered by current account context
  const { data: myTradesData, loading: tradesLoading, error: tradesError, refetch: refetchTrades } = useQuery(GET_MY_P2P_TRADES, {
    variables: {
      accountId: activeAccount?.id // Filter trades by current account context
    },
    fetchPolicy: 'cache-and-network', // Allow cache but also fetch fresh data
    notifyOnNetworkStatusChange: false,
    skip: !activeAccount // Skip query if no active account
  });

  // Transform real trades data into UI format
  const activeTrades: ActiveTrade[] = React.useMemo(() => {
    if (!myTradesData?.myP2pTrades) return [];
    
    return myTradesData.myP2pTrades
      .filter((trade: any) => trade.status !== 'COMPLETED' && trade.status !== 'CANCELLED')
      .map((trade: any) => {
        // NEW: Use the computed helper fields from GraphQL for cleaner logic
        const buyerDisplayName = trade.buyerDisplayName || 'Unknown Buyer';
        const sellerDisplayName = trade.sellerDisplayName || 'Unknown Seller';
        const buyerType = trade.buyerType || 'user';
        const sellerType = trade.sellerType || 'user';
        
        // Determine if current account is buyer or seller
        // Since we're filtering by account context, we know this trade involves the current account
        let tradeType, otherPartyName;
        
        if (activeAccount?.type === 'business') {
          // Current account is business
          const currentBusinessId = activeAccount.business?.id;
          const isBuyer = trade.buyerBusiness?.id === currentBusinessId;
          
          tradeType = isBuyer ? 'buy' : 'sell';
          otherPartyName = isBuyer ? sellerDisplayName : buyerDisplayName;
        } else {
          // Current account is personal
          const currentUserId = activeAccount?.id; // This might need to be adjusted based on account structure
          const isBuyer = trade.buyerUser?.id === currentUserId;
          
          tradeType = isBuyer ? 'buy' : 'sell';
          otherPartyName = isBuyer ? sellerDisplayName : buyerDisplayName;
        }
        
        // Calculate time remaining (mock for now)
        const timeRemaining = 900; // 15 minutes default
        
        // Map status to step
        const getStepFromStatus = (status: string) => {
          switch (status) {
            case 'PENDING': return 1;
            case 'PAYMENT_PENDING': return 2;
            case 'PAYMENT_SENT': return 3;
            case 'PAYMENT_CONFIRMED': return 4;
            default: return 1;
          }
        };

        return {
          id: trade.id,
          trader: {
            name: otherPartyName,
            isOnline: true, // TODO: Get real online status
            verified: true, // TODO: Get real verification status
            lastSeen: "Activo ahora", // TODO: Get real last seen
            responseTime: "5 min", // TODO: Get real response time
          },
          amount: trade.cryptoAmount.toString(),
          crypto: trade.offer?.tokenType || 'cUSD',
          totalBs: formatAmount.withCode(trade.fiatAmount),
          step: getStepFromStatus(trade.status),
          totalSteps: 4,
          timeRemaining,
          status: trade.status.toLowerCase(),
          paymentMethod: trade.paymentMethod?.displayName || trade.paymentMethod?.name || 'N/A',
          rate: trade.rateUsed.toString(),
          tradeType,
        };
      });
  }, [myTradesData, formatAmount, activeAccount]);

  // Debug country changes - Apollo will automatically refetch when variables change
  useEffect(() => {
    if (selectedCountry?.[2]) {
      // Remove console.log to prevent re-renders
      // console.log('🏴 Country changed to:', selectedCountry[0], 'Code:', selectedCountry[2]);
      // console.log('📡 Apollo will automatically refetch payment methods...');
    }
  }, [selectedCountry?.[2]]);



  // Compute payment methods from server data
  const paymentMethods = React.useMemo(() => {
    if (paymentMethodsLoading) {
      return ['Todos los métodos']; // Show default while loading
    }
    
    if (!paymentMethodsData?.p2pPaymentMethods) {
      return ['Todos los métodos']; // Default when no data
    }
    
    const serverMethods = paymentMethodsData.p2pPaymentMethods.map((pm: any) => pm.displayName);
    return ['Todos los métodos', ...serverMethods];
  }, [paymentMethodsData, paymentMethodsLoading]); // Removed selectedCountry dependency

  // Reset selected payment method if it's not available in the new country's methods
  useEffect(() => {
    if (paymentMethods.length > 0 && !paymentMethods.includes(selectedPaymentMethod)) {
      // console.log('Resetting payment method from', selectedPaymentMethod, 'to "Todos los métodos"');
      setSelectedPaymentMethod('Todos los métodos');
    }
  }, [paymentMethods, selectedPaymentMethod]);

  // Refetch when filters change (including country)
  useEffect(() => {
    // Only refetch if we have payment methods data (to use the helper function)
    if (paymentMethodsData || selectedPaymentMethod === 'Todos los métodos') {
      // Convert display name to internal name inline
      let paymentMethodName = null;
      if (selectedPaymentMethod !== 'Todos los métodos' && paymentMethodsData?.p2pPaymentMethods) {
        const method = paymentMethodsData.p2pPaymentMethods.find((pm: any) => pm.displayName === selectedPaymentMethod);
        paymentMethodName = method?.name || null;
      }

      refetch({
        exchangeType: activeTab === 'buy' ? 'SELL' : 'BUY',
        tokenType: selectedCrypto,
        paymentMethod: paymentMethodName,
        countryCode: selectedCountry?.[2]
      });
    }
  }, [activeTab, selectedCrypto, selectedPaymentMethod, selectedCountry, refetch, paymentMethodsData]);

  // Note: Payment method name conversion is now done inline in refetch calls to avoid hoisting issues

  // Search function to apply all current filters - memoized to prevent re-renders
  const handleSearch = React.useCallback(() => {
    // Convert display name to internal name inline
    let paymentMethodName = null;
    if (selectedPaymentMethod !== 'Todos los métodos' && paymentMethodsData?.p2pPaymentMethods) {
      const method = paymentMethodsData.p2pPaymentMethods.find((pm: any) => pm.displayName === selectedPaymentMethod);
      paymentMethodName = method?.name || null;
    }

    // Apply all filters including amount, rate ranges, and other advanced filters
    refetch({
      exchangeType: activeTab === 'buy' ? 'SELL' : 'BUY',
      tokenType: selectedCrypto,
      paymentMethod: paymentMethodName,
      countryCode: selectedCountry?.[2]
      // Note: Additional filters like amount, minRate, maxRate could be added here
      // when the backend GraphQL schema supports them
    });
  }, [activeTab, selectedCrypto, selectedPaymentMethod, selectedCountry, paymentMethodsData, refetch]);

  // Filter offers client-side by amount and advanced filters
  const filteredOffers = React.useMemo(() => {
    const offers = offersData?.p2pOffers || [];
    
    // Apply client-side filtering
    
    return offers.filter((offer: any) => {
      // 1. Filter by amount within operation limits
      if (amount && amount.trim() !== '') {
        const searchAmount = parseFloat(amount.replace(/,/g, ''));
        if (!isNaN(searchAmount) && searchAmount > 0) {
          const minAmount = parseFloat(offer.minAmount?.toString().replace(/,/g, '') || '0');
          const maxAmount = parseFloat(offer.maxAmount?.toString().replace(/,/g, '') || '0');
          
          // Check if search amount falls within the offer's "Límite por operación"
          if (searchAmount < minAmount || searchAmount > maxAmount) {
            return false;
          }
        }
      }
      
      // 2. Filter by rate range (Tasa min/max)
      const hasMinRate = minRate && minRate.trim() !== '';
      const hasMaxRate = maxRate && maxRate.trim() !== '';
      
      // Apply rate filtering if specified
      
      // Only apply rate filtering if at least one rate filter is provided
      if (hasMinRate || hasMaxRate) {
        // Parse the offer rate
        let offerRate = 0;
        if (offer.rate !== undefined && offer.rate !== null) {
          offerRate = parseFloat(offer.rate.toString().replace(/,/g, ''));
        }
        
        // Skip offers without valid rates when rate filters are active
        if (isNaN(offerRate) || offerRate <= 0) {
          return false;
        }
        
        // Apply minimum rate filter (if provided)
        if (hasMinRate) {
          const minRateValue = parseFloat(minRate.replace(/,/g, ''));
          if (!isNaN(minRateValue) && offerRate < minRateValue) {
            return false;
          }
        }
        
        // Apply maximum rate filter (if provided) 
        if (hasMaxRate) {
          const maxRateValue = parseFloat(maxRate.replace(/,/g, ''));
          if (!isNaN(maxRateValue) && offerRate > maxRateValue) {
            return false;
          }
        }
      }
      
      // 3. Filter by verification status (Verificados)
      if (filterVerified) {
        const isVerified = offer.userStats?.isVerified || false;
        if (!isVerified) {
          return false;
        }
      }
      
      // 4. Filter by activity status (En línea -> "Activos hoy")
      if (filterOnline) {
        // Consider user "active" if they've been seen within the last 6 hours
        const lastSeen = offer.userStats?.lastSeenOnline;
        if (!lastSeen) {
          return false;
        }
        
        const lastSeenDate = new Date(lastSeen);
        const now = new Date();
        const sixHoursAgo = new Date(now.getTime() - 6 * 60 * 60 * 1000);
        
        if (lastSeenDate < sixHoursAgo) {
          return false;
        }
      }
      
      // 5. Filter by high volume (+100 ops)
      if (filterHighVolume) {
        const totalTrades = offer.userStats?.totalTrades || 0;
        if (totalTrades < 100) {
          return false;
        }
      }
      
      return true; // Offer passes all filters
    });
  }, [offersData?.p2pOffers, amount, minRate, maxRate, filterVerified, filterOnline, filterHighVolume]);

  // Calculate average rate from filtered offers
  const averageRate = React.useMemo(() => {
    if (filteredOffers.length === 0) {
      return 0;
    }
    
    // Get valid rates and sort to calculate median-based average (reduces outlier impact)
    const validRates = filteredOffers
      .map((offer: any) => parseFloat(offer.rate?.toString() || '0'))
      .filter((rate: number) => rate > 0)
      .sort((a: number, b: number) => a - b);
    
    if (validRates.length === 0) {
      return 0;
    }
    
    // Use trimmed mean (remove top and bottom 10% to reduce outlier impact)
    const trimPercent = 0.1;
    const trimCount = Math.floor(validRates.length * trimPercent);
    const trimmedRates = validRates.slice(trimCount, validRates.length - trimCount);
    
    if (trimmedRates.length === 0) {
      // If too few rates for trimming, use simple average
      return validRates.reduce((sum, rate) => sum + rate, 0) / validRates.length;
    }
    
    return trimmedRates.reduce((sum, rate) => sum + rate, 0) / trimmedRates.length;
  }, [filteredOffers]);

  // Debug: Log final results
  React.useEffect(() => {
    const hasMinRate = minRate && minRate.trim() !== '';
    const hasMaxRate = maxRate && maxRate.trim() !== '';
    if (hasMinRate || hasMaxRate) {
      console.log(`📊 Final results: ${filteredOffers.length} offers out of ${offersData?.p2pOffers?.length || 0} total`);
    }
  }, [filteredOffers.length, minRate, maxRate, offersData?.p2pOffers?.length]);

  // Create ref to store the current animation
  const currentAnimation = useRef<Animated.CompositeAnimation | null>(null);

  // Animate refresh button when loading
  useEffect(() => {
    if (offersLoading) {
      // Reset to 0 first, then start spinning animation
      refreshRotation.setValue(0);
      currentAnimation.current = Animated.loop(
        Animated.timing(refreshRotation, {
          toValue: 1,
          duration: 800,
          useNativeDriver: true,
        })
      );
      currentAnimation.current.start();
    } else {
      // Stop spinning and reset
      if (currentAnimation.current) {
        currentAnimation.current.stop();
        currentAnimation.current = null;
      }
      refreshRotation.stopAnimation();
      refreshRotation.setValue(0);
    }
  }, [offersLoading]);

  // Cleanup animation on unmount
  useEffect(() => {
    return () => {
      refreshRotation.stopAnimation();
    };
  }, []);
  const lastScrollY = useRef(0);
  const scrollViewRef = useRef<any>(null);
  const amountInputRef = useRef<TextInputType>(null);
  const minRateInputRef = useRef<TextInputType>(null);
  const maxRateInputRef = useRef<TextInputType>(null);
  // Removed forceHeaderVisible state as it was causing unnecessary re-renders
  const [headerHeight, setHeaderHeight] = useState(0);
  const [paymentModalVisible, setPaymentModalVisible] = useState(false);
  const [activeList, setActiveList] = useState<'offers' | 'trades'>('offers');
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();

  // Reset header when screen comes into focus
  useEffect(() => {
    const unsubscribe = navigation.addListener('focus', () => {
      // Reset header state when screen is focused
      scrollY.stopAnimation();
      scrollY.setValue(0);
      scrollY.setOffset(0);
      lastScrollY.current = 0;
      
      // Removed timeout to prevent re-renders
    });

    return unsubscribe;
  }, [navigation]);

  // Initialize header state on mount
  useEffect(() => {
    // Ensure header starts in the correct state
    scrollY.stopAnimation();
    scrollY.setValue(0);
    lastScrollY.current = 0;
    
    // Removed timeout to prevent re-renders
  }, []);



  // Calculate local amount based on crypto amount and rate - memoized to prevent re-creation
  const calculateLocalAmount = React.useCallback((cryptoAmount: string, rate: string) => {
    const numAmount = parseFloat(cryptoAmount.replace(/,/g, ''));
    const numRate = parseFloat(rate);
    if (isNaN(numAmount) || isNaN(numRate)) return '';
    return (numAmount * numRate).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }, []);

  // Calculate crypto amount based on local amount and rate - memoized to prevent re-creation
  const calculateCryptoAmount = React.useCallback((localAmount: string, rate: string) => {
    const numAmount = parseFloat(localAmount.replace(/,/g, ''));
    const numRate = parseFloat(rate);
    if (isNaN(numAmount) || isNaN(numRate)) return '';
    return (numAmount / numRate).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }, []);

  // Removed handleAmountChange - now handled inside AmountInputSection

  // Removed handleLocalAmountChange - not used anymore

  // Handle scroll for header visibility
  const handleScroll = (event: any) => {
    const currentScrollY = event.nativeEvent.contentOffset.y;
    const scrollDifference = currentScrollY - lastScrollY.current;
    
    if (Math.abs(scrollDifference) > 10) {
      // Removed forceHeaderVisible updates to prevent re-renders
      
      lastScrollY.current = currentScrollY;
    }
    
    scrollY.setValue(currentScrollY);
  };

  // Reset scroll position when switching between tabs
  const resetScrollPosition = () => {
    // Force header to be fully visible immediately
    
    // Complete reset of scroll system
    scrollY.stopAnimation(); // Stop any ongoing animations
    scrollY.setValue(0);
    scrollY.setOffset(0);
    scrollY.flattenOffset(); // Ensure animated value is properly reset
    lastScrollY.current = 0;
    
    // Immediate scroll to top with no animation
    if (scrollViewRef.current) {
      scrollViewRef.current.scrollTo({ y: 0, animated: false });
    }
    
    // Ensure complete reset with multiple checkpoints
    const performReset = () => {
      scrollY.setValue(0);
      scrollY.setOffset(0);
      lastScrollY.current = 0;
      
      if (scrollViewRef.current) {
        scrollViewRef.current.scrollTo({ y: 0, animated: false });
      }
    };
    
    // Immediate reset
    performReset();
    
    // Additional resets to ensure completeness
    setTimeout(performReset, 50);
    setTimeout(performReset, 150);
    
    // Removed timeout to prevent re-renders
  };

  const onSelectPaymentMethod = (method: string) => {
    setSelectedPaymentMethod(method);
    setPaymentModalVisible(false);
  };

  // Memoized callbacks for AmountInputSection
  const handleOpenPaymentModal = React.useCallback(() => {
    setPaymentModalVisible(true);
  }, []);

  // Memoized amount update to prevent re-renders
  const handleAmountUpdate = React.useCallback((value: string) => {
    setAmount(value);
  }, []);

  const handleSelectOffer = (offer: any, action: 'profile' | 'trade') => {
    // Map real GraphQL offer data to navigation format
    const userName = offer.user ? `${offer.user.firstName} ${offer.user.lastName?.charAt(0)}.` : 'Usuario';
    const userStats = offer.userStats || {};
    const completedTrades = userStats.completedTrades || 0;
    const successRate = parseFloat(userStats.successRate || '0');
    const isVerified = userStats.isVerified || false;
    
    // Calculate activity status for lastSeen
    const getActivityText = () => {
      const lastSeen = userStats.lastSeenOnline;
      if (!lastSeen) return 'Sin actividad reciente';
      
      const lastSeenDate = new Date(lastSeen);
      const hoursAgo = (Date.now() - lastSeenDate.getTime()) / (1000 * 60 * 60);
      
      if (hoursAgo < 2) return 'Activo recientemente';
      if (hoursAgo < 6) return 'Activo hoy';
      if (hoursAgo < 24) return 'Visto hoy';
      return 'Inactivo';
    };
    
    // Calculate response time text
    const getResponseTimeText = () => {
      const avgResponseMinutes = userStats.avgResponseTime;
      if (avgResponseMinutes === null || avgResponseMinutes === undefined) {
        return 'Sin datos';
      }
      if (avgResponseMinutes <= 15) return 'Responde rápido';
      if (avgResponseMinutes <= 60) return 'Responde < 1h';
      if (avgResponseMinutes <= 240) return 'Responde < 4h';
      return 'Responde lento';
    };

    const mappedOffer = {
      id: offer.id.toString(),
      name: userName,
      rate: offer.rate.toString(),
      limit: `${offer.minAmount} - ${offer.maxAmount}`,
      available: offer.availableAmount.toString(),
      paymentMethods: offer.paymentMethods || [],
      responseTime: getResponseTimeText(),
      completedTrades: completedTrades,
      successRate: successRate,
      verified: isVerified,
      isOnline: userStats.lastSeenOnline && (Date.now() - new Date(userStats.lastSeenOnline).getTime()) < 2 * 60 * 60 * 1000, // Active within 2 hours
      lastSeen: getActivityText(),
      terms: offer.terms || '', // Include trader's custom terms
    };

    if (action === 'profile') {
      // Navigate to TraderProfile screen
      navigation.navigate('TraderProfile', { 
        offer: mappedOffer, 
        crypto: selectedCrypto 
      });
    } else if (action === 'trade') {
      // Navigate to TradeConfirm screen
      navigation.navigate('TradeConfirm', { 
        offer: mappedOffer, 
        crypto: selectedCrypto,
        tradeType: activeTab as 'buy' | 'sell'
      });
    }
  };

  // Enhanced Offer Card Component
  const OfferCard = ({ offer, crypto }: { offer: any, crypto: 'cUSD' | 'CONFIO' }) => {
    // Extract user info from the real offer structure
    const userName = offer.user ? `${offer.user.firstName} ${offer.user.lastName?.charAt(0)}.` : 'Usuario';
    const userStats = offer.userStats || {};
    const completedTrades = userStats.completedTrades || 0;
    const successRate = parseFloat(userStats.successRate || '0'); // Convert string to number
    const responseTime = offer.responseTimeMinutes || 15;
    const isVerified = userStats.isVerified || false;
    
    // Calculate simple activity status instead of real-time online
    const getActivityStatus = () => {
      const lastSeen = userStats.lastSeenOnline;
      if (!lastSeen) return { text: 'Sin actividad reciente', isActive: false };
      
      const lastSeenDate = new Date(lastSeen);
      const hoursAgo = (Date.now() - lastSeenDate.getTime()) / (1000 * 60 * 60);
      
      if (hoursAgo < 2) return { text: 'Activo recientemente', isActive: true };
      if (hoursAgo < 6) return { text: 'Activo hoy', isActive: true };
      if (hoursAgo < 24) return { text: 'Visto hoy', isActive: false };
      return { text: 'Inactivo', isActive: false };
    };
    
    const activityStatus = getActivityStatus();
    
    return (
      <View style={styles.offerCard}>
        <View style={styles.offerHeader}>
          <View style={styles.offerUser}>
            <View style={styles.avatarContainer}>
              <Text style={styles.avatarText}>{userName.charAt(0)}</Text>
              {activityStatus.isActive && <View style={styles.onlineIndicator} />}
            </View>
            <View style={styles.userInfoContainer}>
              <View style={styles.userNameContainer}>
                <Text style={styles.userName}>{userName}</Text>
                {isVerified && (
                  <Icon name="shield" size={16} color={colors.accent} style={styles.verifiedIcon} />
                )}
              </View>
              <Text style={styles.tradeCount}>
                {completedTrades === 0 ? 'Nuevo trader' : `${completedTrades} operaciones`}
              </Text>
              <Text style={styles.successRate}>
                {completedTrades === 0 ? 'Sin historial' : `${successRate}% completado`}
              </Text>
              <Text style={[styles.activityStatus, activityStatus.isActive && styles.activeStatus]}>
                {activityStatus.text}
              </Text>
            </View>
          </View>
          <View style={styles.offerRateContainer}>
            <Text style={styles.rateValue}>{formatAmount.withCode(offer.rate)}</Text>
            <View style={styles.responseTime}>
              <Icon name="clock" size={12} color="#6B7280" />
              <Text style={styles.responseTimeText}>
                {(() => {
                  // Use real avgResponseTime from userStats if available
                  const avgResponseMinutes = offer.userStats?.avgResponseTime || null;
                  
                  if (avgResponseMinutes === null || avgResponseMinutes === undefined) {
                    return 'Sin datos';
                  }
                  
                  // Convert to response categories based on actual data
                  if (avgResponseMinutes <= 15) {
                    return 'Responde rápido';
                  } else if (avgResponseMinutes <= 60) {
                    return 'Responde < 1h';
                  } else if (avgResponseMinutes <= 240) {
                    return 'Responde < 4h';
                  } else {
                    return 'Responde lento';
                  }
                })()}
              </Text>
            </View>
          </View>
        </View>

      <View style={styles.offerDetails}>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Límite por operación</Text>
          <Text style={styles.detailValue}>{offer.minAmount} - {offer.maxAmount} {crypto}</Text>
        </View>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Disponible</Text>
          <Text style={styles.detailValue}>{offer.availableAmount} {crypto}</Text>
        </View>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Métodos de pago</Text>
          <View style={styles.paymentMethodsContainer}>
            <Text style={styles.detailValue}>
              {(() => {
                const methods = offer.paymentMethods || [];
                if (methods.length === 0) return 'N/A';
                
                const maxVisible = 2; // Show first 2 methods
                const visibleMethods = methods.slice(0, maxVisible);
                const remainingCount = methods.length - maxVisible;
                
                let text = visibleMethods.map((pm: any) => pm.displayName).join(', ');
                if (remainingCount > 0) {
                  text += `, +${remainingCount} más`;
                }
                
                return text;
              })()}
            </Text>
          </View>
        </View>
      </View>

      <View style={styles.offerActions}>
        <TouchableOpacity 
            style={styles.detailsButton}
            onPress={() => handleSelectOffer(offer, 'profile')}
        >
          <Text style={styles.detailsButtonText}>Ver Perfil</Text>
        </TouchableOpacity>
        <TouchableOpacity 
            style={styles.buyButton}
            onPress={() => handleSelectOffer(offer, 'trade')}
        >
          <Text style={styles.buyButtonText}>{activeTab === 'buy' ? 'Comprar' : 'Vender'}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
  };

  const ActiveTradeCard = ({ trade }: { trade: ActiveTrade }) => {
    const formatTime = (seconds: number) => {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${minutes}:${secs.toString().padStart(2, '0')}`;
    };

    const getStepText = (step: number) => {
        const steps: { [key: number]: string } = { 1: "Realizar pago", 2: "Confirmar pago", 3: "Esperando verificación", 4: "Completado" };
        return steps[step] || "En proceso";
    };

    return (
        <View style={styles.activeTradeCard}>
            <View style={styles.tradeHeader}>
                <View style={styles.tradeUser}>
                    <View style={styles.avatarContainer}>
                        <Text style={styles.avatarText}>{trade.trader.name.charAt(0)}</Text>
                    </View>
                    <View>
                        <Text style={styles.userName}>{trade.trader.name}</Text>
                        <Text style={styles.tradeDetails}>{trade.amount} {trade.crypto} por {formatAmount.withCode(trade.totalBs)}</Text>
                    </View>
                </View>
                <View style={styles.timerBadge}>
                    <Text style={styles.timerText}>{formatTime(trade.timeRemaining)}</Text>
                </View>
            </View>
            <View style={styles.progressContainer}>
                <Text style={styles.stepText}>Paso {trade.step}/{trade.totalSteps}: {getStepText(trade.step)}</Text>
                <View style={styles.progressBar}>
                    <View style={[styles.progressFill, { width: `${(trade.step / trade.totalSteps) * 100}%` }]} />
                </View>
            </View>
            <TouchableOpacity 
                style={styles.continueButton}
                onPress={() => {
                    navigation.navigate('ActiveTrade', {
                        trade: {
                            id: trade.id,
                            trader: {
                                name: trade.trader.name,
                                isOnline: trade.trader.isOnline,
                                verified: trade.trader.verified,
                                lastSeen: trade.trader.lastSeen,
                                responseTime: trade.trader.responseTime,
                            },
                            amount: trade.amount,
                            crypto: trade.crypto,
                            totalBs: trade.totalBs,
                            paymentMethod: trade.paymentMethod,
                            rate: trade.rate,
                            step: trade.step,
                            timeRemaining: trade.timeRemaining,
                            tradeType: trade.tradeType,
                        }
                    });
                }}
            >
                <Text style={styles.continueButtonText}>Continuar</Text>
            </TouchableOpacity>
        </View>
    );
  };

  // Create a separate component for the amount input to prevent re-renders
  const AmountInputSection = React.memo(({ 
    initialAmount,
    selectedCrypto, 
    selectedPaymentMethod,
    onAmountUpdate,
    onPaymentMethodPress,
    onSearchPress
  }: {
    initialAmount: string;
    selectedCrypto: 'cUSD' | 'CONFIO';
    selectedPaymentMethod: string;
    onAmountUpdate: (value: string) => void;
    onPaymentMethodPress: () => void;
    onSearchPress: () => void;
  }) => {
    // Local state for the input to prevent parent re-renders
    const [localAmount, setLocalAmount] = useState(initialAmount);
    const inputRef = useRef<TextInputType>(null);
    
    // Sync with parent state when needed (e.g., on search or blur)
    const syncAmount = React.useCallback(() => {
      if (localAmount !== initialAmount) {
        onAmountUpdate(localAmount);
      }
    }, [localAmount, initialAmount, onAmountUpdate]);
    
    // Update local state when typing
    const handleLocalChange = React.useCallback((value: string) => {
      setLocalAmount(value);
    }, []);
    
    // Sync when search is pressed
    const handleSearchPress = React.useCallback(() => {
      syncAmount();
      onSearchPress();
    }, [syncAmount, onSearchPress]);
    
    // Update local state if parent state changes externally
    useEffect(() => {
      setLocalAmount(initialAmount);
    }, [initialAmount]);
    
    return (
      <>
        <View style={styles.amountInputContainer}>
          <TextInput
            ref={inputRef}
            style={styles.amountInput}
            value={localAmount}
            onChangeText={handleLocalChange}
            onBlur={syncAmount}
            placeholder="Monto mínimo"
            keyboardType="decimal-pad"
            autoCorrect={false}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            returnKeyType="done"
            blurOnSubmit={false}
          />
          <Text style={styles.currencyLabel}>{selectedCrypto}</Text>
        </View>

        <View style={styles.paymentMethodContainer}>
          <TouchableOpacity
            style={styles.paymentMethodInput}
            onPress={onPaymentMethodPress}
          >
            <Text style={styles.paymentMethodInputText} numberOfLines={1}>
              {selectedPaymentMethod}
            </Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity style={styles.searchButton} onPress={handleSearchPress}>
          <Icon name="search" size={16} color="#fff" />
        </TouchableOpacity>
      </>
    );
  });

  // Add display name for debugging
  AmountInputSection.displayName = 'AmountInputSection';

  // Create isolated FilterInput component to prevent keyboard issues
  const FilterInput = React.memo(React.forwardRef<TextInputType, {
    placeholder: string;
    value: string;
    onChangeText: (value: string) => void;
  }>(({ placeholder, value, onChangeText }, ref) => {
    const [localValue, setLocalValue] = useState(value);
    const inputRef = useRef<TextInputType>(null);
    const debounceTimer = useRef<NodeJS.Timeout | null>(null);
    
    // Use forwarded ref if provided, otherwise use internal ref
    const actualRef = ref || inputRef;
    
    // Sync with parent when input loses focus
    const syncValue = React.useCallback(() => {
      // Cancel any pending debounced update
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
        debounceTimer.current = null;
      }
      
      // Immediately sync if there's a difference
      if (localValue !== value) {
        onChangeText(localValue);
      }
    }, [localValue, value, onChangeText]);
    
    // Debounced sync to parent (delays sync to prevent rapid re-renders)
    const debouncedSync = React.useCallback((text: string) => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
      
      debounceTimer.current = setTimeout(() => {
        onChangeText(text);
      }, 500); // 500ms delay - responsive but prevents rapid re-renders
    }, [onChangeText]);
    
    // Update local state when typing and schedule debounced sync
    const handleLocalChange = React.useCallback((text: string) => {
      setLocalValue(text);
      debouncedSync(text);
    }, [debouncedSync]);
    
    // Update local state if parent value changes externally
    useEffect(() => {
      setLocalValue(value);
    }, [value]);
    
    // Cleanup timer on unmount
    useEffect(() => {
      return () => {
        if (debounceTimer.current) {
          clearTimeout(debounceTimer.current);
        }
      };
    }, []);
    
    return (
      <TextInput
        ref={actualRef}
        style={styles.filterInput}
        placeholder={placeholder}
        keyboardType="decimal-pad"
        value={localValue}
        onChangeText={handleLocalChange}
        onBlur={syncValue}
        autoCorrect={false}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        returnKeyType="done"
        blurOnSubmit={false}
      />
    );
  }));

  // Add display name for debugging
  FilterInput.displayName = 'FilterInput';

  // Header component - memoized to prevent re-renders
  const Header = React.memo(() => {
    const scrollYClamped = Animated.diffClamp(scrollY, 0, headerHeight);

    const headerTranslateY = scrollYClamped.interpolate({
        inputRange: [0, headerHeight],
        outputRange: [0, -headerHeight],
        extrapolate: 'clamp',
    });

    return (
        <Animated.View 
            onLayout={(event) => {
                const { height } = event.nativeEvent.layout;
                if (height > 0 && height !== headerHeight) {
                    // console.log('Header height changed:', { old: headerHeight, new: height });
                    setHeaderHeight(height);
                }
            }}
            style={[
                styles.header,
                {
                    transform: [{ translateY: headerTranslateY }],
                }
            ]}
        >
            {activeTrades.length > 0 && (
                <TouchableOpacity 
                    style={styles.activeTradesAlert}
                    onPress={() => {
                        setActiveList('trades');
                        resetScrollPosition();
                    }}
                >
                    <Icon name="alert-triangle" size={16} color={colors.primary} />
                    <Text style={styles.activeTradesText}>
                        {activeTrades.length} intercambio{activeTrades.length > 1 ? 's' : ''} activo{activeTrades.length > 1 ? 's' : ''} - Toca para continuar
                    </Text>
                    <Icon name="chevron-right" size={16} color={colors.primary} />
                </TouchableOpacity>
            )}

            <View style={styles.mainTabsContainer}>
                <TouchableOpacity
                    style={[styles.mainTab, activeList === 'offers' && styles.activeMainTab]}
                    onPress={() => {
                        setActiveList('offers');
                        resetScrollPosition();
                    }}
                >
                    <Text style={[styles.mainTabText, activeList === 'offers' && styles.activeMainTabText]}>
                        Ofertas
                    </Text>
                </TouchableOpacity>
                <TouchableOpacity
                    style={[styles.mainTab, activeList === 'trades' && styles.activeMainTab]}
                    onPress={() => {
                        setActiveList('trades');
                        resetScrollPosition();
                    }}
                >
                    <Text style={[styles.mainTabText, activeList === 'trades' && styles.activeMainTabText]}>
                        Mis Intercambios
                    </Text>
                    {activeTrades.length > 0 && (
                        <View style={styles.notificationBadge}>
                            <Text style={styles.notificationText}>{activeTrades.length}</Text>
                        </View>
                    )}
                </TouchableOpacity>
            </View>

            {activeList === 'offers' && (
                <>
                    {/* Buy/Sell Toggle */}
                    <View style={styles.tabContainer}>
                        <TouchableOpacity
                            style={[styles.tab, activeTab === 'buy' && styles.activeTab]}
                            onPress={() => {
                                setActiveTab('buy');
                                resetScrollPosition();
                            }}
                        >
                            <Text style={[styles.tabText, activeTab === 'buy' && styles.activeTabText]}>Comprar</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={[styles.tab, activeTab === 'sell' && styles.activeTab]}
                            onPress={() => {
                                setActiveTab('sell');
                                resetScrollPosition();
                            }}
                        >
                            <Text style={[styles.tabText, activeTab === 'sell' && styles.activeTabText]}>Vender</Text>
                        </TouchableOpacity>
                    </View>

                    {/* Crypto Selection */}
                    <View style={styles.cryptoSelector}>
                        <TouchableOpacity
                            style={[styles.cryptoButton, selectedCrypto === 'cUSD' && styles.selectedCryptoButton]}
                            onPress={() => {
                                setSelectedCrypto('cUSD');
                                resetScrollPosition();
                            }}
                        >
                            <Text style={[styles.cryptoButtonText, selectedCrypto === 'cUSD' && styles.selectedCryptoButtonText]}>
                                Confío Dollar ($cUSD)
                            </Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={[styles.cryptoButton, selectedCrypto === 'CONFIO' && styles.selectedCryptoButton]}
                            onPress={() => {
                                setSelectedCrypto('CONFIO');
                                resetScrollPosition();
                            }}
                        >
                            <Text style={[styles.cryptoButtonText, selectedCrypto === 'CONFIO' && styles.selectedCryptoButtonText]}>
                                Confío ($CONFIO)
                            </Text>
                        </TouchableOpacity>
                    </View>

                    {/* Amount, Payment Method, and Search */}
                    <View style={[
                        styles.searchContainer,
                        showAdvancedFilters && styles.searchContainerExtended
                    ]}>
                        <AmountInputSection
                            initialAmount={amount}
                            selectedCrypto={selectedCrypto}
                            selectedPaymentMethod={selectedPaymentMethod}
                            onAmountUpdate={handleAmountUpdate}
                            onPaymentMethodPress={handleOpenPaymentModal}
                            onSearchPress={handleSearch}
                        />
                    </View>

                    {/* Rate and Filter Controls */}
                    <View style={[
                        styles.rateFilterContainer,
                        showAdvancedFilters && styles.rateFilterContainerExtended
                    ]}>
                        <Text style={styles.averageRate}>
                            {averageRate > 0 ? formatAmount.withCode(averageRate) : 'Sin datos'} promedio
                        </Text>
                        <View style={styles.filterControls}>
                            <TouchableOpacity
                                style={[
                                    styles.filterButton, 
                                    (showAdvancedFilters || minRate || maxRate || filterVerified || filterOnline || filterHighVolume) && styles.activeFilterButton
                                ]}
                                onPress={() => setShowAdvancedFilters(!showAdvancedFilters)}
                            >
                                <Icon
                                    name="filter"
                                    size={12}
                                    color={(showAdvancedFilters || minRate || maxRate || filterVerified || filterOnline || filterHighVolume) ? colors.primary : '#6B7280'}
                                />
                                {(minRate || maxRate || filterVerified || filterOnline || filterHighVolume) && (
                                    <View style={styles.filterIndicator} />
                                )}
                            </TouchableOpacity>
                            
                            {/* Quick clear filters button - only show when filters are active */}
                            {(amount || minRate || maxRate || filterVerified || filterOnline || filterHighVolume || selectedPaymentMethod !== 'Todos los métodos') && (
                                <TouchableOpacity 
                                    style={styles.quickClearButton}
                                    onPress={() => {
                                        // Clear all filter values
                                        setAmount('');
                                        setMinRate('');
                                        setMaxRate('');
                                        setFilterVerified(false);
                                        setFilterOnline(false);
                                        setFilterHighVolume(false);
                                        setSelectedPaymentMethod('Todos los métodos');
                                        
                                        // Also clear the filter inputs
                                        minRateInputRef.current?.clear();
                                        maxRateInputRef.current?.clear();
                                    }}
                                >
                                    <Icon name="x-circle" size={12} color="#ef4444" />
                                </TouchableOpacity>
                            )}
                            
                            <TouchableOpacity 
                                style={styles.refreshButton}
                                onPress={() => {
                                    // Convert display name to internal name inline
                                    let paymentMethodName = null;
                                    if (selectedPaymentMethod !== 'Todos los métodos' && paymentMethodsData?.p2pPaymentMethods) {
                                        const method = paymentMethodsData.p2pPaymentMethods.find((pm: any) => pm.displayName === selectedPaymentMethod);
                                        paymentMethodName = method?.name || null;
                                    }

                                    refetch({
                                        exchangeType: activeTab === 'buy' ? 'SELL' : 'BUY',
                                        tokenType: selectedCrypto,
                                        paymentMethod: paymentMethodName,
                                        countryCode: selectedCountry?.[2]
                                    });
                                }}
                                disabled={offersLoading}
                            >
                                <Animated.View
                                    style={{
                                        transform: [{
                                            rotate: refreshRotation.interpolate({
                                                inputRange: [0, 1],
                                                outputRange: ['0deg', '360deg']
                                            })
                                        }]
                                    }}
                                >
                                    <Icon 
                                        name="refresh-cw" 
                                        size={12} 
                                        color={offersLoading ? colors.primary : '#6B7280'} 
                                    />
                                </Animated.View>
                            </TouchableOpacity>
                        </View>
                    </View>

                    {/* Advanced Filters */}
                    {showAdvancedFilters && (
                        <>
                            {/* Background fill for the gap */}
                            <View style={styles.filterGapFill} />
                            <View style={styles.advancedFilters}>
                            <View style={styles.filterInputs}>
                                <FilterInput
                                    ref={minRateInputRef}
                                    placeholder="Tasa min."
                                    value={minRate}
                                    onChangeText={setMinRate}
                                />
                                <FilterInput
                                    ref={maxRateInputRef}
                                    placeholder="Tasa max."
                                    value={maxRate}
                                    onChangeText={setMaxRate}
                                />
                            </View>

                            {/* Country Filter */}
                            <View style={styles.countryFilterContainer}>
                                <Text style={styles.filterLabel}>País:</Text>
                                <TouchableOpacity
                                    style={styles.countryFilterSelector}
                                    onPress={openCountryModal}
                                >
                                    <Text style={styles.countryFilterFlag}>{selectedCountry?.[3] || '🌍'}</Text>
                                    <Text style={styles.countryFilterName}>
                                        {selectedCountry?.[0] || 'Todos los países'}
                                    </Text>
                                    <Icon name="chevron-down" size={16} color="#6B7280" />
                                </TouchableOpacity>
                            </View>

                            <View style={styles.filterCheckboxes}>
                                <TouchableOpacity 
                                    style={styles.checkboxItem}
                                    onPress={() => setFilterVerified(!filterVerified)}
                                >
                                    <View style={[styles.checkbox, filterVerified && styles.checkboxChecked]}>
                                        {filterVerified && <Icon name="check" size={12} color="#fff" />}
                                    </View>
                                    <Text style={styles.checkboxLabel}>Verificados</Text>
                                </TouchableOpacity>
                                <TouchableOpacity 
                                    style={styles.checkboxItem}
                                    onPress={() => setFilterOnline(!filterOnline)}
                                >
                                    <View style={[styles.checkbox, filterOnline && styles.checkboxChecked]}>
                                        {filterOnline && <Icon name="check" size={12} color="#fff" />}
                                    </View>
                                    <Text style={styles.checkboxLabel}>Activos hoy</Text>
                                </TouchableOpacity>
                                <TouchableOpacity 
                                    style={styles.checkboxItem}
                                    onPress={() => setFilterHighVolume(!filterHighVolume)}
                                >
                                    <View style={[styles.checkbox, filterHighVolume && styles.checkboxChecked]}>
                                        {filterHighVolume && <Icon name="check" size={12} color="#fff" />}
                                    </View>
                                    <Text style={styles.checkboxLabel}>+100 ops</Text>
                                </TouchableOpacity>
                            </View>

                            <View style={styles.filterActions}>
                                <TouchableOpacity 
                                    style={styles.clearAllButton}
                                    onPress={() => {
                                        // Clear all filter values
                                        setAmount('');
                                        setMinRate('');
                                        setMaxRate('');
                                        setFilterVerified(false);
                                        setFilterOnline(false);
                                        setFilterHighVolume(false);
                                        setSelectedPaymentMethod('Todos los métodos');
                                        
                                        // Also clear the filter inputs
                                        minRateInputRef.current?.clear();
                                        maxRateInputRef.current?.clear();
                                    }}
                                >
                                    <Icon name="refresh-ccw" size={12} color="#6B7280" />
                                    <Text style={styles.clearAllButtonText}>Limpiar Todo</Text>
                                </TouchableOpacity>
                                <TouchableOpacity 
                                    style={styles.applyButton}
                                    onPress={() => {
                                        // Force sync of filter input values by blurring them
                                        // This ensures any typed values are captured before applying filters
                                        minRateInputRef.current?.blur();
                                        maxRateInputRef.current?.blur();
                                        
                                        // Close the advanced filters menu
                                        setShowAdvancedFilters(false);
                                        
                                        // Optional: Also refresh the base data from server
                                        // Convert display name to internal name inline
                                        let paymentMethodName = null;
                                        if (selectedPaymentMethod !== 'Todos los métodos' && paymentMethodsData?.p2pPaymentMethods) {
                                            const method = paymentMethodsData.p2pPaymentMethods.find((pm: any) => pm.displayName === selectedPaymentMethod);
                                            paymentMethodName = method?.name || null;
                                        }

                                        refetch({
                                            exchangeType: activeTab === 'buy' ? 'SELL' : 'BUY',
                                            tokenType: selectedCrypto,
                                            paymentMethod: paymentMethodName,
                                            countryCode: selectedCountry?.[2]
                                        });
                                    }}
                                >
                                    <Text style={styles.applyButtonText}>Aplicar</Text>
                                </TouchableOpacity>
                                <TouchableOpacity
                                    style={styles.closeButton}
                                    onPress={() => setShowAdvancedFilters(false)}
                                >
                                    <Icon name="x" size={12} color="#6B7280" />
                                </TouchableOpacity>
                            </View>
                        </View>
                        </>
                    )}
                </>
            )}
        </Animated.View>
    );
  });

  // Add display name for debugging
  Header.displayName = 'Header';

  const renderContent = () => {
    if (activeList === 'offers') {
      const offers = filteredOffers; // Use filtered offers instead of raw data
      
      if (offersLoading) {
        return (
          <View style={[styles.offersList, { padding: 16 }]}>
            <Text style={styles.loadingText}>Cargando ofertas...</Text>
          </View>
        );
      }
      
      if (offersError) {
        return (
          <View style={[styles.offersList, { padding: 16 }]}>
            <Text style={styles.errorText}>Error cargando ofertas: {offersError.message}</Text>
          </View>
        );
      }
      
      if (offers.length === 0) {
        // Show different message based on active filters
        const hasAmount = amount && amount.trim() !== '';
        const hasRateFilters = (minRate && minRate.trim() !== '') || (maxRate && maxRate.trim() !== '');
        const hasAdvancedFilters = filterVerified || filterOnline || filterHighVolume;
        const hasAnyFilters = hasAmount || hasRateFilters || hasAdvancedFilters;
        
        let emptyMessage = 'No hay ofertas disponibles';
        if (hasAnyFilters) {
          emptyMessage = 'No hay ofertas que coincidan con los filtros aplicados';
        }
        
        return (
          <View style={[styles.offersList, { padding: 16 }]}>
            <Text style={styles.emptyText}>{emptyMessage}</Text>
            {hasAnyFilters && (
              <TouchableOpacity 
                style={styles.clearFiltersButton}
                onPress={() => {
                  setAmount('');
                  setMinRate('');
                  setMaxRate('');
                  setFilterVerified(false);
                  setFilterOnline(false);
                  setFilterHighVolume(false);
                }}
              >
                <Text style={styles.clearFiltersText}>Limpiar filtros</Text>
              </TouchableOpacity>
            )}
          </View>
        );
      }
      
      return (
        <View style={[styles.offersList, { padding: 16 }]}>
          {offers.map((offer: any) => (
            <OfferCard key={offer.id} offer={offer} crypto={selectedCrypto} />
          ))}
        </View>
      );
    }
    
    if (activeList === 'trades') {
      return (
        <View style={[styles.offersList, { padding: 16 }]}>
          {activeTrades.length > 0 ? (
            <>
              {activeTrades.map((trade) => (
                <ActiveTradeCard key={trade.id} trade={trade} />
              ))}
            </>
          ) : (
            <View style={styles.emptyState}>
              <Icon name="inbox" size={48} color="#9CA3AF" style={styles.emptyIcon} />
              <Text style={styles.emptyTitle}>No hay intercambios activos</Text>
              <Text style={styles.emptyText}>
                Cuando inicies un intercambio, aparecerá aquí para que puedas darle seguimiento.
              </Text>
            </View>
          )}
        </View>
      );
    }
    
    return null;
  };

  return (
    <View style={styles.container}>
      <Header />
      
      <Modal
        animationType="fade"
        transparent={true}
        visible={paymentModalVisible}
        onRequestClose={() => {
          setPaymentModalVisible(!paymentModalVisible);
        }}
      >
        <TouchableWithoutFeedback onPress={() => setPaymentModalVisible(false)}>
          <View style={styles.modalOverlay}>
            <TouchableWithoutFeedback>
              <View style={styles.modalContent}>
                <Text style={styles.modalTitle}>Métodos de pago</Text>
                {paymentMethods.map((method, index) => (
                  <TouchableOpacity 
                    key={index} 
                    style={styles.modalItem}
                    onPress={() => onSelectPaymentMethod(method)}
                  >
                    <Text style={styles.modalItemText}>{method}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </TouchableWithoutFeedback>
          </View>
        </TouchableWithoutFeedback>
      </Modal>

      {/* Country Selection Modal */}
      <Modal
        animationType="slide"
        transparent={false}
        visible={showCountryModal}
        onRequestClose={closeCountryModal}
      >
        <View style={styles.modalContainer}>
          <View style={styles.modalHeaderCountry}>
            <TouchableOpacity onPress={closeCountryModal}>
              <Icon name="x" size={24} color="#1F2937" />
            </TouchableOpacity>
            <Text style={styles.modalTitleCountry}>Filtrar por País</Text>
            <TouchableOpacity onPress={() => selectCountry(null)}>
              <Text style={styles.clearText}>Limpiar</Text>
            </TouchableOpacity>
          </View>
          <FlatList
            data={countries}
            keyExtractor={(item, index) => `${item[2]}-${index}`}
            renderItem={({ item }) => (
              <TouchableOpacity
                style={[
                  styles.countryModalItem,
                  selectedCountry?.[2] === item[2] && styles.countryModalItemSelected
                ]}
                onPress={() => selectCountry(item)}
              >
                <Text style={styles.countryModalFlag}>{item[3]}</Text>
                <Text style={styles.countryModalName}>{item[0]}</Text>
                <Text style={styles.countryModalCode}>{item[1]}</Text>
                {selectedCountry?.[2] === item[2] && (
                  <Icon name="check" size={20} color={colors.primary} />
                )}
              </TouchableOpacity>
            )}
            showsVerticalScrollIndicator={false}
          />
        </View>
      </Modal>

      <Animated.ScrollView 
        style={styles.content} 
        contentContainerStyle={{ paddingTop: headerHeight, paddingBottom: 100 }}
        onScroll={Animated.event(
            [{ nativeEvent: { contentOffset: { y: scrollY } } }],
            { useNativeDriver: true }
        )}
        scrollEventThrottle={16}
        bounces={false}
      >
        {renderContent()}
      </Animated.ScrollView>

      {/* Floating Action Button */}
      <TouchableOpacity 
        style={styles.fab}
        onPress={() => navigation.navigate('CreateOffer')}
      >
        <Icon name="plus" size={24} color="#fff" />
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    padding: 16,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F2937',
    marginBottom: 16,
  },
  header: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 100,
    backgroundColor: '#fff',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 4,
      },
    }),
  },
  headerTitle: {
    marginBottom: 16,
  },
  headerTitleText: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  tabContainer: {
    flexDirection: 'row',
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    marginBottom: 12,
  },
  tab: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
  },
  activeTab: {
    backgroundColor: colors.primary,
    borderRadius: 12,
  },
  tabText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#6B7280',
  },
  activeTabText: {
    color: '#fff',
  },
  cryptoSelector: {
    flexDirection: 'row',
    marginBottom: 12,
    backgroundColor: colors.neutralDark,
    borderRadius: 10,
    padding: 2,
  },
  cryptoButton: {
    flex: 1,
    paddingVertical: 10,
    paddingHorizontal: 8,
    alignItems: 'center',
    borderRadius: 8,
  },
  selectedCryptoButton: {
    backgroundColor: colors.primary,
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
  cryptoButtonText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#6B7280',
    textAlign: 'center',
  },
  selectedCryptoButtonText: {
    color: '#fff',
  },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    gap: 8,
  },
  searchContainerExtended: {
    backgroundColor: '#fff', // White background when filters are open
    marginHorizontal: -12, // Extend to header edges
    paddingHorizontal: 12, // Restore content padding
    paddingTop: 8, // Padding above inputs
    paddingBottom: 20, // Extended padding to reach the filter button area
    marginBottom: -8, // Overlap with rate filter container
  },
  amountInputContainer: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 8,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    minHeight: 48,
  },
  amountInput: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginLeft: 4,
  },
  currencyLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
    marginLeft: 4,
  },
  paymentMethodContainer: {
    flex: 1,
  },
  paymentMethodInput: {
    flex: 1,
    paddingHorizontal: 12,
    backgroundColor: '#f3f4f6',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    justifyContent: 'center',
    minHeight: 48, // Ensure consistent height
  },
  paymentMethodInputText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  searchButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    height: 48,
    width: 48,
  },
  rateFilterContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  rateFilterContainerExtended: {
    backgroundColor: '#fff', // White background when filters are open
    marginHorizontal: -12, // Extend to header edges
    paddingHorizontal: 12, // Restore content padding
    paddingBottom: 16, // Extra padding to fill the gap completely
    marginBottom: -8, // Overlap with advanced filters margin
  },
  averageRate: {
    fontSize: 12,
    color: '#6B7280',
  },
  filterControls: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  filterButton: {
    padding: 6,
    backgroundColor: colors.neutralDark,
    borderRadius: 8,
    position: 'relative',
  },
  activeFilterButton: {
    backgroundColor: colors.primaryLight,
  },
  filterIndicator: {
    position: 'absolute',
    top: 2,
    right: 2,
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#ef4444', // red-500
  },
  quickClearButton: {
    padding: 6,
    backgroundColor: '#fee2e2', // red-100
    borderRadius: 8,
  },
  refreshButton: {
    padding: 6,
    backgroundColor: colors.neutralDark,
    borderRadius: 8,
  },
  advancedFilters: {
    marginTop: 4, // Reduced gap between filter button and advanced filters menu
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
    backgroundColor: '#fff', // Solid white background
    borderRadius: 8,
    padding: 10,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.1,
        shadowRadius: 4,
      },
      android: {
        elevation: 3,
      },
    }),
  },
  filterInputs: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 8,
  },
  filterInput: {
    flex: 1,
    padding: 8,
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    fontSize: 12,
  },
  filterCheckboxes: {
    flexDirection: 'row',
    gap: 16,
    marginBottom: 8,
  },
  checkboxItem: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  checkbox: {
    width: 16,
    height: 16,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: '#6B7280',
    marginRight: 4,
  },
  checkboxLabel: {
    fontSize: 12,
    color: '#6B7280',
  },
  filterActions: {
    flexDirection: 'row',
    gap: 8,
  },
  clearAllButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 4,
    padding: 8,
    backgroundColor: '#f3f4f6', // gray-100
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e5e7eb', // gray-200
  },
  clearAllButtonText: {
    fontSize: 12,
    fontWeight: '500',
    color: '#6B7280',
  },
  applyButton: {
    flex: 1,
    padding: 8,
    backgroundColor: colors.primary,
    borderRadius: 8,
    alignItems: 'center',
  },
  applyButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#fff',
  },
  closeButton: {
    padding: 8,
    backgroundColor: colors.neutralDark,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  offersList: {
    gap: 12,
  },
  offerCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    paddingVertical: 18, // Slightly more vertical padding for better spacing
    borderWidth: 1,
    borderColor: '#E5E7EB',
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
  offerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  offerUser: {
    flexDirection: 'row',
    alignItems: 'flex-start', // Changed from 'center' to allow proper height
    flex: 1,
  },
  avatarContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    position: 'relative',
  },
  avatarText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#4B5563',
  },
  onlineIndicator: {
    position: 'absolute',
    bottom: -2,
    right: -2,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#10B981',
    borderWidth: 2,
    borderColor: '#fff',
  },
  userNameContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  userName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
  },
  verifiedIcon: {
    marginLeft: 4,
  },
  userInfoContainer: {
    flex: 1,
    marginLeft: 12,
    justifyContent: 'space-around',
    minHeight: 50,
  },
  userStats: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  tradeCount: {
    fontSize: 11,
    color: '#6B7280',
    fontWeight: '400',
  },
  bullet: {
    fontSize: 12,
    color: '#6B7280',
    marginHorizontal: 4,
  },
  successRate: {
    fontSize: 11,
    color: '#10B981',
    fontWeight: '500',
  },
  activityStatus: {
    fontSize: 11,
    color: '#9CA3AF', // gray-400 for inactive
    fontWeight: '400',
  },
  activeStatus: {
    color: '#10B981', // green for active
    fontWeight: '500',
  },
  offerRateContainer: {
    alignItems: 'flex-end',
  },
  rateValue: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1F2937',
  },
  responseTime: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  responseTimeText: {
    fontSize: 12,
    color: '#6B7280',
    marginLeft: 2,
  },
  offerDetails: {
    marginBottom: 12,
  },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 6,
  },
  detailLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginRight: 12,
    minWidth: 80,
  },
  detailValue: {
    fontSize: 12,
    fontWeight: '500',
    color: '#1F2937',
    flex: 1,
    textAlign: 'right',
  },
  paymentMethodsContainer: {
    flex: 1,
    alignItems: 'flex-end',
  },
  offerActions: {
    flexDirection: 'row',
    gap: 8,
  },
  detailsButton: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    paddingVertical: 8,
    borderRadius: 8,
    alignItems: 'center',
  },
  detailsButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  buyButton: {
    flex: 1,
    backgroundColor: colors.primary,
    paddingVertical: 8,
    borderRadius: 8,
    alignItems: 'center',
  },
  buyButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#fff',
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  modalContent: {
    width: '80%',
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 20,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.25,
        shadowRadius: 4,
      },
      android: {
        elevation: 5,
      },
    }),
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 16,
    textAlign: 'center',
  },
  modalItem: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#f3f4f6',
  },
  modalItemText: {
    fontSize: 16,
    textAlign: 'center',
  },
  screenContainer: {
    flex: 1,
    backgroundColor: colors.neutral,
  },
  pageHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    paddingTop: 60,
  },
  backButton: {
    marginRight: 16,
  },
  pageTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  screenContent: {
    flex: 1,
    padding: 16,
  },
  profileCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 24,
    alignItems: 'center',
    marginBottom: 16,
  },
  profileName: {
    fontSize: 22,
    fontWeight: 'bold',
    marginVertical: 12,
  },
  summaryCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 24,
    marginBottom: 16,
  },
  summaryTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 16,
  },
  placeholderText: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    marginVertical: 20,
  },
  confirmButton: {
    backgroundColor: colors.primary,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 20,
  },
  confirmButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  pageHeaderTitleContainer: {
    paddingBottom: 16,
  },
  activeTradesAlert: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.primaryLight,
    padding: 12,
    borderRadius: 8,
    marginBottom: 16,
  },
  activeTradesText: {
    color: colors.primary,
    fontWeight: 'bold',
    marginLeft: 8,
  },
  mainTabsContainer: {
    flexDirection: 'row',
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 4,
    marginBottom: 16,
  },
  mainTab: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
  },
  activeMainTab: {
    backgroundColor: '#fff',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 1 },
        shadowOpacity: 0.1,
        shadowRadius: 2,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  mainTabText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
  },
  activeMainTabText: {
    color: '#1F2937',
  },
  notificationBadge: {
    position: 'absolute',
    top: -4,
    right: -4,
    backgroundColor: '#ef4444', // red-500
    borderRadius: 10,
    width: 20,
    height: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  notificationText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  activeTradeCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
  },
  tradeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  tradeUser: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  tradeDetails: {
    fontSize: 12,
    color: '#6B7280',
  },
  timerBadge: {
    backgroundColor: colors.primaryLight,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  timerText: {
    color: colors.primary,
    fontWeight: 'bold',
    fontSize: 12,
  },
  progressContainer: {
    marginBottom: 12,
  },
  stepText: {
    fontSize: 12,
    fontWeight: '500',
    color: '#6B7280',
    marginBottom: 4,
  },
  progressBar: {
    height: 8,
    backgroundColor: colors.neutralDark,
    borderRadius: 4,
  },
  progressFill: {
    height: 8,
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  continueButton: {
    backgroundColor: colors.primary,
    padding: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  continueButtonText: {
    color: '#fff',
    fontWeight: 'bold',
  },
  detailsCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  profileHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
  },
  profileAvatarContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
    position: 'relative',
  },
  profileAvatarText: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#4B5563',
  },
  onlineIndicatorLarge: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: '#10B981',
    borderWidth: 3,
    borderColor: '#fff',
  },
  lastSeenText: {
    color: '#6B7280',
    fontSize: 14,
  },
  profileStatsText: {
    fontSize: 14,
    fontWeight: '500',
  },
  statsGrid: {
    flexDirection: 'row',
    gap: 16,
    marginBottom: 16,
  },
  statBox: {
    flex: 1,
    backgroundColor: colors.neutral,
    padding: 12,
    borderRadius: 8,
  },
  statLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
  },
  statValue: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  paymentMethodRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.neutral,
    padding: 8,
    borderRadius: 8,
  },
  paymentMethodIcon: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  paymentMethodIconText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  paymentMethodName: {
    fontSize: 14,
    fontWeight: '500',
  },
  infoBox: {
    backgroundColor: '#eff6ff', // blue-50
    padding: 12,
    borderRadius: 8,
    flexDirection: 'row',
  },
  infoBoxTitle: {
    color: '#1e40af', // blue-800
    fontWeight: '500',
    marginBottom: 4,
  },
  infoBoxText: {
    color: '#1d4ed8', // blue-700
    fontSize: 14,
  },
  detailValueBold: {
    fontSize: 14,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  bottomButtonContainer: {
    padding: 16,
    backgroundColor: '#fff',
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
  },
  bottomButton: {
    backgroundColor: colors.primary,
    padding: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  bottomButtonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  welcomeCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  welcomeIcon: {
    marginBottom: 12,
  },
  welcomeTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  welcomeText: {
    fontSize: 14,
    color: '#6B7280',
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyIcon: {
    marginBottom: 12,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  fab: {
    position: 'absolute',
    bottom: 24,
    right: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.3,
        shadowRadius: 6,
      },
      android: {
        elevation: 8,
      },
    }),
  },
  filterGapFill: {
    height: 16, // Increased height to ensure complete coverage
    backgroundColor: '#fff', // Pure white background to fill the gap
    marginHorizontal: -16, // Extend beyond header edges to ensure full coverage
    marginTop: 0, // Start immediately after header content
    marginBottom: -8, // Overlap with advanced filters margin
  },
  countryFilterContainer: {
    marginBottom: 8,
  },
  filterLabel: {
    fontSize: 12,
    fontWeight: '500',
    color: '#1F2937',
    marginBottom: 8,
  },
  countryFilterSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F9FAFB', // Slightly different background to distinguish from main background
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#E5E7EB',
    paddingHorizontal: 10,
    paddingVertical: 8,
    minHeight: 36,
  },
  countryFilterFlag: {
    fontSize: 16,
    marginRight: 6,
  },
  countryFilterName: {
    flex: 1,
    fontSize: 13,
    color: '#1F2937',
  },
  modalContainer: {
    flex: 1,
    backgroundColor: '#fff',
  },
  modalHeaderCountry: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: Platform.OS === 'ios' ? 50 : 20,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#E5E7EB',
  },
  modalTitleCountry: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1F2937',
  },
  clearText: {
    fontSize: 16,
    color: colors.primary,
    fontWeight: '500',
  },
  countryModalItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
  },
  countryModalItemSelected: {
    backgroundColor: colors.primaryLight,
  },
  countryModalFlag: {
    fontSize: 24,
    marginRight: 12,
  },
  countryModalName: {
    fontSize: 16,
    color: '#1F2937',
    flex: 1,
  },
  countryModalCode: {
    fontSize: 14,
    color: '#6B7280',
    marginRight: 8,
  },
  loadingText: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    marginTop: 32,
  },
  errorText: {
    fontSize: 16,
    color: '#EF4444',
    textAlign: 'center',
    marginTop: 32,
  },
  emptyText: {
    fontSize: 16,
    color: '#6B7280',
    textAlign: 'center',
    marginTop: 32,
  },
  checkboxChecked: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  clearFiltersButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
    alignItems: 'center',
    alignSelf: 'center',
    marginTop: 16,
  },
  clearFiltersText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '500',
  },
}); 