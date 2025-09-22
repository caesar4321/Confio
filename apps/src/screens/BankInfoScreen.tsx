import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Platform,
  Alert,
  ActivityIndicator,
  Modal,
  TextInput,
  RefreshControl,
  FlatList,
} from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useQuery, useMutation } from '@apollo/client';
import { 
  GET_USER_BANK_ACCOUNTS, 
  GET_COUNTRIES, 
  GET_BANKS, 
  CREATE_BANK_INFO,
  UPDATE_BANK_INFO,
  DELETE_BANK_INFO,
  SET_DEFAULT_BANK_INFO,
  GET_USER_ACCOUNTS
} from '../apollo/queries';
import { useAccount } from '../contexts/AccountContext';
import { SafeAreaView } from 'react-native-safe-area-context';
import { AddBankInfoModal } from '../components/AddBankInfoModal';

// Colors matching app design
const colors = {
  primary: '#34d399', // emerald-400
  primaryLight: '#d1fae5', // emerald-100
  primaryDark: '#10b981', // emerald-500
  secondary: '#8b5cf6', // violet-500
  accent: '#3b82f6', // blue-500
  background: '#f9fafb', // gray-50
  neutralDark: '#f3f4f6', // gray-100
  text: {
    primary: '#1f2937', // gray-800
    secondary: '#6b7280', // gray-500
    light: '#9ca3af', // gray-400
  },
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
};

type BankInfoNavigationProp = NativeStackNavigationProp<any>;

interface BankAccount {
  id: string;
  account: {
    id: string;
    accountId: string;
    displayName: string;
    accountType: string;
  };
  paymentMethod?: {
    id: string;
    name: string;
    displayName: string;
    providerType: string;
    icon: string;
    requiresPhone: boolean;
    requiresEmail: boolean;
    requiresAccountNumber: boolean;
    bank?: {
      id: string;
      name: string;
      shortName?: string;
      country: {
        id: string;
        code: string;
        name: string;
        flagEmoji: string;
        requiresIdentification: boolean;
        identificationName: string;
      };
    };
    country?: {
      id: string;
      code: string;
      name: string;
      flagEmoji: string;
      requiresIdentification: boolean;
      identificationName: string;
    };
  };
  country?: {
    id: string;
    code: string;
    name: string;
    flagEmoji: string;
    requiresIdentification: boolean;
    identificationName: string;
  };
  bank?: {
    id: string;
    name: string;
    shortName?: string;
  };
  accountHolderName: string;
  accountNumber?: string;
  maskedAccountNumber?: string;
  accountType?: string;
  identificationNumber?: string;
  phoneNumber?: string;
  email?: string;
  username?: string;
  isDefault: boolean;
  isPublic: boolean;
  isVerified: boolean;
  summaryText: string;
  fullBankName: string;
  requiresIdentification: boolean;
  identificationLabel: string;
  createdAt: string;
}

interface Country {
  id: string;
  code: string;
  name: string;
  flagEmoji: string;
  requiresIdentification: boolean;
  identificationName: string;
  identificationFormat?: string;
}

interface Bank {
  id: string;
  code: string;
  name: string;
  shortName?: string;
  country: {
    id: string;
    code: string;
    name: string;
    flagEmoji: string;
  };
  supportsChecking: boolean;
  supportsSavings: boolean;
  supportsPayroll: boolean;
  accountTypeChoices: string[];
}

