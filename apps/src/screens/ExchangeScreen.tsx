import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, ScrollView, Platform } from 'react-native';
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

// Mock data for offers
const mockOffers = {
  cUSD: [
    { name: "Maria L.", completedTrades: 248, rate: "36.10", available: "1,500.00", limit: "100.00 - 1,500.00" },
    { name: "Carlos F.", completedTrades: 124, rate: "36.05", available: "800.00", limit: "50.00 - 800.00" },
    { name: "Ana P.", completedTrades: 310, rate: "36.00", available: "950.00", limit: "100.00 - 950.00" },
    { name: "Pedro M.", completedTrades: 178, rate: "35.95", available: "2,300.00", limit: "200.00 - 2,300.00" },
  ],
  CONFIO: [
    { name: "Juan V.", completedTrades: 89, rate: "3.65", available: "2,000.00", limit: "100.00 - 2,000.00" },
    { name: "Laura M.", completedTrades: 356, rate: "3.63", available: "1,200.00", limit: "50.00 - 1,200.00" },
    { name: "Roberto S.", completedTrades: 112, rate: "3.60", available: "3,500.00", limit: "100.00 - 3,500.00" },
    { name: "Carla D.", completedTrades: 201, rate: "3.58", available: "1,800.00", limit: "200.00 - 1,800.00" },
  ],
};

export const ExchangeScreen = () => {
  const [activeTab, setActiveTab] = useState<'buy' | 'sell'>('buy');
  const [selectedCrypto, setSelectedCrypto] = useState<'cUSD' | 'CONFIO'>('cUSD');
  const [amount, setAmount] = useState('100.00');
  const [localAmount, setLocalAmount] = useState('3,600.00');

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

  // Offer Card Component
  const OfferCard = ({ offer, crypto }: { offer: typeof mockOffers.cUSD[0], crypto: 'cUSD' | 'CONFIO' }) => (
    <View style={styles.offerCard}>
      <View style={styles.offerHeader}>
        <View style={styles.offerUser}>
          <View style={styles.avatarContainer}>
            <Text style={styles.avatarText}>{offer.name.charAt(0)}</Text>
          </View>
          <View>
            <Text style={styles.userName}>{offer.name}</Text>
            <Text style={styles.tradeCount}>{offer.completedTrades} operaciones</Text>
          </View>
        </View>
        <View style={styles.offerRateContainer}>
          <Text style={styles.rateValue}>{offer.rate} Bs.</Text>
          <Text style={styles.rateLabel}>Tasa</Text>
        </View>
      </View>

      <View style={styles.offerDetails}>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Disponible</Text>
          <Text style={styles.detailValue}>{offer.available} {crypto}</Text>
        </View>
        <View style={styles.detailRow}>
          <Text style={styles.detailLabel}>Límite</Text>
          <Text style={styles.detailValue}>{offer.limit} {crypto}</Text>
        </View>
      </View>

      <View style={styles.offerActions}>
        <TouchableOpacity style={styles.detailsButton}>
          <Text style={styles.detailsButtonText}>Detalles</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.buyButton}>
          <Text style={styles.buyButtonText}>Comprar</Text>
        </TouchableOpacity>
      </View>
    </View>
  );

  return (
    <View style={styles.container}>
      <ScrollView style={styles.content} contentContainerStyle={styles.contentContainer}>
        {/* Buy/Sell Tabs */}
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

        {/* Crypto Selection and Amount Input */}
        <View style={styles.inputContainer}>
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

          <View style={styles.amountInputs}>
            <View style={styles.inputGroup}>
              <Text style={styles.inputLabel}>Quiero comprar</Text>
              <View style={styles.amountInputContainer}>
                <TextInput
                  style={styles.amountInput}
                  value={amount}
                  onChangeText={handleAmountChange}
                  keyboardType="decimal-pad"
                />
                <Text style={styles.currencyLabel}>{selectedCrypto}</Text>
              </View>
            </View>

            <View style={styles.inputGroup}>
              <Text style={styles.inputLabel}>Pagaré</Text>
              <View style={styles.amountInputContainer}>
                <TextInput
                  style={styles.amountInput}
                  value={localAmount}
                  onChangeText={handleLocalAmountChange}
                  keyboardType="decimal-pad"
                />
                <Text style={styles.currencyLabel}>Bs.</Text>
              </View>
            </View>
          </View>
        </View>

        {/* Rate and Filter */}
        <View style={styles.rateContainer}>
          <Text style={styles.rateText}>
            Tasa: 1 {selectedCrypto} = {selectedCrypto === 'cUSD' ? '36.00' : '3.60'} Bs.
          </Text>
          <TouchableOpacity style={styles.filterButton}>
            <Icon name="filter" size={20} color="#6B7280" />
          </TouchableOpacity>
        </View>

        {/* Offers List */}
        <View style={styles.offersList}>
          {mockOffers[selectedCrypto].map((offer, index) => (
            <OfferCard key={index} offer={offer} crypto={selectedCrypto} />
          ))}
        </View>
      </ScrollView>
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
  inputContainer: {
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  cryptoSelector: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  cryptoButton: {
    flex: 1,
    paddingVertical: 8,
    paddingHorizontal: 12,
    alignItems: 'center',
  },
  selectedCryptoButton: {
    backgroundColor: '#fff',
    borderRadius: 8,
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
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
  },
  selectedCryptoButtonText: {
    color: '#1F2937',
  },
  amountInputs: {
    flexDirection: 'row',
    gap: 8,
  },
  inputGroup: {
    flex: 1,
  },
  inputLabel: {
    fontSize: 12,
    color: '#6B7280',
    marginBottom: 4,
  },
  amountInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fff',
    borderRadius: 8,
    padding: 8,
  },
  amountInput: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
  },
  currencyLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#6B7280',
  },
  rateContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  rateText: {
    fontSize: 12,
    color: '#6B7280',
  },
  filterButton: {
    padding: 4,
    backgroundColor: colors.neutralDark,
    borderRadius: 8,
  },
  offersList: {
    gap: 12,
  },
  offerCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#E5E7EB',
  },
  offerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  offerUser: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  avatarContainer: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  avatarText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#4B5563',
  },
  userName: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1F2937',
  },
  tradeCount: {
    fontSize: 12,
    color: '#6B7280',
  },
  offerRateContainer: {
    alignItems: 'flex-end',
  },
  rateValue: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1F2937',
  },
  rateLabel: {
    fontSize: 12,
    color: '#6B7280',
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
    paddingVertical: 6,
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
    paddingVertical: 6,
    borderRadius: 8,
    alignItems: 'center',
  },
  buyButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#fff',
  },
}); 