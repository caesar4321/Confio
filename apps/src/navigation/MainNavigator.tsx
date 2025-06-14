import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { BottomTabNavigator } from './BottomTabNavigator';
import LegalDocumentScreen from '../screens/LegalDocumentScreen';
import VerificationScreen from '../screens/VerificationScreen';
import { ConfioAddressScreen } from '../screens/ConfioAddressScreen';

const Stack = createNativeStackNavigator<MainStackParamList>();

export const MainNavigator = () => {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        animation: 'none',
        presentation: 'transparentModal'
      }}
    >
      <Stack.Screen name="BottomTabs" component={BottomTabNavigator} />
      <Stack.Screen 
        name="LegalDocument" 
        component={LegalDocumentScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="Verification" 
        component={VerificationScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="ConfioAddress" 
        component={ConfioAddressScreen}
        options={{
          headerShown: false,
        }}
      />
    </Stack.Navigator>
  );
}; 