export const BankInfoScreen = () => {
  const navigation = useNavigation<BankInfoNavigationProp>();
  // No dynamic insets; SafeAreaView handles device padding
  const { activeAccount } = useAccount();
  
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingBankInfo, setEditingBankInfo] = useState<BankAccount | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  
  // Check if user is an employee without manage_bank_accounts permission
  const isEmployee = activeAccount?.isEmployee || false;
  const canManageBankAccounts = !isEmployee || activeAccount?.employeePermissions?.manageBankAccounts;


  // GraphQL queries
  // Server determines context from JWT token
  const { 
    data: bankAccountsData, 
    loading: bankAccountsLoading, 
    error: bankAccountsError,
    refetch: refetchBankAccounts 
  } = useQuery(GET_USER_BANK_ACCOUNTS, {
    fetchPolicy: 'cache-and-network'
  });

  const bankAccounts: BankAccount[] = bankAccountsData?.userBankAccounts || [];

  // Mutations
  const [setDefaultBankInfo] = useMutation(SET_DEFAULT_BANK_INFO);
  const [deleteBankInfo] = useMutation(DELETE_BANK_INFO);

  // Refresh functionality
  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refetchBankAccounts();
    } catch (error) {
      console.error('Error refreshing bank accounts:', error);
    } finally {
      setRefreshing(false);
    }
  };

  // Focus effect to refresh data
  useFocusEffect(
    React.useCallback(() => {
      refetchBankAccounts();
    }, [refetchBankAccounts])
  );

  const handleSetDefault = async (bankInfoId: string) => {
    try {
      const { data } = await setDefaultBankInfo({
        variables: { bankInfoId }
      });

      if (data?.setDefaultBankInfo?.success) {
        Alert.alert('Éxito', 'Cuenta bancaria marcada como predeterminada');
        refetchBankAccounts();
      } else {
        Alert.alert('Error', data?.setDefaultBankInfo?.error || 'Error al marcar como predeterminada');
      }
    } catch (error) {
      console.error('Error setting default bank info:', error);
      Alert.alert('Error', 'Error de conexión');
    }
  };

  const handleDelete = async (bankInfoId: string, bankName: string) => {
    Alert.alert(
      'Eliminar Cuenta Bancaria',
      `¿Estás seguro de que quieres eliminar la cuenta de ${bankName}?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: async () => {
            try {
              const { data } = await deleteBankInfo({
                variables: { bankInfoId }
              });

              if (data?.deleteBankInfo?.success) {
                Alert.alert('Éxito', 'Cuenta bancaria eliminada');
                refetchBankAccounts();
              } else {
                Alert.alert('Error', data?.deleteBankInfo?.error || 'Error al eliminar');
              }
            } catch (error) {
              console.error('Error deleting bank info:', error);
              Alert.alert('Error', 'Error de conexión');
            }
          }
        }
      ]
    );
  };

  const handleEdit = (bankInfo: BankAccount) => {
    setEditingBankInfo(bankInfo);
    setShowAddModal(true);
  };

  const handleAddNew = () => {
    setEditingBankInfo(null);
    setShowAddModal(true);
  };


  const renderBankAccountCard = (bankAccount: BankAccount) => {
    // Determine if this is a bank or other payment method type
    const isBank = bankAccount.paymentMethod?.providerType === 'BANK';
    const isDigitalWallet = bankAccount.paymentMethod?.providerType === 'DIGITAL_WALLET';
    const isMobilePayment = bankAccount.paymentMethod?.providerType === 'MOBILE_PAYMENT';
    
    // Get country flag emoji - check payment method first, then legacy fields
    let flagEmoji = bankAccount.paymentMethod?.bank?.country?.flagEmoji || 
                    bankAccount.paymentMethod?.country?.flagEmoji ||  // For non-bank payment methods
                    bankAccount.country?.flagEmoji;
                    
    // Use specific icons for non-bank payment methods if no flag
    if (!flagEmoji) {
      if (isDigitalWallet) flagEmoji = '💳';
      else if (isMobilePayment) flagEmoji = '📱';
      else flagEmoji = '🏦';
    }
    
    // Get bank/payment method name
    const displayName = bankAccount.fullBankName || 
                       bankAccount.paymentMethod?.displayName || 
                       bankAccount.bank?.name || 
                       'Payment Method';
    
    // Get country name for additional context
    const countryName = bankAccount.paymentMethod?.bank?.country?.name || 
                        bankAccount.paymentMethod?.country?.name ||  // For non-bank payment methods
                        bankAccount.country?.name || 
                        '';
    
    return (
      <View key={bankAccount.id} style={styles.bankCard}>
        <View style={styles.bankCardHeader}>
          <View style={styles.bankInfo}>
            <View style={styles.bankNameRow}>
              <Text style={styles.countryFlag}>{flagEmoji}</Text>
              <View style={styles.bankNameContainer}>
                <Text style={styles.bankName}>{displayName}</Text>
                {countryName && (
                  <Text style={styles.countryName}>{countryName}</Text>
                )}
              </View>
              {bankAccount.isDefault && (
                <View style={styles.defaultBadge}>
                  <Text style={styles.defaultText}>Predeterminada</Text>
                </View>
            )}
          </View>
          <Text style={styles.accountHolder}>{bankAccount.accountHolderName}</Text>
          <Text style={styles.accountDetails}>
            {bankAccount.summaryText}
          </Text>
          {bankAccount.identificationNumber && (
            <Text style={styles.identificationText}>
              {bankAccount.identificationLabel}: {bankAccount.identificationNumber}
            </Text>
          )}
        </View>
        <View style={styles.bankActions}>
          <TouchableOpacity
            style={styles.actionButton}
            onPress={() => handleEdit(bankAccount)}
          >
            <Icon name="edit-2" size={16} color={colors.accent} />
          </TouchableOpacity>
          {!bankAccount.isDefault && (
            <TouchableOpacity
              style={styles.actionButton}
              onPress={() => handleSetDefault(bankAccount.id)}
            >
              <Icon name="star" size={16} color={colors.warning} />
            </TouchableOpacity>
          )}
          <TouchableOpacity
            style={styles.actionButton}
            onPress={() => handleDelete(bankAccount.id, displayName)}
          >
            <Icon name="trash-2" size={16} color={colors.error} />
          </TouchableOpacity>
        </View>
      </View>
      
      {bankAccount.isVerified && (
        <View style={styles.verifiedBadge}>
          <Icon name="check-circle" size={14} color={colors.success} />
          <Text style={styles.verifiedText}>Cuenta Verificada</Text>
        </View>
      )}
    </View>
    );
  };

  const renderEmptyState = () => (
    <View style={styles.emptyState}>
      <Icon name="credit-card" size={64} color={colors.text.light} />
      <Text style={styles.emptyTitle}>No tienes métodos de pago</Text>
      <Text style={styles.emptyDescription}>
        Agrega tu información bancaria o billetera digital para poder recibir pagos y hacer transferencias.
      </Text>
      <TouchableOpacity style={styles.addButton} onPress={handleAddNew}>
        <Icon name="plus" size={20} color="white" />
        <Text style={styles.addButtonText}>Agregar Método de Pago</Text>
      </TouchableOpacity>
    </View>
  );

  // Show permission denied screen for employees without permission
  if (!canManageBankAccounts) {
    return (
      <SafeAreaView edges={['top']} style={styles.container}>
        {/* Header */}
        <View style={[styles.header, { paddingTop: 8 }]}>
          <View style={styles.headerContent}>
            <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
              <Icon name="arrow-left" size={24} color="white" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Métodos de Pago</Text>
            <View style={{ width: 40 }} />
          </View>
        </View>
        
        <View style={styles.permissionDeniedContainer}>
          <Icon name="lock" size={64} color={colors.text.light} />
          <Text style={styles.permissionDeniedTitle}>Información del Negocio</Text>
          <Text style={styles.permissionDeniedText}>
            Los métodos de pago de {activeAccount?.business?.name || 'la empresa'} son gestionados por el equipo administrativo.
          </Text>
          <Text style={styles.permissionDeniedSubtext}>
            Si necesitas información sobre pagos, consulta con tu supervisor.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={styles.container}>
      {/* Header */}
      <View style={[styles.header, { paddingTop: 8 }]}>
        <View style={styles.headerContent}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
            <Icon name="arrow-left" size={24} color="white" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Métodos de Pago</Text>
          <TouchableOpacity onPress={handleAddNew} style={styles.addHeaderButton}>
            <Icon name="plus" size={24} color="white" />
          </TouchableOpacity>
        </View>
      </View>

      <View style={styles.contentContainer}>
        {/* Payment Methods Header */}
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Métodos de Pago Configurados</Text>
          <Text style={styles.sectionSubtitle}>
            {bankAccounts.length} método{bankAccounts.length !== 1 ? 's' : ''}
          </Text>
        </View>

        {bankAccountsLoading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.loadingText}>Cargando cuentas bancarias...</Text>
          </View>
        ) : bankAccountsError ? (
          <View style={styles.errorContainer}>
            <Icon name="alert-circle" size={48} color={colors.error} />
            <Text style={styles.errorText}>Error al cargar las cuentas</Text>
            <TouchableOpacity style={styles.retryButton} onPress={onRefresh}>
              <Text style={styles.retryText}>Reintentar</Text>
            </TouchableOpacity>
          </View>
        ) : bankAccounts.length === 0 ? (
          renderEmptyState()
        ) : (
          <FlatList
            data={bankAccounts}
            renderItem={({ item }) => renderBankAccountCard(item)}
            keyExtractor={(item) => item.id}
            style={styles.content}
            contentContainerStyle={styles.listContent}
            showsVerticalScrollIndicator={false}
            refreshControl={
              <RefreshControl
                refreshing={refreshing}
                onRefresh={onRefresh}
                colors={[colors.primary]}
                tintColor={colors.primary}
              />
            }
            ListFooterComponent={
              <TouchableOpacity style={styles.addMoreButton} onPress={handleAddNew}>
                <Icon name="plus-circle" size={20} color={colors.primary} />
                <Text style={styles.addMoreText}>Agregar otro método de pago</Text>
              </TouchableOpacity>
            }
            // FlatList optimizations
            initialNumToRender={10}
            maxToRenderPerBatch={10}
            windowSize={21}
            removeClippedSubviews={true}
            updateCellsBatchingPeriod={50}
          />
        )}
      </View>

      {/* Add/Edit Modal */}
      <Modal
        visible={showAddModal}
        animationType="slide"
        presentationStyle="pageSheet"
      >
        <AddBankInfoModal
          isVisible={showAddModal}
          onClose={() => {
            setShowAddModal(false);
            setEditingBankInfo(null);
          }}
          onSuccess={() => {
            setShowAddModal(false);
            setEditingBankInfo(null);
            refetchBankAccounts();
          }}
          accountId={activeAccount?.id}
          editingBankInfo={editingBankInfo}
        />
      </Modal>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  contentContainer: {
    flex: 1,
  },
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 24,
  },
  header: {
    backgroundColor: colors.primary,
    paddingBottom: 24,
    paddingHorizontal: 16,
  },
  headerContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  addHeaderButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: 'white',
  },
  content: {
    flex: 1,
    paddingHorizontal: 16,
  },
  section: {
    marginBottom: 24,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  sectionSubtitle: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  bankCard: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
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
  bankCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  bankInfo: {
    flex: 1,
  },
  bankNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  countryFlag: {
    fontSize: 20,
    marginRight: 8,
  },
  bankNameContainer: {
    flex: 1,
  },
  bankName: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.text.primary,
  },
  countryName: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 2,
  },
  defaultBadge: {
    backgroundColor: colors.primaryLight,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    marginLeft: 8,
  },
  defaultText: {
    fontSize: 10,
    color: colors.primaryDark,
    fontWeight: '600',
  },
  accountHolder: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 2,
  },
  accountDetails: {
    fontSize: 12,
    color: colors.text.secondary,
    marginBottom: 2,
  },
  identificationText: {
    fontSize: 12,
    color: colors.text.light,
  },
  bankActions: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  actionButton: {
    padding: 8,
    marginLeft: 4,
  },
  verifiedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: colors.neutralDark,
  },
  verifiedText: {
    fontSize: 12,
    color: colors.success,
    fontWeight: '600',
    marginLeft: 4,
  },
  loadingContainer: {
    alignItems: 'center',
    paddingVertical: 40,
  },
  loadingText: {
    marginTop: 12,
    color: colors.text.secondary,
  },
  errorContainer: {
    alignItems: 'center',
    paddingVertical: 40,
  },
  errorText: {
    marginTop: 12,
    marginBottom: 16,
    color: colors.error,
    textAlign: 'center',
  },
  retryButton: {
    backgroundColor: colors.error,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
  },
  retryText: {
    color: 'white',
    fontWeight: '600',
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 60,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginTop: 16,
    marginBottom: 8,
  },
  emptyDescription: {
    fontSize: 14,
    color: colors.text.secondary,
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 20,
  },
  addButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  addButtonText: {
    color: 'white',
    fontWeight: '600',
    marginLeft: 8,
  },
  addMoreButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'white',
    paddingVertical: 16,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: colors.primaryLight,
    borderStyle: 'dashed',
  },
  addMoreText: {
    color: colors.primary,
    fontWeight: '600',
    marginLeft: 8,
  },
  permissionDeniedContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  permissionDeniedTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: colors.text.primary,
    marginTop: 24,
    marginBottom: 12,
  },
  permissionDeniedText: {
    fontSize: 16,
    color: colors.text.secondary,
    textAlign: 'center',
    marginBottom: 8,
    lineHeight: 24,
  },
  permissionDeniedSubtext: {
    fontSize: 14,
    color: colors.text.light,
    textAlign: 'center',
    lineHeight: 20,
  },
});
