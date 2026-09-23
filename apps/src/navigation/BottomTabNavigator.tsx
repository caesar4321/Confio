import React, { useCallback, useMemo } from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Icon from 'react-native-vector-icons/Feather';
import { View, StyleSheet, Platform } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { BottomTabParamList, RootStackParamList } from '../types/navigation';
import DiscoverScreen from '../screens/DiscoverScreen';
import { InvestScreen } from '../screens/InvestScreen';
import { DiscoverStackHeader } from './StackScreenHeaders';
import { HomeScreen } from '../screens/HomeScreen';
import ScanTab from '../screens/ScanTab';
import { ChargeScreen } from '../screens/ChargeScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { Header } from './Header';
import { QrPayIcon } from '../components/QrPayIcon';
import { useHeader } from '../contexts/HeaderContext';
import { useAccount } from '../contexts/AccountContext';
import { useAuth } from '../contexts/AuthContext';
import { useQuery } from '@apollo/client';
import { GET_MESSAGE_INBOX_UNREAD_COUNT } from '../apollo/queries';
import { Text } from 'react-native';

// Single navigator instance
const Tabs = createBottomTabNavigator<BottomTabParamList>();

type TabNavigatorNavigationProp = NavigationProp<RootStackParamList>;

export const BottomTabNavigator = () => {
  const navigation = useNavigation<TabNavigatorNavigationProp>();
  const { unreadNotifications, currentAccountAvatar, profileMenu } = useHeader();
  const { activeAccount, isLoading: accountsLoading } = useAccount();
  const { isAuthenticated, isLoading: authLoading, accountContextTick } = useAuth();
  const canQueryMessages = isAuthenticated && !authLoading;
  const messageContextKey = activeAccount?.id || 'no-account';
  const { data: messageUnreadData, refetch: refetchMessageUnread } = useQuery(GET_MESSAGE_INBOX_UNREAD_COUNT, {
    variables: { contextKey: messageContextKey },
    fetchPolicy: 'network-only',
    nextFetchPolicy: 'cache-first',
    skip: !canQueryMessages,
  });

  // 🔥 Fix: Normalize the account type to lowercase for comparison
  const accountType = (activeAccount?.type || 'personal').toLowerCase();
  const isEmployee = activeAccount?.isEmployee || false;
  const canSendFunds = !isEmployee || activeAccount?.employeePermissions?.sendFunds === true;

  //
  const handleNotificationPress = useCallback(() => {
    navigation.navigate('Notification' as any);
  }, [navigation]);

  const handleMessagesPress = useCallback(() => {
    navigation.navigate('HomeMessages' as any);
  }, [navigation]);
  React.useEffect(() => {
    if (!canQueryMessages) {
      return;
    }
    refetchMessageUnread();
  }, [accountContextTick, canQueryMessages, refetchMessageUnread, messageContextKey]);

  // Create stable header components for each screen
  const HomeHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={true}
      title="Confío"
      onProfilePress={profileMenu.openProfileMenu}
      onNotificationPress={handleNotificationPress}
      onMessagePress={handleMessagesPress}
      backgroundColor="#34d399"
      showBackButton={false}
      isLight={false}
      unreadNotifications={unreadNotifications}
      unreadMessages={messageUnreadData?.messageInboxUnreadCount || 0}
      currentAccountAvatar={currentAccountAvatar}
    />
  ), [navigation, profileMenu.openProfileMenu, handleNotificationPress, handleMessagesPress, unreadNotifications, currentAccountAvatar, messageUnreadData?.messageInboxUnreadCount]);


  // Charge header removed since ChargeScreen has its own header



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

  // Personal accounts pay from the center tab; businesses use Cobrar → Pagar.
  const scanTabOptions = useMemo(() => ({
    headerShown: false,
    freezeOnBlur: true,
    tabBarLabel: () => (
      <Text style={{ color: '#10B981', fontSize: 12, fontWeight: '600' }}>Pagar</Text>
    ),
    tabBarIcon: () => (
      <View style={styles.payButton}>
        <QrPayIcon size={32} color="#fff" />
      </View>
    ),
    tabBarAccessibilityLabel: 'Pagar con QR',
    tabBarButton: !canSendFunds ? () => null : undefined,
  }), [canSendFunds]);

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



  // Remove dynamic key to prevent re-renders that cause keyboard dismissal
  // The conditional rendering of tabs is sufficient for account type changes
  // const tabNavigatorKey = useMemo(() => 
  //   `tab-navigator-${activeAccount?.id || 'default'}-${accountType}`,
  //   [activeAccount?.id, accountType] // Use normalized accountType
  // );

  //
  return (
    <>
      <Tabs.Navigator
        detachInactiveScreens
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
            freezeOnBlur: true,
            tabBarLabel: 'Inicio',
            tabBarIcon: ({ color, size }: any) => <Icon name="home" size={size} color={color} />
          }}
        />
        <Tabs.Screen
          name="Invest"
          component={InvestScreen}
          options={{
            // The shared Header, like every main tab: same title size and
            // position everywhere. The screen's hero continues its green.
            header: () => (
              <Header
                navigation={navigation}
                isHomeScreen={false}
                title="Invertir"
                backgroundColor="#34d399"
                showBackButton={false}
                isLight
                unreadNotifications={0}
                currentAccountAvatar="U"
              />
            ),
            tabBarLabel: 'Invertir',
            tabBarIcon: ({ color, size }) => <Icon name="trending-up" size={size} color={color} />,
          }}
        />
        {isBusinessAccount && (
          <Tabs.Screen
            name="Charge"
            component={ChargeScreen}
            options={{ ...chargeTabOptions, freezeOnBlur: true }}
          />
        )}
        {!isBusinessAccount && (
          <Tabs.Screen
            name="Scan"
            component={ScanTab}
            options={scanTabOptions}
          />
        )}
        <Tabs.Screen
          name="Discover"
          component={DiscoverScreen}
          options={{
            header: () => <DiscoverStackHeader showBackButton={false} />,
            tabBarLabel: 'Descubrir',
            tabBarIcon: ({ color, size }) => <Icon name="compass" size={size} color={color} />,
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
  headerIconButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: '#E5E7EB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerIconButtonActive: {
    backgroundColor: '#111827',
    borderColor: '#111827',
  },
  payButton: {
    width: 60,
    height: 60,
    // Rounded square, not a circle: it echoes the scanner frame drawn inside
    // and sets Pagar apart from Cobrar's round button on business accounts.
    borderRadius: 18,
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
