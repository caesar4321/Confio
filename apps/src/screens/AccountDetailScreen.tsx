import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  TextInput,
  Modal,
  Platform,
  Image,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useRoute } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { MainStackParamList } from '../types/navigation';
import { Header } from '../navigation/Header';
import cUSDLogo from '../assets/png/cUSD.png';
import CONFIOLogo from '../assets/png/CONFIO.png';
import USDCLogo from '../assets/png/USDC.png';

// Color palette
const colors = {
  primary: '#34D399', // emerald-400
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
  text: {
    primary: '#1F2937', // gray-800
    secondary: '#6B7280', // gray-500
  },
};

type AccountDetailScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;
type AccountDetailScreenRouteProp = RouteProp<MainStackParamList, 'AccountDetail'>;

interface Transaction {
  type: 'received' | 'sent' | 'exchange' | 'payment';
  from?: string;
  to?: string;
  amount: string;
  currency: string;
  date: string;
  time: string;
  status: string;
  hash: string;
}

export const AccountDetailScreen = () => {
  const navigation = useNavigation<AccountDetailScreenNavigationProp>();
  const route = useRoute<AccountDetailScreenRouteProp>();
  const [showBalance, setShowBalance] = useState(true);
  const [showExchangeModal, setShowExchangeModal] = useState(false);
  const [exchangeAmount, setExchangeAmount] = useState('');

  // Account data from navigation params
  const account = {
    name: route.params.accountName,
    symbol: route.params.accountSymbol,
    balance: route.params.accountBalance,
    balanceHidden: "•••••••",
    color: route.params.accountType === 'cusd' ? colors.primary : colors.secondary,
    textColor: route.params.accountType === 'cusd' ? colors.primaryText : colors.secondaryText,
    address: "0x1234...5678",
    exchangeRate: "1 USDC = 1.00 cUSD",
    description: route.params.accountType === 'cusd' 
      ? "Moneda estable respaldada por dólares americanos"
      : "Token de gobernanza de Confío"
  };

  // USDC balance data (shown only for cUSD account)
  const usdcAccount = route.params.accountType === 'cusd' ? {
    name: "USD Coin",
    symbol: "USDC",
    balance: "458.22",
    balanceHidden: "•••••••",
    description: "Para usuarios avanzados - depósito directo vía Sui Blockchain"
  } : null;

  // Mock transaction data
  const transactions: Transaction[] = [
    {
      type: 'received' as const,
      from: 'María González',
      amount: '+125.50',
      currency: route.params.accountType === 'cusd' ? 'cUSD' : 'CONFIO',
      date: '2025-06-10',
      time: '14:30',
      status: 'completed',
      hash: '0xabc123...'
    },
    {
      type: 'sent' as const,
      to: 'Carlos Pérez',
      amount: '-89.25',
      currency: route.params.accountType === 'cusd' ? 'cUSD' : 'CONFIO',
      date: '2025-06-09',
      time: '16:45',
      status: 'completed',
      hash: '0xdef456...'
    },
    {
      type: 'exchange' as const,
      from: route.params.accountType === 'cusd' ? 'USDC' : 'cUSD',
      to: route.params.accountType === 'cusd' ? 'cUSD' : 'CONFIO',
      amount: route.params.accountType === 'cusd' ? '+500.00' : '+1000.00',
      currency: route.params.accountType === 'cusd' ? 'cUSD' : 'CONFIO',
      date: '2025-06-08',
      time: '10:15',
      status: 'completed',
      hash: '0xghi789...'
    },
    {
      type: 'payment' as const,
      to: 'Supermercado Central',
      amount: '-32.75',
      currency: route.params.accountType === 'cusd' ? 'cUSD' : 'CONFIO',
      date: '2025-06-07',
      time: '18:45',
      status: 'completed',
      hash: '0xjkl012...'
    }
  ];

  const getTransactionTitle = (transaction: Transaction) => {
    switch(transaction.type) {
      case 'received':
        return `Recibido de ${transaction.from}`;
      case 'sent':
        return `Enviado a ${transaction.to}`;
      case 'exchange':
        return `Intercambio ${transaction.from} → ${transaction.to}`;
      case 'payment':
        return `Pago a ${transaction.to}`;
      default:
        return 'Transacción';
    }
  };

  const getTransactionIcon = (transaction: Transaction) => {
    switch(transaction.type) {
      case 'received':
        return <Icon name="arrow-down" size={20} color="#10B981" />;
      case 'sent':
        return <Icon name="arrow-up" size={20} color="#EF4444" />;
      case 'exchange':
        return <Icon name="refresh-cw" size={20} color="#3B82F6" />;
      case 'payment':
        return <Icon name="shopping-bag" size={20} color="#8B5CF6" />;
      default:
        return <Icon name="arrow-up" size={20} color="#6B7280" />;
    }
  };

  const TransactionItem = ({ transaction }: { transaction: Transaction }) => {
    return (
      <View style={styles.transactionItem}>
        <View style={styles.transactionIconContainer}>
          {getTransactionIcon(transaction)}
        </View>
        <View style={styles.transactionInfo}>
          <Text style={styles.transactionTitle}>{getTransactionTitle(transaction)}</Text>
          <Text style={styles.transactionDate}>{transaction.date} • {transaction.time}</Text>
        </View>
        <View style={styles.transactionAmount}>
          <Text style={[
            styles.transactionAmountText,
            (transaction.type === 'sent' || transaction.type === 'payment') ? styles.negativeAmount : styles.positiveAmount
          ]}>
            {transaction.amount} {transaction.currency}
          </Text>
          <View style={styles.transactionStatus}>
            <Text style={styles.statusText}>Completado</Text>
            <View style={styles.statusDot} />
          </View>
        </View>
      </View>
    );
  };

  const ExchangeModal = () => (
    <Modal
      visible={showExchangeModal}
      transparent
      animationType="fade"
      onRequestClose={() => setShowExchangeModal(false)}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Intercambiar USDC</Text>
            <TouchableOpacity onPress={() => setShowExchangeModal(false)}>
              <Icon name="arrow-left" size={24} color="#6b7280" />
            </TouchableOpacity>
          </View>

          <View style={styles.exchangeContainer}>
            <View style={styles.exchangeInputContainer}>
              <View style={styles.exchangeInputHeader}>
                <Text style={styles.exchangeInputLabel}>Desde</Text>
                <Text style={styles.exchangeInputLabel}>Disponible: {usdcAccount?.balance} USDC</Text>
              </View>
              <View style={styles.exchangeInput}>
                <TextInput
                  value={exchangeAmount}
                  onChangeText={setExchangeAmount}
                  placeholder="0.00"
                  keyboardType="decimal-pad"
                  style={styles.exchangeInputText}
                />
                <View style={styles.currencyBadge}>
                  <View style={[styles.currencyIcon, { backgroundColor: colors.accent }]}>
                    <Text style={styles.currencyIconText}>U</Text>
                  </View>
                  <Text style={styles.currencyText}>USDC</Text>
                </View>
              </View>
            </View>

            <View style={styles.exchangeArrow}>
              <Icon name="arrow-down" size={20} color="#6b7280" />
            </View>

            <View style={styles.exchangeInputContainer}>
              <View style={styles.exchangeInputHeader}>
                <Text style={styles.exchangeInputLabel}>A</Text>
                <Text style={styles.exchangeInputLabel}>Tasa: 1 USDC = 1.00 cUSD</Text>
              </View>
              <View style={styles.exchangeInput}>
                <Text style={styles.exchangeInputText}>
                  {exchangeAmount || '0.00'}
                </Text>
                <View style={styles.currencyBadge}>
                  <View style={[styles.currencyIcon, { backgroundColor: colors.primary }]}>
                    <Text style={styles.currencyIconText}>C</Text>
                  </View>
                  <Text style={styles.currencyText}>cUSD</Text>
                </View>
              </View>
            </View>
          </View>

          <View style={styles.feeContainer}>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de red</Text>
              <Text style={styles.feeValue}>$0.02</Text>
            </View>
            <View style={styles.feeRow}>
              <Text style={styles.feeLabel}>Comisión de plataforma</Text>
              <Text style={styles.feeValue}>Gratis</Text>
            </View>
            <View style={styles.feeDivider} />
            <View style={styles.feeRow}>
              <Text style={styles.feeTotalLabel}>Total a recibir</Text>
              <Text style={styles.feeTotalValue}>
                {exchangeAmount ? (parseFloat(exchangeAmount) - 0.02).toFixed(2) : '0.00'} cUSD
              </Text>
            </View>
          </View>

          <TouchableOpacity
            style={[
              styles.exchangeButton,
              !exchangeAmount && styles.exchangeButtonDisabled
            ]}
            disabled={!exchangeAmount}
          >
            <Text style={styles.exchangeButtonText}>Confirmar Intercambio</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );

  return (
    <View style={styles.container}>
      <Header
        navigation={navigation}
        title={account.name}
        backgroundColor={account.color}
        isLight={true}
        showBackButton={true}
      />

      <ScrollView style={styles.scrollView}>
        {/* Balance Section */}
        <View style={[styles.balanceSection, { backgroundColor: account.color }]}>
          <View style={styles.balanceIconContainer}>
            <Image 
              source={route.params.accountType === 'cusd' ? cUSDLogo : CONFIOLogo} 
              style={styles.balanceLogo} 
            />
          </View>

          <View style={styles.balanceRow}>
            <Text style={styles.balanceText}>
              {showBalance ? `$${account.balance}` : account.balanceHidden}
            </Text>
            <TouchableOpacity onPress={() => setShowBalance(!showBalance)}>
              <Icon
                name={showBalance ? 'eye' : 'eye-off'}
                size={20}
                color="#ffffff"
                style={styles.eyeIcon}
              />
            </TouchableOpacity>
          </View>

          <Text style={styles.balanceDescription}>{account.description}</Text>
          <View style={styles.addressContainer}>
            <Text style={styles.addressText}>{account.address}</Text>
            <TouchableOpacity>
              <Icon name="copy" size={16} color="#ffffff" style={styles.copyIcon} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Action Buttons */}
        <View style={styles.actionButtonsContainer}>
          <View style={styles.actionButtons}>
            <TouchableOpacity style={styles.actionButton}>
              <View style={[styles.actionIcon, { backgroundColor: colors.primary }]}>
                <Icon name="send" size={20} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Enviar</Text>
            </TouchableOpacity>

            <TouchableOpacity 
              style={styles.actionButton}
              onPress={() => navigation.navigate('USDCDeposit', { 
                tokenType: route.params.accountType === 'cusd' ? 'cusd' : 'confio' 
              })}
            >
              <View style={[styles.actionIcon, { backgroundColor: colors.primary }]}>
                <Icon name="download" size={20} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Recibir</Text>
            </TouchableOpacity>

            <TouchableOpacity style={styles.actionButton}>
              <View style={[styles.actionIcon, { backgroundColor: colors.secondary }]}>
                <Icon name="shopping-bag" size={20} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Pagar</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.actionButton}
              onPress={() => setShowExchangeModal(true)}
            >
              <View style={[styles.actionIcon, { backgroundColor: colors.accent }]}>
                <Icon name="refresh-cw" size={20} color="#ffffff" />
              </View>
              <Text style={styles.actionButtonText}>Intercambio</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* USDC Balance Section - Only show for cUSD account */}
        {route.params.accountType === 'cusd' && usdcAccount && (
          <View style={styles.usdcSection}>
            <View style={styles.usdcCard}>
              <View style={styles.usdcHeader}>
                <View style={styles.usdcInfo}>
                  <Image source={USDCLogo} style={styles.usdcLogo} />
                  <View style={styles.usdcTextContainer}>
                    <Text style={styles.usdcName}>{usdcAccount.name}</Text>
                    <Text style={styles.usdcDescription} numberOfLines={2}>
                      {usdcAccount.description}
                    </Text>
                  </View>
                </View>
                <View style={styles.usdcBalance}>
                  <Text style={styles.usdcBalanceText}>
                    {showBalance ? usdcAccount.balance : usdcAccount.balanceHidden}
                  </Text>
                  <Text style={styles.usdcSymbol}>{usdcAccount.symbol}</Text>
                </View>
              </View>

              <View style={styles.usdcActions}>
                <TouchableOpacity 
                  style={styles.usdcActionButton}
                  onPress={() => navigation.navigate('USDCDeposit', { tokenType: 'usdc' })}
                >
                  <Text style={styles.usdcActionButtonText}>Depositar USDC</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.usdcActionButton, { backgroundColor: colors.accent }]}
                  onPress={() => navigation.navigate('USDCManage')}
                >
                  <Text style={[styles.usdcActionButtonText, { color: '#ffffff' }]}>
                    Gestionar
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        )}

        {/* Transactions Section */}
        <View style={styles.transactionsSection}>
          <View style={styles.transactionsHeader}>
            <Text style={styles.transactionsTitle}>Historial de transacciones</Text>
            <View style={styles.transactionsFilters}>
              <TouchableOpacity style={styles.filterButton}>
                <Icon name="filter" size={16} color="#6b7280" />
              </TouchableOpacity>
              <TouchableOpacity style={styles.filterButton}>
                <Icon name="calendar" size={16} color="#6b7280" />
              </TouchableOpacity>
            </View>
          </View>

          <View style={styles.transactionsList}>
            {transactions.map((transaction, index) => (
              <TransactionItem key={index} transaction={transaction} />
            ))}
          </View>

          <TouchableOpacity style={styles.viewAllButton}>
            <Text style={[styles.viewAllButtonText, { color: account.color }]}>
              Ver todas las transacciones
            </Text>
          </TouchableOpacity>
        </View>
      </ScrollView>

      <ExchangeModal />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.neutralDark,
  },
  scrollView: {
    flex: 1,
  },
  balanceSection: {
    paddingTop: 12,
    paddingBottom: 32,
    paddingHorizontal: 20,
    alignItems: 'center',
  },
  balanceIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: '#ffffff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    padding: 8,
  },
  balanceLogo: {
    width: '100%',
    height: '100%',
    resizeMode: 'contain',
  },
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  balanceText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#ffffff',
    marginRight: 8,
  },
  eyeIcon: {
    opacity: 0.8,
  },
  balanceDescription: {
    fontSize: 14,
    color: '#ffffff',
    opacity: 0.8,
    marginBottom: 4,
  },
  addressContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  addressText: {
    fontSize: 12,
    color: '#ffffff',
    opacity: 0.7,
    marginRight: 4,
  },
  copyIcon: {
    opacity: 0.8,
  },
  actionButtonsContainer: {
    marginTop: -16,
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  actionButtons: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
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
  actionButton: {
    alignItems: 'center',
    flex: 1,
    paddingHorizontal: 4,
  },
  actionIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 8,
  },
  actionButtonText: {
    fontSize: 12,
    fontWeight: '500',
    color: '#1f2937',
    textAlign: 'center',
  },
  usdcSection: {
    paddingHorizontal: 16,
    marginBottom: 16,
  },
  usdcCard: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    padding: 16,
    borderLeftWidth: 4,
    borderLeftColor: colors.accent,
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
  usdcHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  usdcInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
    marginRight: 12,
  },
  usdcLogo: {
    width: 40,
    height: 40,
    borderRadius: 20,
    marginRight: 12,
  },
  usdcTextContainer: {
    flex: 1,
  },
  usdcName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
    marginBottom: 2,
  },
  usdcDescription: {
    fontSize: 12,
    color: '#6b7280',
    flexWrap: 'wrap',
  },
  usdcBalance: {
    alignItems: 'flex-end',
  },
  usdcBalanceText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  usdcSymbol: {
    fontSize: 12,
    color: '#6b7280',
  },
  usdcAddressContainer: {
    marginBottom: 12,
  },
  usdcAddressLabel: {
    fontSize: 12,
    color: '#6b7280',
    marginBottom: 4,
  },
  usdcAddressRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  usdcAddressText: {
    fontSize: 12,
    color: '#6b7280',
    marginRight: 4,
  },
  usdcActions: {
    flexDirection: 'row',
    gap: 8,
  },
  usdcActionButton: {
    flex: 1,
    backgroundColor: colors.neutralDark,
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  usdcActionButtonText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  transactionsSection: {
    paddingHorizontal: 16,
    paddingBottom: 24,
  },
  transactionsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  transactionsTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  transactionsFilters: {
    flexDirection: 'row',
    gap: 8,
  },
  filterButton: {
    padding: 8,
    backgroundColor: '#ffffff',
    borderRadius: 8,
  },
  transactionsList: {
    gap: 8,
  },
  transactionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ffffff',
    borderRadius: 12,
    padding: 16,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#f3f4f6',
  },
  transactionIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  transactionInfo: {
    flex: 1,
  },
  transactionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  transactionDate: {
    fontSize: 12,
    color: '#6b7280',
  },
  transactionAmount: {
    alignItems: 'flex-end',
  },
  transactionAmountText: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  positiveAmount: {
    color: '#10b981',
  },
  negativeAmount: {
    color: '#ef4444',
  },
  transactionStatus: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusText: {
    fontSize: 12,
    color: '#10b981',
    marginRight: 4,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#10b981',
  },
  viewAllButton: {
    alignItems: 'center',
    paddingVertical: 24,
  },
  viewAllButtonText: {
    fontSize: 14,
    fontWeight: '500',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 16,
  },
  modalContent: {
    backgroundColor: '#ffffff',
    borderRadius: 16,
    width: '100%',
    maxWidth: 400,
    padding: 24,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  exchangeContainer: {
    marginBottom: 24,
  },
  exchangeInputContainer: {
    backgroundColor: colors.neutralDark,
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  exchangeInputHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  exchangeInputLabel: {
    fontSize: 12,
    color: '#6b7280',
  },
  exchangeInput: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  exchangeInputText: {
    flex: 1,
    fontSize: 24,
    fontWeight: 'bold',
    color: '#1f2937',
  },
  currencyBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginLeft: 8,
  },
  currencyIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  currencyIconText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 12,
  },
  currencyText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  exchangeArrow: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    alignSelf: 'center',
    marginBottom: 16,
  },
  feeContainer: {
    marginBottom: 24,
  },
  feeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  feeLabel: {
    fontSize: 12,
    color: '#6b7280',
  },
  feeValue: {
    fontSize: 12,
    fontWeight: '500',
    color: '#1f2937',
  },
  feeDivider: {
    height: 1,
    backgroundColor: '#e5e7eb',
    marginBottom: 12,
  },
  feeTotalLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  feeTotalValue: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
  },
  exchangeButton: {
    backgroundColor: colors.primary,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  exchangeButtonDisabled: {
    opacity: 0.5,
  },
  exchangeButtonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: 'bold',
  },
}); 