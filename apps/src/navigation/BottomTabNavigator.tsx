import React, { useCallback, useMemo } from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Icon from 'react-native-vector-icons/Feather';
import { View, StyleSheet, Platform } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { MainStackParamList, BottomTabParamList, RootStackParamList } from '../types/navigation';
import { HomeScreen } from '../screens/HomeScreen';
import { ContactsScreen } from '../screens/ContactsScreen';
import ScanTab from '../screens/ScanTab';
import { ChargeScreen } from '../screens/ChargeScreen';
import { ExchangeScreen } from '../screens/ExchangeScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { Header } from './Header';
import { useHeader } from '../contexts/HeaderContext';
import { useAccount } from '../contexts/AccountContext';
import { Text } from 'react-native';

// Single navigator instance
const Tabs = createBottomTabNavigator<BottomTabParamList>();

type TabNavigatorNavigationProp = NavigationProp<RootStackParamList>;

export const BottomTabNavigator = () => {
  const navigation = useNavigation<TabNavigatorNavigationProp>();
  const { unreadNotifications, currentAccountAvatar, profileMenu } = useHeader();
  const { activeAccount, isLoading: accountsLoading } = useAccount();

  // 🔥 Fix: Normalize the account type to lowercase for comparison
  const accountType = (activeAccount?.type || 'personal').toLowerCase();
  const isBusiness = accountType === 'business';

  console.log('🔍 BottomTabNavigator - Active account:', {
    accountId: activeAccount?.id,
    originalType: activeAccount?.type,
    normalizedType: accountType,
    accountName: activeAccount?.name,
    isBusiness
  });

  const handleNotificationPress = useCallback(() => {
    navigation.navigate('Notification' as any);
  }, [navigation]);

  // Create stable header components for each screen
  const HomeHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={true}
      title="Confío"
      onProfilePress={profileMenu.openProfileMenu}
      onNotificationPress={handleNotificationPress}
      backgroundColor="#34d399"
      showBackButton={false}
      isLight={false}
      unreadNotifications={unreadNotifications}
      currentAccountAvatar={currentAccountAvatar}
    />
  ), [navigation, profileMenu.openProfileMenu, handleNotificationPress, unreadNotifications, currentAccountAvatar]);

  const ContactsHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Contactos"
      onProfilePress={undefined}
      onNotificationPress={undefined}
      backgroundColor="#fff"
      showBackButton={false}
      isLight={false}
      unreadNotifications={0}
      currentAccountAvatar="U"
    />
  ), [navigation]);

  // Dynamic scan header that updates based on account type
  const ScanHeader = useCallback(() => {
    const title = 'Escanear';
    return (
      <Header
        navigation={navigation}
        isHomeScreen={false}
        title={title}
        onProfilePress={undefined}
        onNotificationPress={undefined}
        backgroundColor={undefined}
        showBackButton={false}
        isLight={false}
        unreadNotifications={0}
        currentAccountAvatar="U"
      />
    );
  }, [navigation]);

  // Charge header removed since ChargeScreen has its own header



  const ExchangeHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Intercambio P2P"
      onProfilePress={undefined}
      onNotificationPress={undefined}
      backgroundColor="#fff"
      showBackButton={false}
      isLight={false}
      unreadNotifications={0}
      currentAccountAvatar="U"
    />
  ), [navigation]);

  const ProfileHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Mi Perfil"
      onProfilePress={undefined}
      onNotificationPress={undefined}
      backgroundColor="#34d399"
      showBackButton={false}
      isLight={true}
      unreadNotifications={0}
      currentAccountAvatar="U"
    />
  ), [navigation]);

  // Check if account is business (using normalized type)
  const isBusinessAccount = accountType === 'business';

  // Memoize tab options to ensure they update when activeAccount changes
  const scanTabOptions = useMemo(() => ({
    header: () => <ScanHeader />,
    tabBarLabel: ({ color }: any) => (
      <Text style={{ color, fontSize: 12 }}>
        Escanear
      </Text>
    ),
    tabBarIcon: ({ color, size }: any) => (
      <View style={styles.scanButton}>
        <Icon name="maximize" size={32} color="#fff" />
      </View>
    ),
    tabBarButton: isBusinessAccount ? () => null : undefined, // Hide for business accounts
  }), [ScanHeader, isBusinessAccount]);

  // Charge tab options - only show for business accounts
  const chargeTabOptions = useMemo(() => ({
    headerShown: false, // Remove header entirely since ChargeScreen has its own header
    tabBarLabel: ({ color }: any) => (
      <Text style={{ color, fontSize: 12 }}>
        Cobrar
      </Text>
    ),
    tabBarIcon: ({ color, size }: any) => (
      <View style={styles.scanButton}>
        <Icon name="dollar-sign" size={32} color="#fff" />
      </View>
    ),
    tabBarButton: !isBusinessAccount ? () => null : undefined, // Hide for personal accounts
  }), [isBusinessAccount]);



  // Force re-render when activeAccount changes by using a key
  const tabNavigatorKey = useMemo(() => 
    `tab-navigator-${activeAccount?.id || 'default'}-${accountType}`,
    [activeAccount?.id, accountType] // Use normalized accountType
  );

  console.log('🔑 TabNavigator Key:', tabNavigatorKey, 'isBusinessAccount:', isBusinessAccount);

  return (
    <>
      <Tabs.Navigator
        key={tabNavigatorKey} // This forces re-render when account changes
        screenOptions={{
          tabBarActiveTintColor: '#8B5CF6',
          tabBarInactiveTintColor: '#6B7280',
          tabBarStyle: {
            backgroundColor: '#FFFFFF',
            borderTopWidth: 1,
            borderTopColor: '#E5E7EB',
            height: 64,
            paddingBottom: 8,
            paddingTop: 8,
          },
        }}
      >
        <Tabs.Screen 
          name="Home" 
          component={HomeScreen}
          options={{
            header: () => <HomeHeader />,
            tabBarLabel: 'Inicio',
            tabBarIcon: ({ color, size }: any) => <Icon name="home" size={size} color={color} />
          }}
        />
        <Tabs.Screen 
          name="Contacts" 
          component={ContactsScreen}
          options={{
            header: () => <ContactsHeader />,
            tabBarLabel: 'Contactos',
            tabBarIcon: ({ color, size }: any) => <Icon name="users" size={size} color={color} />
          }}
        />
        {!isBusinessAccount && (
          <Tabs.Screen 
            name="Scan" 
            component={ScanTab}
            options={scanTabOptions}
          />
        )}
        {isBusinessAccount && (
          <Tabs.Screen 
            name="Charge" 
            component={ChargeScreen}
            options={chargeTabOptions}
          />
        )}
        <Tabs.Screen 
          name="Exchange" 
          component={ExchangeScreen}
          options={{
            header: () => <ExchangeHeader />,
            tabBarLabel: 'Intercambio',
            tabBarIcon: ({ color, size }: any) => <Icon name="repeat" size={size} color={color} />
          }}
        />
        <Tabs.Screen 
          name="Profile" 
          component={ProfileScreen}
          options={{
            header: () => <ProfileHeader />,
            tabBarLabel: 'Perfil',
            tabBarIcon: ({ color, size }: any) => <Icon name="user" size={size} color={color} />
          }}
        />
      </Tabs.Navigator>
    </>
  );
};

const styles = StyleSheet.create({
  scanButton: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#34d399',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 40,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 2 },
        shadowOpacity: 0.25,
        shadowRadius: 3.84,
      },
      android: {
        elevation: 5,
      },
    }),
  },
}); 