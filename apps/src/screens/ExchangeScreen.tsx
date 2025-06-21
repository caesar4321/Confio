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
import Icon from 'react-native-vector-icons/Feather';

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
    }
  ],
};

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

  // Enhanced Offer Card Component
  const OfferCard = ({ offer, crypto }: { offer: typeof mockOffers.cUSD[0], crypto: 'cUSD' | 'CONFIO' }) => (
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
        <TouchableOpacity style={styles.detailsButton}>
          <Text style={styles.detailsButtonText}>Ver Perfil</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.buyButton}>
          <Text style={styles.buyButtonText}>{activeTab === 'buy' ? 'Comprar' : 'Vender'}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

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
        </Animated.View>
    );
  }

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
        contentContainerStyle={{ paddingTop: headerHeight }}
        onScroll={Animated.event(
            [{ nativeEvent: { contentOffset: { y: scrollY } } }],
            { useNativeDriver: true }
        )}
        scrollEventThrottle={16}
        bounces={false}
      >
        <View style={[styles.offersList, { padding: 16 }]}>
          {mockOffers[selectedCrypto].map((offer) => (
            <OfferCard key={offer.id} offer={offer} crypto={selectedCrypto} />
          ))}
        </View>
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
}); 