import React, { useState, useRef } from 'react';
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
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Feather';
import { MainStackParamList } from '../types/navigation';

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

const activeTrades = [
    {
      id: 't1',
      trader: {
        name: "Maria L.",
        verified: true,
      },
      amount: "100.00",
      crypto: "cUSD",
      totalBs: "3,610.00",
      step: 2,
      totalSteps: 4,
      timeRemaining: 754, // seconds
      status: "waiting_confirmation",
      paymentMethod: "Banco Venezuela",
    },
    {
      id: 't2',
      trader: {
        name: "Carlos F.",
        verified: true,
      },
      amount: "50.00",
      crypto: "cUSD",
      totalBs: "1,802.50",
      step: 3,
      totalSteps: 4,
      timeRemaining: 525, // seconds
      status: "verifying_payment",
      paymentMethod: "Pago Móvil",
    }
];

const paymentMethods = [
  'Todos los métodos',
  'Banco Venezuela',
  'Mercantil',
  'Banesco',
  'Pago Móvil',
  'Efectivo',
  'Zelle',
  'PayPal',
];

type Offer = typeof mockOffers.cUSD[0];
type ActiveTrade = typeof activeTrades[0];

export const ExchangeScreen = () => {
  const [activeTab, setActiveTab] = useState<'buy' | 'sell'>('buy');
  const [selectedCrypto, setSelectedCrypto] = useState<'cUSD' | 'CONFIO'>('cUSD');
  const [amount, setAmount] = useState('100.00');
  const [localAmount, setLocalAmount] = useState('3,600.00');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [headerVisible, setHeaderVisible] = useState(true);
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState('Todos los métodos');
  const scrollY = useRef(new Animated.Value(0)).current;
  const lastScrollY = useRef(0);
  const [headerHeight, setHeaderHeight] = useState(0);
  const [paymentModalVisible, setPaymentModalVisible] = useState(false);
  const [activeList, setActiveList] = useState<'offers' | 'trades'>('offers');
  const navigation = useNavigation<NativeStackNavigationProp<MainStackParamList>>();

  // Calculate local amount based on crypto amount and rate
  const calculateLocalAmount = (cryptoAmount: string, rate: string) => {
    const numAmount = parseFloat(cryptoAmount.replace(/,/g, ''));
    const numRate = parseFloat(rate);
    return (numAmount * numRate).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  // Calculate crypto amount based on local amount and rate
  const calculateCryptoAmount = (localAmount: string, rate: string) => {
    const numAmount = parseFloat(localAmount.replace(/,/g, ''));
    const numRate = parseFloat(rate);
    return (numAmount / numRate).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  // Handle amount changes
  const handleAmountChange = (value: string) => {
    setAmount(value);
    const rate = selectedCrypto === 'cUSD' ? '36.00' : '3.60';
    setLocalAmount(calculateLocalAmount(value, rate));
  };

  const handleLocalAmountChange = (value: string) => {
    setLocalAmount(value);
    const rate = selectedCrypto === 'cUSD' ? '36.00' : '3.60';
    setAmount(calculateCryptoAmount(value, rate));
  };

  // Handle scroll for header visibility
  const handleScroll = (event: any) => {
    const currentScrollY = event.nativeEvent.contentOffset.y;
    const scrollDifference = currentScrollY - lastScrollY.current;
    
    if (Math.abs(scrollDifference) > 10) {
      if (scrollDifference > 0 && currentScrollY > 100) {
        setHeaderVisible(false);
      } else if (scrollDifference < 0) {
        setHeaderVisible(true);
      }
      
      lastScrollY.current = currentScrollY;
    }
    
    scrollY.setValue(currentScrollY);
  };

  const onSelectPaymentMethod = (method: string) => {
    setSelectedPaymentMethod(method);
    setPaymentModalVisible(false);
  };

  const handleSelectOffer = (offer: Offer, action: 'profile' | 'trade') => {
    if (action === 'profile') {
      // Navigate to TraderProfile screen
      navigation.navigate('TraderProfile', { 
        offer: {
          id: offer.id.toString(),
          name: offer.name,
          rate: offer.rate + ' Bs.',
          limit: offer.limit,
          available: offer.available,
          paymentMethods: offer.paymentMethods,
          responseTime: offer.responseTime,
          completedTrades: offer.completedTrades,
          successRate: offer.successRate,
          verified: offer.verified,
          isOnline: offer.isOnline,
          lastSeen: offer.lastSeen,
        }, 
        crypto: selectedCrypto 
      });
    } else if (action === 'trade') {
      // Navigate to TradeConfirm screen
      navigation.navigate('TradeConfirm', { 
        offer: {
          id: offer.id.toString(),
          name: offer.name,
          rate: offer.rate + ' Bs.',
          limit: offer.limit,
          available: offer.available,
          paymentMethods: offer.paymentMethods,
          responseTime: offer.responseTime,
          completedTrades: offer.completedTrades,
          successRate: offer.successRate,
          verified: offer.verified,
          isOnline: offer.isOnline,
          lastSeen: offer.lastSeen,
        }, 
        crypto: selectedCrypto 
      });
    }
  };

  // Enhanced Offer Card Component
  const OfferCard = ({ offer, crypto }: { offer: Offer, crypto: 'cUSD' | 'CONFIO' }) => (
    <View style={styles.offerCard}>
      <View style={styles.offerHeader}>
        <View style={styles.offerUser}>
          <View style={styles.avatarContainer}>
            <Text style={styles.avatarText}>{offer.name.charAt(0)}</Text>
            {offer.isOnline && <View style={styles.onlineIndicator} />}
          </View>
          <View>
            <View style={styles.userNameContainer}>
              <Text style={styles.userName}>{offer.name}</Text>
              {offer.verified && (
                <Icon name="shield" size={16} color={colors.accent} style={styles.verifiedIcon} />
              )}
            </View>
            <View style={styles.userStats}>
              <Text style={styles.tradeCount}>{offer.completedTrades} operaciones</Text>
              <Text style={styles.bullet}>•</Text>
              <Text style={styles.successRate}>{offer.successRate}%</Text>
            </View>
          </View>
        </View>
        <View style={styles.offerRateContainer}>
          <Text style={styles.rateValue}>{offer.rate} Bs.</Text>
          <View style={styles.responseTime}>
            <Icon name="clock" size={12} color="#6B7280" />
            <Text style={styles.responseTimeText}>Resp: {offer.responseTime}</Text>
          </View>
        </View>
      </View>

      <View style={styles.offerDetails}>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Límite por operación</Text>
          <Text style={styles.detailValue}>{offer.limit} {crypto}</Text>
        </View>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Métodos de pago</Text>
          <Text style={styles.detailValue}>{offer.paymentMethods.join(', ')}</Text>
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
                        <Text style={styles.tradeDetails}>{trade.amount} {trade.crypto} por {trade.totalBs} Bs.</Text>
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
            <TouchableOpacity style={styles.continueButton}>
                <Text style={styles.continueButtonText}>Continuar</Text>
            </TouchableOpacity>
        </View>
    );
  };

  // Header component
  const Header = () => {
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
                    onPress={() => setActiveList('trades')}
                >
                    <Icon name="alert-triangle" size={16} color={colors.primary} />
                    <Text style={styles.activeTradesText}>
                        {activeTrades.length} intercambio{activeTrades.length > 1 ? 's' : ''} activo{activeTrades.length > 1 ? 's' : ''}
                    </Text>
                    <Icon name="chevron-right" size={16} color={colors.primary} />
                </TouchableOpacity>
            )}

            <View style={styles.mainTabsContainer}>
                <TouchableOpacity
                    style={[styles.mainTab, activeList === 'offers' && styles.activeMainTab]}
                    onPress={() => setActiveList('offers')}
                >
                    <Text style={[styles.mainTabText, activeList === 'offers' && styles.activeMainTabText]}>
                        Ofertas
                    </Text>
                </TouchableOpacity>
                <TouchableOpacity
                    style={[styles.mainTab, activeList === 'trades' && styles.activeMainTab]}
                    onPress={() => setActiveList('trades')}
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
                            onPress={() => setActiveTab('buy')}
                        >
                            <Text style={[styles.tabText, activeTab === 'buy' && styles.activeTabText]}>Comprar</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={[styles.tab, activeTab === 'sell' && styles.activeTab]}
                            onPress={() => setActiveTab('sell')}
                        >
                            <Text style={[styles.tabText, activeTab === 'sell' && styles.activeTabText]}>Vender</Text>
                        </TouchableOpacity>
                    </View>

                    {/* Crypto Selection */}
                    <View style={styles.cryptoSelector}>
                        <TouchableOpacity
                            style={[styles.cryptoButton, selectedCrypto === 'cUSD' && styles.selectedCryptoButton]}
                            onPress={() => setSelectedCrypto('cUSD')}
                        >
                            <Text style={[styles.cryptoButtonText, selectedCrypto === 'cUSD' && styles.selectedCryptoButtonText]}>
                                Confío Dollar ($cUSD)
                            </Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={[styles.cryptoButton, selectedCrypto === 'CONFIO' && styles.selectedCryptoButton]}
                            onPress={() => setSelectedCrypto('CONFIO')}
                        >
                            <Text style={[styles.cryptoButtonText, selectedCrypto === 'CONFIO' && styles.selectedCryptoButtonText]}>
                                Confío ($CONFIO)
                            </Text>
                        </TouchableOpacity>
                    </View>

                    {/* Amount, Payment Method, and Search */}
                    <View style={styles.searchContainer}>
                        <View style={styles.amountInputContainer}>
                            <TextInput
                                style={styles.amountInput}
                                value={amount}
                                onChangeText={handleAmountChange}
                                placeholder="Cantidad"
                                keyboardType="decimal-pad"
                            />
                            <Text style={styles.currencyLabel}>{selectedCrypto}</Text>
                        </View>

                        <View style={styles.paymentMethodContainer}>
                            <TouchableOpacity
                                style={styles.paymentMethodInput}
                                onPress={() => setPaymentModalVisible(true)}
                            >
                                <Text style={styles.paymentMethodInputText} numberOfLines={1}>
                                    {selectedPaymentMethod}
                                </Text>
                            </TouchableOpacity>
                        </View>

                        <TouchableOpacity style={styles.searchButton}>
                            <Icon name="search" size={16} color="#fff" />
                        </TouchableOpacity>
                    </View>

                    {/* Rate and Filter Controls */}
                    <View style={styles.rateFilterContainer}>
                        <Text style={styles.averageRate}>
                            {selectedCrypto === 'cUSD' ? '36.00' : '3.60'} Bs. promedio
                        </Text>
                        <View style={styles.filterControls}>
                            <TouchableOpacity
                                style={[styles.filterButton, showAdvancedFilters && styles.activeFilterButton]}
                                onPress={() => setShowAdvancedFilters(!showAdvancedFilters)}
                            >
                                <Icon
                                    name="filter"
                                    size={12}
                                    color={showAdvancedFilters ? colors.primary : '#6B7280'}
                                />
                            </TouchableOpacity>
                            <TouchableOpacity style={styles.refreshButton}>
                                <Icon name="refresh-cw" size={12} color="#6B7280" />
                            </TouchableOpacity>
                        </View>
                    </View>

                    {/* Advanced Filters */}
                    {showAdvancedFilters && (
                        <View style={styles.advancedFilters}>
                            <View style={styles.filterInputs}>
                                <TextInput
                                    style={styles.filterInput}
                                    placeholder="Tasa min."
                                    keyboardType="decimal-pad"
                                />
                                <TextInput
                                    style={styles.filterInput}
                                    placeholder="Tasa max."
                                    keyboardType="decimal-pad"
                                />
                            </View>

                            <View style={styles.filterCheckboxes}>
                                <TouchableOpacity style={styles.checkboxItem}>
                                    <View style={styles.checkbox} />
                                    <Text style={styles.checkboxLabel}>Verificados</Text>
                                </TouchableOpacity>
                                <TouchableOpacity style={styles.checkboxItem}>
                                    <View style={styles.checkbox} />
                                    <Text style={styles.checkboxLabel}>En línea</Text>
                                </TouchableOpacity>
                                <TouchableOpacity style={styles.checkboxItem}>
                                    <View style={styles.checkbox} />
                                    <Text style={styles.checkboxLabel}>+100 ops</Text>
                                </TouchableOpacity>
                            </View>

                            <View style={styles.filterActions}>
                                <TouchableOpacity style={styles.applyButton}>
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
                    )}
                </>
            )}
        </Animated.View>
    );
  };

  const renderContent = () => {
    if (activeList === 'offers') {
      return (
        <View style={[styles.offersList, { padding: 16 }]}>
          {mockOffers[selectedCrypto].map((offer) => (
            <OfferCard key={offer.id} offer={offer} crypto={selectedCrypto} />
          ))}
        </View>
      );
    }
    
    if (activeList === 'trades') {
      return (
        <View style={[styles.offersList, { padding: 16 }]}>
          {activeTrades.map((trade) => (
            <ActiveTradeCard key={trade.id} trade={trade} />
          ))}
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
    marginBottom: 16,
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
    marginBottom: 16,
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
    marginBottom: 16,
    gap: 8,
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
  },
  activeFilterButton: {
    backgroundColor: colors.primaryLight,
  },
  refreshButton: {
    padding: 6,
    backgroundColor: colors.neutralDark,
    borderRadius: 8,
  },
  advancedFilters: {
    marginTop: 12,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: '#E5E7EB',
    backgroundColor: colors.neutral,
    borderRadius: 8,
    padding: 12,
  },
  filterInputs: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 12,
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
    marginBottom: 12,
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
    alignItems: 'center',
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
  userStats: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
  },
  tradeCount: {
    fontSize: 12,
    color: '#6B7280',
  },
  bullet: {
    fontSize: 12,
    color: '#6B7280',
    marginHorizontal: 4,
  },
  successRate: {
    fontSize: 12,
    color: '#10B981',
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
    marginBottom: 4,
  },
  detailLabel: {
    fontSize: 12,
    color: '#6B7280',
  },
  detailValue: {
    fontSize: 12,
    fontWeight: '500',
    color: '#1F2937',
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
}); 