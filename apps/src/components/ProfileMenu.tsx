import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { getCountryByIso } from '../utils/countries';

// Utility function to format phone number with country code
const formatPhoneNumber = (phoneNumber?: string, phoneCountry?: string): string => {
  if (!phoneNumber) return '';
  
  // If we have a country code, format it
  if (phoneCountry) {
    const country = getCountryByIso(phoneCountry);
    if (country) {
      const countryCode = country[1]; // country[1] is the phone code (e.g., '+54')
      return `${countryCode} ${phoneNumber}`;
    }
  }
  
  return phoneNumber;
};

interface Account {
  id: string;
  name: string;
  type: 'personal' | 'business';
  phone?: string;
  category?: string;
  avatar: string;
  isEmployee?: boolean;
  employeeRole?: 'cashier' | 'manager' | 'admin';
}

interface ProfileMenuProps {
  visible: boolean;
  onClose: () => void;
  accounts: Account[];
  selectedAccount: string;
  onAccountSwitch: (accountId: string) => void;
  onCreateBusinessAccount: () => void;
}

export const ProfileMenu: React.FC<ProfileMenuProps> = ({
  visible,
  onClose,
  accounts,
  selectedAccount,
  onAccountSwitch,
  onCreateBusinessAccount,
}) => {
  const { userProfile, isUserProfileLoading } = useAuth();
  const { isLoading: accountsLoading } = useAccount();

  // For personal accounts, only format phone number with country code
  const displayAccounts = accounts.map(acc => {
    if (acc.type === 'personal' && userProfile) {
      return {
        ...acc,
        phone: formatPhoneNumber(userProfile.phoneNumber, userProfile.phoneCountry),
      };
    }
    return acc;
  });
  const currentAccount = displayAccounts.find(acc => acc.id === selectedAccount) || displayAccounts[0];

  // Debug logging
  console.log('ProfileMenu render:', { 
    visible, 
    selectedAccount, 
    currentAccount: !!currentAccount,
    currentAccountName: currentAccount?.name,
    currentAccountAvatar: currentAccount?.avatar,
    accountsCount: accounts.length,
    accounts: displayAccounts.map(acc => ({ id: acc.id, name: acc.name, avatar: acc.avatar, type: acc.type }))
  });

  // Do not return null — render with a safe placeholder so the menu never disappears mid-hydration
  const headerAccount = currentAccount || ({ id: 'personal_0', name: 'Personal', type: 'personal', avatar: 'P' } as Account);

  return (
    <Modal
      visible={visible}
      transparent={true}
      animationType="fade"
      onRequestClose={onClose}
    >
      <TouchableOpacity
        style={styles.overlay}
        activeOpacity={1}
        onPress={onClose}
      >
        <View style={styles.menuContainer}>
          {/* Header */}
          <View style={styles.header}>
            <View style={styles.accountInfo}>
              <View style={styles.avatarContainer}>
                <Text style={styles.avatarText}>{headerAccount.avatar}</Text>
              </View>
              <View style={styles.accountDetails}>
                <Text style={styles.accountName}>{headerAccount.name}</Text>
                <Text style={styles.accountType}>
                  {headerAccount.type.toLowerCase() === "personal" 
                    ? "Personal"
                    : "Negocio"}
                </Text>
              </View>
            </View>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Text style={styles.closeButtonText}>✕</Text>
            </TouchableOpacity>
          </View>

          {/* Account List */}
          <View style={styles.accountList}>
            <Text style={styles.sectionTitle}>Cambiar cuenta</Text>
            
            {accountsLoading ? (
              <Text style={{ padding: 16 }}>Cargando cuentas...</Text>
            ) : (
              displayAccounts.map((account) => (
                <TouchableOpacity
                  key={account.id}
                  style={[
                    styles.accountItem,
                    selectedAccount === account.id && styles.selectedAccount
                  ]}
                  onPress={() => onAccountSwitch(account.id)}
                >
                  <View style={styles.accountItemAvatar}>
                    <Text style={styles.accountItemAvatarText}>{account.avatar}</Text>
                  </View>
                  <View style={styles.accountItemInfo}>
                    <Text style={styles.accountItemName}>{account.name}</Text>
                    <Text style={styles.accountItemType}>
                      {account.type.toLowerCase() === "personal" 
                        ? "Personal" 
                        : account.isEmployee 
                          ? `Empleado - ${account.employeeRole === 'cashier' ? 'Cajero' : account.employeeRole === 'manager' ? 'Gerente' : 'Admin'}`
                          : "Negocio"}
                    </Text>
                  </View>
                  {selectedAccount === account.id && (
                    <View style={styles.selectedIndicator} />
                  )}
                </TouchableOpacity>
              ))
            )}

            {/* Create Business Account Button */}
            <TouchableOpacity 
              style={styles.createAccountButton}
              onPress={onCreateBusinessAccount}
            >
              <View style={styles.createAccountIcon}>
                <Icon name="plus" size={16} color="#9CA3AF" />
              </View>
              <View style={styles.createAccountInfo}>
                <Text style={styles.createAccountTitle}>Crear cuenta de negocio</Text>
                <Text style={styles.createAccountSubtitle}>Agregar nuevo negocio</Text>
              </View>
            </TouchableOpacity>
          </View>
        </View>
      </TouchableOpacity>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.2)',
    justifyContent: 'flex-start',
    alignItems: 'flex-end',
    paddingTop: 80,
    paddingRight: 16,
  },
  menuContainer: {
    width: 288,
    maxWidth: '90%',
    backgroundColor: '#fff',
    borderRadius: 16,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 4,
    },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#F3F4F6',
    backgroundColor: '#F9FAFB',
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
  },
  accountInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  avatarContainer: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#F3F4F6',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  avatarText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: '#6B7280',
  },
  accountDetails: {
    flex: 1,
  },
  accountName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 2,
  },
  accountType: {
    fontSize: 12,
    color: '#6B7280',
  },
  closeButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#F3F4F6',
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButtonText: {
    fontSize: 16,
    color: '#6B7280',
    fontWeight: '600',
  },
  accountList: {
    padding: 12,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 12,
  },
  accountItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 8,
    borderRadius: 8,
    marginBottom: 4,
  },
  selectedAccount: {
    backgroundColor: '#F3F4F6',
  },
  accountItemAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#E5E7EB',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  accountItemAvatarText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
  },
  accountItemInfo: {
    flex: 1,
  },
  accountItemName: {
    fontSize: 14,
    fontWeight: '600',
    color: '#1F2937',
    marginBottom: 2,
  },
  accountItemType: {
    fontSize: 12,
    color: '#6B7280',
  },
  selectedIndicator: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#34d399',
  },
  createAccountButton: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 8,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: '#E5E7EB',
    borderStyle: 'dashed',
    marginTop: 8,
  },
  createAccountIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#F9FAFB',
    borderWidth: 2,
    borderColor: '#E5E7EB',
    borderStyle: 'dashed',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  createAccountInfo: {
    flex: 1,
  },
  createAccountTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6B7280',
    marginBottom: 2,
  },
  createAccountSubtitle: {
    fontSize: 12,
    color: '#9CA3AF',
  },
}); 
