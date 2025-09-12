import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { AuthStackParamList } from '../types/navigation';
import { AuthScreen } from '../screens/AuthScreen';
import PhoneVerificationScreen from '../screens/PhoneVerificationScreen';
import LegalDocumentScreen from '../screens/LegalDocumentScreen';

const Stack = createNativeStackNavigator<AuthStackParamList>();

export const AuthNavigator = () => {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        animation: 'none'
      }}
    >
      <Stack.Screen name="Login" component={AuthScreen} />
      <Stack.Screen name="PhoneVerification" component={PhoneVerificationScreen} />
      <Stack.Screen 
        name="LegalDocument" 
        component={LegalDocumentScreen}
        options={{ headerShown: false }}
      />
    </Stack.Navigator>
  );
};
