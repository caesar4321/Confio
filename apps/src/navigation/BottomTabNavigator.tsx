import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import Icon from 'react-native-vector-icons/Feather';
import { HomeScreen } from '../screens/HomeScreen';
import { ContactsScreen } from '../screens/ContactsScreen';
import { ScanScreen } from '../screens/ScanScreen';
import { ExchangeScreen } from '../screens/ExchangeScreen';
import { ProfileScreen } from '../screens/ProfileScreen';
import { Header } from './Header';

const Tab = createBottomTabNavigator();

export const BottomTabNavigator = () => {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => {
        // Determine if this is the Home screen
        const isHomeScreen = route.name === 'Home';
        // Set the title and label based on the route
        let title = 'Confío';
        let tabBarLabel = '';
        if (route.name === 'Home') { title = 'Confío'; tabBarLabel = 'Inicio'; }
        else if (route.name === 'Contacts') { title = 'Contactos'; tabBarLabel = 'Contactos'; }
        else if (route.name === 'Scan') { title = 'Escanear'; tabBarLabel = 'Escanear'; }
        else if (route.name === 'Exchange') { title = 'Intercambio P2P'; tabBarLabel = 'Intercambio'; }
        else if (route.name === 'Profile') { title = 'Mi Perfil'; tabBarLabel = 'Perfil'; }
        return {
          header: () => (
            <Header
              isHomeScreen={isHomeScreen}
              title={title}
              onProfilePress={() => {}}
              onNotificationPress={() => {}}
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
        };
      }}
    >
      <Tab.Screen
        name="Home"
        component={HomeScreen}
        options={{
          tabBarIcon: ({ color, size }) => (
            <Icon name="home" size={size} color={color} />
          ),
          tabBarLabel: 'Inicio',
        }}
      />
      <Tab.Screen
        name="Contacts"
        component={ContactsScreen}
        options={{
          tabBarIcon: ({ color, size }) => (
            <Icon name="users" size={size} color={color} />
          ),
          tabBarLabel: 'Contactos',
        }}
      />
      <Tab.Screen
        name="Scan"
        component={ScanScreen}
        options={{
          tabBarIcon: ({ color, size }) => (
            <Icon name="maximize" size={size} color={color} />
          ),
          tabBarLabel: 'Escanear',
        }}
      />
      <Tab.Screen
        name="Exchange"
        component={ExchangeScreen}
        options={{
          tabBarIcon: ({ color, size }) => (
            <Icon name="repeat" size={size} color={color} />
          ),
          tabBarLabel: 'Intercambio',
        }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{
          tabBarIcon: ({ color, size }) => (
            <Icon name="user" size={size} color={color} />
          ),
          tabBarLabel: 'Perfil',
        }}
      />
    </Tab.Navigator>
  );
}; 