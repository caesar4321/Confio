import GuideAnchorView from '../assistant/GuideAnchorView';
import React, { useCallback, useMemo } from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Icon from 'react-native-vector-icons/Feather';
import { View, StyleSheet, Platform } from 'react-native';
import { Text } from '../components/common/AppText';
import { getFocusedRouteNameFromRoute, useNavigation, useNavigationState, useRoute } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { BottomTabParamList, RootStackParamList } from '../types/navigation';
import { InvestTabScreen } from '../screens/InvestTabScreen';
import { ComprarScreen } from '../screens/ComprarScreen';
import { HomeScreen } from '../screens/HomeScreen';
import ScanTab from '../screens/ScanTab';
import { ChargeScreen } from '../screens/ChargeScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { Header } from './Header';
import { QrPayIcon } from '../components/QrPayIcon';
import { useHeader } from '../contexts/HeaderContext';
import { useAccount } from '../contexts/AccountContext';
import { colors } from '../config/theme';
import { peekBadge, useCommunityPeek, watchCommunityPeek } from '../services/communityPeek';
import { useSharedQr } from '../hooks/useSharedQr';
import { Alert } from 'react-native';
import { CONVERSATION_HOME_ENABLED } from '../config/features';
import { AppDrawerProvider } from '../home/AppDrawer';
import { ConversationHomeScreen } from '../home/ConversationHomeScreen';
import { DrawerHeader } from '../home/DrawerHeader';
import { FloatingPrimaryButton } from '../home/FloatingPrimaryButton';
import { logHomeNav } from '../services/homeNavAnalytics';

// Module-level, so the tab bar and headers keep a stable identity.
const NoTabBar = () => null;
const ComprarDrawerHeader = () => <DrawerHeader title="Comprar" backgroundColor="#fff" />;
const ProfileDrawerHeader = () => <DrawerHeader title="Mi Perfil" backgroundColor={colors.heroField} isLight />;
// The same names the conversation home's doors log, so the two compare.
const TAB_TARGETS: Record<string, string> = { Scan: 'pay' };

// The Cuenta inteligente homes, loaded only when a smart context is active:
// almost nobody is in one at launch, and the tab bar should not pull their
// modules (the account switcher, the signing path) in for everyone else.
// Module-level components, so their identity is stable across renders.
const SmartAccountHomeTab = () => {
  const Screen = require('../screens/SmartAccountHomeScreen').SmartAccountHomeTab;
  return <Screen />;
};
const InheritedAccountTab = () => {
  const Screen = require('../screens/InheritedAccountScreen').InheritedAccountTab;
  return <Screen />;
};

// Single navigator instance
const Tabs = createBottomTabNavigator<BottomTabParamList>();

type TabNavigatorNavigationProp = NavigationProp<RootStackParamList>;

