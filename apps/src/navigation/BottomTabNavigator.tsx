import React, { useCallback } from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Icon from 'react-native-vector-icons/Feather';
import { View, StyleSheet, Platform } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NavigationProp } from '@react-navigation/native';
import { MainStackParamList, BottomTabParamList, RootStackParamList } from '../types/navigation';
import { HomeScreen } from '../screens/HomeScreen';
import { ContactsScreen } from '../screens/ContactsScreen';
import { ScanScreen } from '../screens/ScanScreen';
import { ExchangeScreen } from '../screens/ExchangeScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { Header } from './Header';
import { useHeader } from '../contexts/HeaderContext';

const Tab = createBottomTabNavigator<BottomTabParamList>();

type TabNavigatorNavigationProp = NavigationProp<RootStackParamList>;

export const BottomTabNavigator = () => {
  const navigation = useNavigation<TabNavigatorNavigationProp>();
  const { unreadNotifications, currentAccountAvatar, profileMenu } = useHeader();

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

  const ScanHeader = useCallback(() => (
    <Header
      navigation={navigation}
      isHomeScreen={false}
      title="Escanear"
      onProfilePress={undefined}
      onNotificationPress={undefined}
      backgroundColor={undefined}
      showBackButton={false}
      isLight={false}
      unreadNotifications={0}
      currentAccountAvatar="U"
    />
  ), [navigation]);

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

  return (
    <Tab.Navigator
      screenOptions={({ route }) => {
        // Set the label based on the route
        let tabBarLabel = '';
        if (route.name === 'Home') { tabBarLabel = 'Inicio'; }
        else if (route.name === 'Contacts') { tabBarLabel = 'Contactos'; }
        else if (route.name === 'Scan') { tabBarLabel = 'Escanear'; }
        else if (route.name === 'Exchange') { tabBarLabel = 'Intercambio'; }
        else if (route.name === 'Profile') { tabBarLabel = 'Perfil'; }

        return {
          header: () => {
            switch (route.name) {
              case 'Home':
                return <HomeHeader />;
              case 'Contacts':
                return <ContactsHeader />;
              case 'Scan':
                return <ScanHeader />;
              case 'Exchange':
                return <ExchangeHeader />;
              case 'Profile':
                return <ProfileHeader />;
              default:
                return null;
            }
          },
          tabBarLabel,
          tabBarActiveTintColor: '#8B5CF6', // Violet (secondary)
          tabBarInactiveTintColor: '#6B7280', // Gray-500
          tabBarStyle: {
            backgroundColor: '#FFFFFF', // White background
            borderTopWidth: 1,
            borderTopColor: '#E5E7EB', // Gray-200
            height: 64,
            paddingBottom: 8,
            paddingTop: 8,
          },
          tabBarIcon: ({ color, size, focused }) => {
            if (route.name === 'Scan') {
              return (
                <View style={styles.scanButton}>
                  <Icon name="maximize" size={32} color="#fff" />
                </View>
              );
            }
            
            let icon;
            if (route.name === 'Home') {
              icon = <Icon name="home" size={size} color={color} />;
            } else if (route.name === 'Contacts') {
              icon = <Icon name="users" size={size} color={color} />;
            } else if (route.name === 'Exchange') {
              icon = <Icon name="repeat" size={size} color={color} />;
            } else if (route.name === 'Profile') {
              icon = <Icon name="user" size={size} color={color} />;
            }
            return icon;
          },
        };
      }}
    >
      <Tab.Screen name="Home" component={HomeScreen} />
      <Tab.Screen name="Contacts" component={ContactsScreen} />
      <Tab.Screen name="Scan" component={ScanScreen} />
      <Tab.Screen name="Exchange" component={ExchangeScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
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