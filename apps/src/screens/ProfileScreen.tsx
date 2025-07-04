import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, Linking } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useAuth } from '../contexts/AuthContext';
import { useAccountManager } from '../hooks/useAccountManager';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RootStackParamList, MainStackParamList } from '../types/navigation';
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

type ProfileScreenNavigationProp = NativeStackNavigationProp<MainStackParamList>;

export const ProfileScreen = () => {
  const { signOut, userProfile, isUserProfileLoading } = useAuth();
  const { activeAccount, accounts, isLoading: accountsLoading, refreshAccounts } = useAccountManager();
  const navigation = useNavigation<ProfileScreenNavigationProp>();

  // Debug active account changes to ensure real-time updates
  React.useEffect(() => {
    console.log('ProfileScreen - activeAccount changed:', {
      activeAccountId: activeAccount?.id,
      activeAccountName: activeAccount?.name,
      activeAccountType: activeAccount?.type,
      isLoading: accountsLoading
    });
  }, [activeAccount, accountsLoading]);

  // Force refresh when screen comes into focus to ensure latest state
  useFocusEffect(
    React.useCallback(() => {
      console.log('ProfileScreen - Screen focused, refreshing accounts');
      refreshAccounts();
    }, [refreshAccounts])
  );

  const handleLegalDocumentPress = (docType: 'terms' | 'privacy' | 'deletion') => {
    navigation.navigate('LegalDocument', { docType });
  };

  const handleTelegramPress = async () => {
    const telegramUrl = 'tg://resolve?domain=FansDeJulian';
    const webUrl = 'https://t.me/FansDeJulian';
    try {
      const canOpen = await Linking.canOpenURL(telegramUrl);
      if (canOpen) {
        await Linking.openURL(telegramUrl);
      } else {
        // Fallback to t.me URL
        await Linking.openURL(webUrl);
      }
    } catch (error) {
      console.error('Error opening Telegram link:', error);
      // Fallback to t.me URL
      await Linking.openURL(webUrl);
    }
  };

  const profileOptions = [
    { name: "Verificación", icon: "user-check", onPress: () => navigation.navigate('Verification') },
    /* Temporarily hidden until 2FA and advanced security features are implemented
    { name: "Seguridad", icon: "shield", onPress: () => {} },
    { name: "Notificaciones", icon: "bell", onPress: () => {} },
    */
    { name: "Comunidad", icon: "users", onPress: handleTelegramPress },
    { name: "Términos de Servicio", icon: "file-text", onPress: () => handleLegalDocumentPress('terms') },
    { name: "Política de Privacidad", icon: "lock", onPress: () => handleLegalDocumentPress('privacy') },
    { name: "Eliminación de Datos", icon: "trash-2", onPress: () => handleLegalDocumentPress('deletion') }
  ];

  // Get display information based on active account
  const getDisplayInfo = () => {
    if (accountsLoading || isUserProfileLoading) {
      return { name: 'Cargando...', subtitle: '', showAccountType: false };
    }

    if (activeAccount) {
      const isPersonal = activeAccount.type.toLowerCase() === 'personal';
      const accountType = isPersonal ? 'Personal' : 'Negocio';
      
      if (isPersonal) {
        // For personal accounts, show user profile info with phone number (no account type label)
        const displayName = userProfile?.firstName || userProfile?.username || activeAccount.name;
        const phoneNumber = formatPhoneNumber(userProfile?.phoneNumber, userProfile?.phoneCountry);
        return {
          name: displayName,
          subtitle: phoneNumber,
          accountType: '',
          showAccountType: false
        };
      } else {
        // For business accounts, show business info with account type only (no category)
        return {
          name: activeAccount.name,
          subtitle: '',
          accountType,
          showAccountType: true
        };
      }
    }

    // Fallback to user profile with phone number (no account type label)
    const displayName = userProfile?.firstName || userProfile?.username || 'Sin perfil';
    const phoneNumber = formatPhoneNumber(userProfile?.phoneNumber, userProfile?.phoneCountry);
    return {
      name: displayName,
      subtitle: phoneNumber,
      accountType: '',
      showAccountType: false
    };
  };

  const displayInfo = getDisplayInfo();

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.scrollContent}>
      {/* Header Section */}
      <View style={styles.header}>
        <View style={styles.profileInfo}>
          <TouchableOpacity 
            style={styles.avatarContainer}
            onPress={() => {
              const isBusiness = activeAccount?.type.toLowerCase() === 'business';
              if (isBusiness) {
                navigation.navigate('EditBusiness');
              } else {
                navigation.navigate('EditProfile');
              }
            }}
          >
            <Text style={styles.avatarText}>
              {activeAccount?.avatar || (userProfile?.firstName?.charAt(0) || userProfile?.username?.charAt(0) || 'U')}
            </Text>
            <View style={styles.editIconContainer}>
              <Icon name="edit-2" size={12} color="#fff" />
            </View>
          </TouchableOpacity>
          <Text style={styles.name}>{displayInfo.name}</Text>
          {displayInfo.showAccountType && (
            <Text style={styles.accountType}>{displayInfo.accountType}</Text>
          )}
          {displayInfo.subtitle && (
            <Text style={styles.subtitle}>{displayInfo.subtitle}</Text>
          )}
        </View>
      </View>

      {/* Confío Address Card - Only show for personal accounts */}
      {activeAccount?.type.toLowerCase() === 'personal' && (
        <View style={styles.addressCard}>
          <TouchableOpacity 
            style={styles.addressCardContent}
            onPress={() => navigation.navigate('ConfioAddress')}
          >
            <View style={styles.addressIconContainer}>
              <Icon name="maximize" size={20} color="#6B7280" />
            </View>
            <View style={styles.addressInfo}>
              <Text style={styles.addressTitle}>Mi dirección de Confío</Text>
              <Text style={styles.addressValue}>
                {userProfile?.username ? `confio.lat/@${userProfile.username}` : 'confio.lat/@usuario'}
              </Text>
            </View>
            <Icon name="chevron-right" size={20} color="#9CA3AF" />
          </TouchableOpacity>
        </View>
      )}

      {/* Profile Options */}
      <View style={styles.optionsContainer}>
        {profileOptions.map((option, index) => (
          <TouchableOpacity key={index} style={styles.optionItem} onPress={option.onPress}>
            <View style={styles.optionLeft}>
              <View style={styles.optionIconContainer}>
                <Icon name={option.icon} size={20} color="#6B7280" />
              </View>
              <Text style={styles.optionText}>{option.name}</Text>
            </View>
            <Icon name="chevron-right" size={20} color="#9CA3AF" />
          </TouchableOpacity>
        ))}
      </View>

      {/* Sign Out Button */}
      <TouchableOpacity style={styles.signOutButton} onPress={signOut}>
        <Text style={styles.signOutText}>Cerrar Sesión</Text>
      </TouchableOpacity>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  scrollContent: {
    flexGrow: 1,
  },
  header: {
    backgroundColor: '#34d399', // emerald-400
    paddingBottom: 32,
    paddingHorizontal: 20,
    borderBottomLeftRadius: 32,
    borderBottomRightRadius: 32,
  },
  profileInfo: {
    alignItems: 'center',
  },
  avatarContainer: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#fff',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
    position: 'relative',
  },
  avatarText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#34d399',
  },
  editIconContainer: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#fff',
  },
  name: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#fff',
    marginBottom: 4,
  },
  accountType: {
    fontSize: 14,
    color: 'rgba(255, 255, 255, 0.9)',
    marginBottom: 2,
  },
  subtitle: {
    fontSize: 14,
    color: 'rgba(255, 255, 255, 0.8)',
  },
  addressCard: {
    backgroundColor: '#fff',
    borderRadius: 16,
    marginTop: -16,
    marginHorizontal: 16,
    marginBottom: 8,
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
  addressCardContent: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
  },
  addressIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.neutralDark,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  addressInfo: {
    flex: 1,
  },
  addressTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
    marginBottom: 2,
  },
  addressValue: {
    fontSize: 12,
    color: '#6B7280',
  },
  optionsContainer: {
    paddingHorizontal: 16,
    paddingTop: 16,
    gap: 12,
  },
  optionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.neutralDark,
    padding: 12,
    borderRadius: 12,
  },
  optionLeft: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  optionIconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#fff',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  optionText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#1F2937',
  },
  signOutButton: {
    marginTop: 32,
    marginBottom: 32,
    paddingVertical: 12,
    alignItems: 'center',
  },
  signOutText: {
    color: '#EF4444',
    fontSize: 16,
    fontWeight: '500',
  },
}); 