export const BottomTabNavigator = () => {
  const navigation = useNavigation<TabNavigatorNavigationProp>();
  const { unreadNotifications, currentAccountAvatar, profileMenu } = useHeader();
  const { activeAccount, isLoading: accountsLoading } = useAccount();
  // New Comunidad posts badge the Invertir tab (Comunidad lives inside it).
  const communityPeek = useCommunityPeek();
  const investBadge = peekBadge(communityPeek);
  React.useEffect(() => watchCommunityPeek(), []);
  // The message box lives in the floating Confio Assistant bubble (every screen);
  // the Home header no longer has an inbox button.

  // 🔥 Fix: Normalize the account type to lowercase for comparison
  const accountType = (activeAccount?.type || 'personal').toLowerCase();
  const isEmployee = activeAccount?.isEmployee || false;
  const canSendFunds = !isEmployee || activeAccount?.employeePermissions?.sendFunds === true;
  // Check if account is business (using normalized type)
  const isBusinessAccount = accountType === 'business';
  // A Cuenta inteligente context (own, or inherited when index > 0). Its home
  // replaces Inicio, and only what the account supports stays: no Invertir
  // (Futuros, Comunidad), no Pagar, no Cobrar, no Comprar. The server refuses
  // those flows for a smart token too (dual enforcement).
  const isSmartAccount = accountType === 'smart';
  const isInheritedAccount = isSmartAccount && (activeAccount?.index ?? 0) > 0;
  // The conversation home (docs/designs/ai-assistant-first-redesign.md 7):
  // no tab bar; the same routes, reached from the drawer. A Cuenta
  // inteligente context keeps its own two-tab home for now.
  const conversationHome = CONVERSATION_HOME_ENABLED && !isSmartAccount;
  // From the parent stack's raw state, so it is right on the first render (a
  // link that opens straight on Invertir) and on every tab change. The route
  // object from useRoute() alone is reused across tab changes outside
  // production and would leave this one navigation behind.
  const shellKey = useRoute().key;
  const focusedTab = useNavigationState((state) => {
    const shell = state.routes.find((r) => r.key === shellKey);
    return shell ? getFocusedRouteNameFromRoute(shell) : undefined;
  }) ?? 'Home';

  // A QR shared from another app opens Pagar as if it had been scanned; the
  // scan handler applies every check (employee, rail, account) from there.
  useSharedQr((payload) => {
    if (isSmartAccount || !canSendFunds) {
      Alert.alert('Pagar un QR', isSmartAccount
        ? 'Cambia a tu cuenta personal o de negocio para pagar este QR.'
        : 'Tu rol en este negocio no permite hacer pagos.', [{ text: 'Entendido' }]);
      return;
    }
    navigation.navigate('Scan' as any, { mode: 'pagar', sharedQr: payload, sharedAt: Date.now() } as any);
  });

  //
  const handleNotificationPress = useCallback(() => {
    logHomeNav('header', 'notifications');
    navigation.navigate('Notification' as any);
  }, [navigation]);
  const handleChargePress = useCallback(() => {
    logHomeNav('header', 'charge');
    navigation.navigate('Charge' as any);
  }, [navigation]);
  const handleProfileMenuPress = useCallback(() => {
    logHomeNav('header', 'switch_account');
    profileMenu.openProfileMenu();
  }, [profileMenu.openProfileMenu]);


  // Create stable header components for each screen
  const HomeHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={true}
      title="Confío"
      onProfilePress={handleProfileMenuPress}
      onNotificationPress={handleNotificationPress}
      // A business has Cobrar as a tab; a person gets it here and in Recibir.
      onChargePress={isBusinessAccount ? undefined : handleChargePress}
      backgroundColor={colors.heroField}
      showBackButton={false}
      isLight={false}
      unreadNotifications={unreadNotifications}
      currentAccountAvatar={currentAccountAvatar}
    />
  ), [navigation, handleProfileMenuPress, handleNotificationPress, handleChargePress, isBusinessAccount, unreadNotifications, currentAccountAvatar]);


  // Charge header removed since ChargeScreen has its own header



  const ProfileHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Mi Perfil"
      onProfilePress={undefined}
      onNotificationPress={undefined}
      backgroundColor={colors.heroField}
      showBackButton={false}
      isLight={true}
      unreadNotifications={0}
      currentAccountAvatar="U"
    />
  ), [navigation]);

  // Personal accounts pay from the center tab; businesses use Cobrar → Pagar.
  const scanTabOptions = useMemo(() => ({
    headerShown: false,
    freezeOnBlur: true,
    tabBarLabel: () => (
      <Text style={{ color: '#10B981', fontSize: 12, fontWeight: '600' }}>Pagar</Text>
    ),
    tabBarIcon: () => (
      <GuideAnchorView id="tab_pay">
        <View style={styles.payButton}>
          <QrPayIcon size={32} color="#fff" />
        </View>
      </GuideAnchorView>
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
  // Chosen per build, never per account: swapping the wrapper would remount
  // every tab on an account switch.
  const Shell = CONVERSATION_HOME_ENABLED ? AppDrawerProvider : React.Fragment;
  return (
    <Shell>
      <Tabs.Navigator
        detachInactiveScreens
        tabBar={conversationHome ? NoTabBar : undefined}
        screenListeners={({ route }: { route: { name: string } }) => ({
          // Only the tab bar fires this (the conversation home has none).
          tabPress: () => logHomeNav('tabs', TAB_TARGETS[route.name] || route.name.toLowerCase()),
        })}
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
          component={isInheritedAccount ? InheritedAccountTab : isSmartAccount ? SmartAccountHomeTab
            : conversationHome ? ConversationHomeScreen : HomeScreen}
          options={{
            header: () => <HomeHeader />,
            // The smart homes draw the shared Header themselves (help circle
            // and the account avatar live in it); so does the conversation home.
            headerShown: !isSmartAccount && !conversationHome,
            // The conversation home keeps publishing balances for the drawer
            // while another screen is in front, so it is never frozen; and it
            // mounts with the shell, so a shell opened straight on Invertir or
            // Comprar still has a menu with the person's money in it.
            freezeOnBlur: !conversationHome,
            lazy: !conversationHome,
            tabBarLabel: 'Inicio',
            tabBarIcon: ({ color, size }: any) => <GuideAnchorView id="tab_home"><Icon name="home" size={size} color={color} /></GuideAnchorView>
          }}
        />
        {!isSmartAccount && (
        <Tabs.Screen
          name="Invest"
          component={InvestTabScreen}
          options={{
            // The conversation home's Invertir/Comunidad draw their own
            // header (the title follows which one is open).
            headerShown: !conversationHome,
            // The shared Header, like every main tab: same title size and
            // position everywhere. The screen's hero continues its green.
            header: () => (
              <Header
                navigation={navigation}
                isHomeScreen={false}
                title="Invertir"
                backgroundColor={colors.heroField}
                showBackButton={false}
                isLight
                unreadNotifications={0}
                currentAccountAvatar="U"
              />
            ),
            tabBarLabel: 'Invertir',
            tabBarIcon: ({ color, size }) => <GuideAnchorView id="tab_invest"><Icon name="trending-up" size={size} color={color} /></GuideAnchorView>,
            tabBarBadge: investBadge === null ? undefined : investBadge,
            tabBarBadgeStyle: investBadge === ''
              ? { minWidth: 10, maxHeight: 10, borderRadius: 5, backgroundColor: colors.secondary }
              : { backgroundColor: colors.secondary, color: '#fff', fontSize: 10 },
          }}
        />
        )}
        {isBusinessAccount && (
          <Tabs.Screen
            name="Charge"
            component={ChargeScreen}
            options={{ ...chargeTabOptions, freezeOnBlur: true }}
          />
        )}
        {/* The conversation home pays from the stack's Scan (it has the back
            arrow a screen without tabs needs). */}
        {!isBusinessAccount && !isSmartAccount && !conversationHome && (
          <Tabs.Screen
            name="Scan"
            component={ScanTab}
            options={scanTabOptions}
          />
        )}
        {/* Comunidad moved into Invertir; news and Julian's posts live in the
            assistant bubble. The fourth tab is Comprar (marketplace). */}
        {!isSmartAccount && (
        <Tabs.Screen
          name="Comprar"
          component={ComprarScreen}
          options={{
            header: conversationHome ? ComprarDrawerHeader : () => (
              <Header
                navigation={navigation}
                isHomeScreen={false}
                title="Comprar"
                backgroundColor="#fff"
                showBackButton={false}
                isLight={false}
                unreadNotifications={0}
                currentAccountAvatar="U"
              />
            ),
            tabBarLabel: 'Comprar',
            tabBarIcon: ({ color, size }) => <GuideAnchorView id="tab_comprar"><Icon name="shopping-bag" size={size} color={color} /></GuideAnchorView>,
          }}
        />
        )}
        <Tabs.Screen 
          name="Profile" 
          component={ProfileScreen}
          options={{
            header: conversationHome ? ProfileDrawerHeader : () => <ProfileHeader />,
            tabBarLabel: 'Perfil',
            tabBarIcon: ({ color, size }: any) => <GuideAnchorView id="tab_profile"><Icon name="user" size={size} color={color} /></GuideAnchorView>
          }}
        />
      </Tabs.Navigator>
      {conversationHome ? <FloatingPrimaryButton tab={focusedTab} /> : null}
    </Shell>
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
