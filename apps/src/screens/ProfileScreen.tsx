import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Platform, Linking, Image } from 'react-native';
import Icon from 'react-native-vector-icons/Feather';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RootStackParamList, MainStackParamList } from '../types/navigation';
import { getCountryByIso } from '../utils/countries';
import { usePushNotificationPrompt } from '../hooks/usePushNotificationPrompt';
import { PushNotificationModal } from '../components/PushNotificationModal';
import { useQuery } from '@apollo/client';
import { GET_USER_ACHIEVEMENTS, GET_ACHIEVEMENT_TYPES } from '../apollo/queries';

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
  const { activeAccount, accounts, isLoading: accountsLoading, refreshAccounts } = useAccount();
  const navigation = useNavigation<ProfileScreenNavigationProp>();
  const { showModal, handleAllow, handleDeny, checkAndShowPrompt, needsSettings } = usePushNotificationPrompt();
  const [hasCheckedThisFocus, setHasCheckedThisFocus] = React.useState(false);
  
  // Fetch real achievements
  const { data: achievementsData, loading: achievementsLoading } = useQuery(GET_USER_ACHIEVEMENTS, {
    fetchPolicy: 'cache-and-network',
  });
  
  // Fetch all available achievement types to get the correct total count
  const { data: achievementTypesData, loading: achievementTypesLoading } = useQuery(GET_ACHIEVEMENT_TYPES, {
    fetchPolicy: 'cache-and-network',
  });

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
      
      // Reset the check flag when screen loses focus
      return () => {
        setHasCheckedThisFocus(false);
      };
    }, [refreshAccounts])
  );
  
  // Separate effect for push notification check to avoid infinite loop
  React.useEffect(() => {
    if (!hasCheckedThisFocus && !showModal) {
      console.log('[ProfileScreen] Checking push notification permission...');
      setHasCheckedThisFocus(true);
      checkAndShowPrompt();
    }
  }, [hasCheckedThisFocus, showModal, checkAndShowPrompt]);

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

  const handleSocialMediaPress = async (platform: 'tiktok' | 'instagram' | 'youtube') => {
    let url = '';
    switch (platform) {
      case 'tiktok':
        url = 'https://www.tiktok.com/@julianmoonluna';
        break;
      case 'instagram':
        url = 'https://www.instagram.com/julianmoonluna';
        break;
      case 'youtube':
        url = 'https://www.youtube.com/@julianmoonluna';
        break;
    }
    
    try {
      await Linking.openURL(url);
    } catch (error) {
      console.error(`Error opening ${platform} link:`, error);
    }
  };

  // Get real achievements from query
  const userAchievements = achievementsData?.userAchievements || [];
  const achievementTypes = achievementTypesData?.achievementTypes || [];
  
  // Debug achievements data (can be removed after testing)
  React.useEffect(() => {
    console.log('ProfileScreen Debug:');
    console.log('- achievementsData:', achievementsData);
    console.log('- userAchievements:', userAchievements);
    console.log('- achievementTypes:', achievementTypes);
    console.log('- completedCount:', userAchievements.filter(a => 
      a.status?.toLowerCase() === 'earned' || a.status?.toLowerCase() === 'claimed'
    ).length);
    console.log('- totalAchievements:', achievementTypes.length);
  }, [achievementsData, userAchievements, achievementTypes, achievementsLoading, achievementTypesLoading]);
  
  // Count completed achievements (earned or claimed)
  // Note: GraphQL returns uppercase statuses like "CLAIMED", "EARNED"
  const completedCount = userAchievements.filter(a => 
    a.status?.toLowerCase() === 'earned' || a.status?.toLowerCase() === 'claimed'
  ).length;
  
  // Use the total number of available achievement types (not just user's achievements)
  const totalAchievements = achievementTypes.length || 0;

  // Get display information based on active account
  const getDisplayInfo = () => {
    // Only show loading when we have no data yet
    const stillFetching = (accountsLoading && !activeAccount) ||
                          (isUserProfileLoading && !userProfile);

    if (stillFetching) {
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
    <>
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

      {/* Achievements Card */}
      <TouchableOpacity style={styles.card} onPress={() => navigation.navigate('Achievements')}>
        <View style={styles.cardHeader}>
          <View style={styles.cardTitleRow}>
            <Icon name="award" size={20} color={colors.primary} />
            <Text style={styles.cardTitle}>Logros</Text>
          </View>
          <View style={styles.achievementProgress}>
            <Text style={styles.achievementProgressText}>
              {(achievementsLoading || achievementTypesLoading) ? '...' : `${completedCount}/${totalAchievements}`}
            </Text>
            <Icon name="chevron-right" size={16} color="#9CA3AF" />
          </View>
        </View>
        <View style={styles.achievementPreview}>
          {userAchievements.slice(0, 5).map((achievement, index) => (
            <View 
              key={achievement.id || index} 
              style={[
                styles.achievementDot,
                (achievement.status === 'earned' || achievement.status === 'claimed') 
                  ? styles.achievementDotCompleted 
                  : styles.achievementDotLocked
              ]}
            />
          ))}
          {/* Show placeholder dots if we have less than 5 achievements */}
          {userAchievements.length < 5 && Array.from({ length: 5 - userAchievements.length }).map((_, index) => (
            <View 
              key={`placeholder-${index}`} 
              style={[styles.achievementDot, styles.achievementDotLocked]}
            />
          ))}
          {totalAchievements > 5 && (
            <Text style={styles.achievementMore}>+{totalAchievements - 5}</Text>
          )}
        </View>
      </TouchableOpacity>

      {/* Account Management Card */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardTitleRow}>
            <Icon name="user" size={20} color="#6B7280" />
            <Text style={styles.cardTitle}>Cuenta</Text>
          </View>
        </View>
        <View style={styles.cardOptions}>
          <TouchableOpacity 
            style={styles.cardOption}
            onPress={() => navigation.navigate('Verification')}
          >
            <Icon name="user-check" size={18} color="#6B7280" />
            <Text style={styles.cardOptionText}>Verificación</Text>
            <Icon name="chevron-right" size={16} color="#9CA3AF" />
          </TouchableOpacity>
          
          {/* Hide payment methods for employees without permission */}
          {(!activeAccount?.isEmployee || activeAccount?.employeePermissions?.manageBankAccounts) && (
            <TouchableOpacity 
              style={styles.cardOption}
              onPress={() => navigation.navigate('BankInfo')}
            >
              <Icon name="credit-card" size={18} color="#6B7280" />
              <Text style={styles.cardOptionText}>Métodos de Pago</Text>
              <Icon name="chevron-right" size={16} color="#9CA3AF" />
            </TouchableOpacity>
          )}
          
          {activeAccount?.type.toLowerCase() === 'personal' && (
            <TouchableOpacity 
              style={styles.cardOption}
              onPress={() => navigation.navigate('ConfioAddress')}
            >
              <Icon name="at-sign" size={18} color="#6B7280" />
              <Text style={styles.cardOptionText}>Mi dirección Confío</Text>
              <Icon name="chevron-right" size={16} color="#9CA3AF" />
            </TouchableOpacity>
          )}
        </View>
      </View>

      {/* Community Card */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <View style={styles.cardTitleRow}>
            <Icon name="users" size={20} color="#6B7280" />
            <Text style={styles.cardTitle}>Comunidad</Text>
          </View>
        </View>
        <View style={styles.cardOptions}>
          <TouchableOpacity 
            style={styles.cardOption}
            onPress={handleTelegramPress}
          >
            <Icon name="message-circle" size={18} color="#6B7280" />
            <Text style={styles.cardOptionText}>Grupo Telegram</Text>
            <Text style={styles.cardOptionSubtext}>@FansDeJulian</Text>
            <Icon name="chevron-right" size={16} color="#9CA3AF" />
          </TouchableOpacity>
        </View>
      </View>

      {/* Follow the Founder Section */}
      <View style={styles.founderSection}>
        <View style={styles.founderHeader}>
          <Icon name="star" size={20} color={colors.primary} />
          <Text style={styles.founderTitle}>Sigue al fundador</Text>
        </View>
        
        <View style={styles.socialButtonsContainer}>
          <TouchableOpacity 
            style={styles.socialImageButton} 
            onPress={() => handleSocialMediaPress('tiktok')}
          >
            <Image 
              source={require('../assets/png/TikTok.png')} 
              style={[styles.socialButtonImage, styles.tiktokImage]}
              resizeMode="contain"
            />
          </TouchableOpacity>
          
          <TouchableOpacity 
            style={styles.socialImageButton} 
            onPress={() => handleSocialMediaPress('instagram')}
          >
            <Image 
              source={require('../assets/png/Instagram.png')} 
              style={styles.socialButtonImage}
              resizeMode="contain"
            />
          </TouchableOpacity>
          
          <TouchableOpacity 
            style={styles.socialImageButton} 
            onPress={() => handleSocialMediaPress('youtube')}
          >
            <Image 
              source={require('../assets/png/YouTube.png')} 
              style={styles.socialButtonImage}
              resizeMode="contain"
            />
          </TouchableOpacity>
        </View>
        
        <View style={styles.founderStory}>
          <Text style={styles.founderHandle}>@julianmoonluna</Text>
          <Text style={styles.founderTagline}>
            Un coreano que sueña con una nueva Latinoamérica
          </Text>
          <Text style={styles.founderDescription}>
            Descubre por qué un coreano confía en América Latina
          </Text>
        </View>
      </View>

      {/* Legal Links */}
      <View style={styles.legalSection}>
        <TouchableOpacity 
          style={styles.legalLink}
          onPress={() => handleLegalDocumentPress('terms')}
        >
          <Text style={styles.legalLinkText}>Términos de Servicio</Text>
        </TouchableOpacity>
        <Text style={styles.legalSeparator}>•</Text>
        <TouchableOpacity 
          style={styles.legalLink}
          onPress={() => handleLegalDocumentPress('privacy')}
        >
          <Text style={styles.legalLinkText}>Privacidad</Text>
        </TouchableOpacity>
        <Text style={styles.legalSeparator}>•</Text>
        <TouchableOpacity 
          style={styles.legalLink}
          onPress={() => handleLegalDocumentPress('deletion')}
        >
          <Text style={styles.legalLinkText}>Eliminación</Text>
        </TouchableOpacity>
      </View>

      {/* Sign Out Button */}
      <TouchableOpacity style={styles.signOutButton} onPress={signOut}>
        <Text style={styles.signOutText}>Cerrar Sesión</Text>
      </TouchableOpacity>
    </ScrollView>
    
    {/* Push Notification Permission Modal */}
    <PushNotificationModal
      visible={showModal}
      onAllow={handleAllow}
      onDeny={handleDeny}
      needsSettings={needsSettings}
    />
  </>
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
  card: {
    backgroundColor: '#fff',
    borderRadius: 16,
    marginHorizontal: 16,
    marginBottom: 12,
    padding: 16,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.05,
        shadowRadius: 4,
      },
      android: {
        elevation: 2,
      },
    }),
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  cardTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1F2937',
  },
  cardOptions: {
    gap: 12,
  },
  cardOption: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
  },
  cardOptionText: {
    flex: 1,
    fontSize: 15,
    color: '#374151',
    marginLeft: 12,
  },
  cardOptionSubtext: {
    fontSize: 13,
    color: '#9CA3AF',
    marginRight: 8,
  },
  achievementProgress: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  achievementProgressText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.primary,
  },
  achievementPreview: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  achievementDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  achievementDotCompleted: {
    backgroundColor: colors.primary,
  },
  achievementDotLocked: {
    backgroundColor: '#E5E7EB',
  },
  achievementMore: {
    fontSize: 12,
    color: '#9CA3AF',
    marginLeft: 4,
  },
  founderSection: {
    paddingHorizontal: 16,
    paddingVertical: 20,
    alignItems: 'center',
  },
  separator: {
    height: 1,
    backgroundColor: '#E5E7EB',
    marginHorizontal: 16,
    marginVertical: 8,
  },
  founderHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
    gap: 8,
  },
  founderTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#1F2937',
  },
  socialButtonsContainer: {
    flexDirection: 'row',
    marginVertical: 16,
    justifyContent: 'center',
    alignItems: 'center',
  },
  socialImageButton: {
    width: 69, // Fixed width for all buttons (53 + 16 padding)
    height: 69, // Fixed height for all buttons
    justifyContent: 'center',
    alignItems: 'center',
    marginHorizontal: 10, // Equal spacing between buttons
  },
  socialButtonImage: {
    width: 53, // 2/3 of 80px for Instagram and YouTube
    height: 53,
  },
  tiktokImage: {
    width: 40, // Keep TikTok at original size
    height: 40,
  },
  founderStory: {
    alignItems: 'center',
    gap: 4,
  },
  founderHandle: {
    fontSize: 16,
    color: colors.primary,
    fontWeight: '700',
    marginBottom: 4,
  },
  founderTagline: {
    fontSize: 15,
    color: '#1F2937',
    fontWeight: '600',
    textAlign: 'center',
  },
  founderDescription: {
    fontSize: 13,
    color: '#6B7280',
    textAlign: 'center',
    fontStyle: 'italic',
  },
  legalSection: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 16,
    marginTop: 16,
    marginBottom: 8,
  },
  legalLink: {
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  legalLinkText: {
    fontSize: 13,
    color: '#6B7280',
  },
  legalSeparator: {
    color: '#E5E7EB',
    fontSize: 13,
  },
  signOutButton: {
    marginTop: 16,
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