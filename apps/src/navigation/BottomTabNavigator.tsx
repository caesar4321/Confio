import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Icon from 'react-native-vector-icons/Feather';
import { View, StyleSheet } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RootStackParamList } from '../types/navigation';
import { HomeScreen } from '../screens/HomeScreen';
import { ContactsScreen } from '../screens/ContactsScreen';
import { ScanScreen } from '../screens/ScanScreen';
import { ExchangeScreen } from '../screens/ExchangeScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { Header } from './Header';

const Tab = createBottomTabNavigator();

export const BottomTabNavigator = () => {
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();

  return (
    <Tab.Navigator
      screenOptions={({ route }) => {
        // Determine if this is the Home screen
        const isHomeScreen = route.name === 'Home';
        // Set the title and label based on the route
        let title = 'Confío';
        let tabBarLabel = '';
        let headerBg = undefined;
        if (route.name === 'Home') { title = 'Confío'; tabBarLabel = 'Inicio'; }
        else if (route.name === 'Contacts') { title = 'Contactos'; tabBarLabel = 'Contactos'; headerBg = '#fff'; }
        else if (route.name === 'Scan') { title = 'Escanear'; tabBarLabel = 'Escanear'; }
        else if (route.name === 'Exchange') { title = 'Intercambio P2P'; tabBarLabel = 'Intercambio'; headerBg = '#fff'; }
        else if (route.name === 'Profile') { title = 'Mi Perfil'; tabBarLabel = 'Perfil'; headerBg = '#34d399'; }
        return {
          header: () => (
            <Header
              navigation={navigation}
              isHomeScreen={isHomeScreen}
              title={title}
              onProfilePress={() => {}}
              onNotificationPress={() => {}}
              backgroundColor={headerBg}
              showBackButton={false}
              isLight={route.name === 'Profile'}
            />
          ),
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
    backgroundColor: '#34d399', // Emerald color
    width: 56,
    height: 56,
    borderRadius: 28,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: -30,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.25,
    shadowRadius: 3.84,
    elevation: 5,
  },
}); 