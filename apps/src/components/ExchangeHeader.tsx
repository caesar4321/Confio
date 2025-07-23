import React, { useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Animated,
  Platform,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';

interface ExchangeHeaderProps {
  // Navigation props
  activeList: 'offers' | 'trades' | 'myOffers';
  onActiveListChange: (list: 'offers' | 'trades' | 'myOffers') => void;
  
  // Offer-specific props
  activeTab?: 'buy' | 'sell';
  onActiveTabChange?: (tab: 'buy' | 'sell') => void;
  selectedCrypto?: 'cUSD' | 'CONFIO';
  onCryptoChange?: (crypto: 'cUSD' | 'CONFIO') => void;
  showAdvancedFilters?: boolean;
  onToggleFilters?: () => void;
  
  // Data props
  activeTrades: any[];
  myOffersCount?: number;
  
  // Scroll props
  scrollY: Animated.Value;
  
  // Children for dynamic content
  children?: React.ReactNode;
}

// Track header renders
let headerRenderCount = 0;

export const ExchangeHeader = React.memo<ExchangeHeaderProps>(({
  activeList,
  onActiveListChange,
  activeTab = 'buy',
  onActiveTabChange,
  selectedCrypto = 'cUSD',
  onCryptoChange,
  showAdvancedFilters = false,
  onToggleFilters,
  activeTrades,
  myOffersCount = 0,
  scrollY,
  children,
}) => {
  headerRenderCount++;
  console.log('[DEBUG] ExchangeHeader render #', headerRenderCount, {
    activeList,
    activeTab,
    selectedCrypto,
    showAdvancedFilters,
    activeTradesLength: activeTrades.length,
  });

  // Fixed header heights
  const HEADER_HEIGHT = activeList === 'offers' ? 320 : 100;
  
  // Animated values
  const scrollYClamped = Animated.diffClamp(scrollY, 0, HEADER_HEIGHT);
  const headerTranslateY = scrollYClamped.interpolate({
    inputRange: [0, HEADER_HEIGHT],
    outputRange: [0, -HEADER_HEIGHT],
    extrapolate: 'clamp',
  });

  return (
    <Animated.View
      style={[
        styles.header,
        {
          transform: [{ translateY: headerTranslateY }],
        },
      ]}
    >
      {/* Active trades alert */}
      {activeTrades.length > 0 && (
        <TouchableOpacity
          style={styles.activeTradesAlert}
          onPress={() => onActiveListChange('trades')}
        >
          <Icon name="alert-triangle" size={16} color="#34d399" />
          <Text style={styles.activeTradesText}>
            {activeTrades.length} intercambio{activeTrades.length > 1 ? 's' : ''} activo{activeTrades.length > 1 ? 's' : ''} - Toca para continuar
          </Text>
          <Icon name="chevron-right" size={16} color="#34d399" />
        </TouchableOpacity>
      )}

      {/* Main tabs */}
      <View style={styles.mainTabsContainer}>
        <TouchableOpacity
          style={[styles.mainTab, activeList === 'offers' && styles.activeMainTab]}
          onPress={() => onActiveListChange('offers')}
        >
          <Text style={[styles.mainTabText, activeList === 'offers' && styles.activeMainTabText]}>
            Ofertas
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.mainTab, activeList === 'myOffers' && styles.activeMainTab]}
          onPress={() => onActiveListChange('myOffers')}
        >
          <Text style={[styles.mainTabText, activeList === 'myOffers' && styles.activeMainTabText]}>
            Mis Ofertas
          </Text>
          {myOffersCount > 0 && (
            <View style={styles.notificationBadge}>
              <Text style={styles.notificationText}>{myOffersCount}</Text>
            </View>
          )}
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.mainTab, activeList === 'trades' && styles.activeMainTab]}
          onPress={() => onActiveListChange('trades')}
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

      {/* Offers-specific content */}
      {activeList === 'offers' && (
        <>
          {/* Buy/Sell Toggle */}
          <View style={styles.tabContainer}>
            <TouchableOpacity
              style={[styles.tab, activeTab === 'buy' && styles.activeTab]}
              onPress={() => onActiveTabChange?.('buy')}
            >
              <Text style={[styles.tabText, activeTab === 'buy' && styles.activeTabText]}>
                Comprar
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tab, activeTab === 'sell' && styles.activeTab]}
              onPress={() => onActiveTabChange?.('sell')}
            >
              <Text style={[styles.tabText, activeTab === 'sell' && styles.activeTabText]}>
                Vender
              </Text>
            </TouchableOpacity>
          </View>

          {/* Crypto Selection */}
          <View style={styles.cryptoSelector}>
            <TouchableOpacity
              style={[styles.cryptoButton, selectedCrypto === 'cUSD' && styles.selectedCryptoButton]}
              onPress={() => onCryptoChange?.('cUSD')}
            >
              <Text style={[styles.cryptoButtonText, selectedCrypto === 'cUSD' && styles.selectedCryptoButtonText]}>
                Confío Dollar ($cUSD)
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.cryptoButton, selectedCrypto === 'CONFIO' && styles.selectedCryptoButton]}
              onPress={() => onCryptoChange?.('CONFIO')}
            >
              <Text style={[styles.cryptoButtonText, selectedCrypto === 'CONFIO' && styles.selectedCryptoButtonText]}>
                Confío ($CONFIO)
              </Text>
            </TouchableOpacity>
          </View>

          {/* Dynamic content (search, filters, etc.) */}
          {children}
        </>
      )}
    </Animated.View>
  );
});

const styles = StyleSheet.create({
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
  activeTradesAlert: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#d1fae5',
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
  },
  activeTradesText: {
    flex: 1,
    fontSize: 14,
    fontWeight: '500',
    color: '#065f46',
    marginHorizontal: 8,
  },
  mainTabsContainer: {
    flexDirection: 'row',
    marginBottom: 12,
    backgroundColor: '#f3f4f6',
    borderRadius: 12,
    padding: 4,
  },
  mainTab: {
    flex: 1,
    paddingVertical: 10,
    alignItems: 'center',
    borderRadius: 8,
    position: 'relative',
  },
  activeMainTab: {
    backgroundColor: '#fff',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
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
    top: 4,
    right: 4,
    backgroundColor: '#ef4444',
    borderRadius: 10,
    minWidth: 20,
    height: 20,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 6,
  },
  notificationText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  tabContainer: {
    flexDirection: 'row',
    backgroundColor: '#f3f4f6',
    borderRadius: 12,
    marginBottom: 12,
  },
  tab: {
    flex: 1,
    paddingVertical: 12,
    alignItems: 'center',
  },
  activeTab: {
    backgroundColor: '#34d399',
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
    backgroundColor: '#f3f4f6',
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
    backgroundColor: '#34d399',
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
});