import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { BottomTabNavigator } from './BottomTabNavigator';
import LegalDocumentScreen from '../screens/LegalDocumentScreen';
import VerificationScreen from '../screens/VerificationScreen';
import { ConfioAddressScreen } from '../screens/ConfioAddressScreen';
import { AccountDetailScreen } from '../screens/AccountDetailScreen';
import DepositScreen from '../screens/DepositScreen';
import USDCManageScreen from '../screens/USDCManageScreen';
import { SendScreen } from '../screens/SendScreen';
import { TransactionDetailScreen } from '../screens/TransactionDetailScreen';

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
      <Stack.Screen 
        name="AccountDetail" 
        component={AccountDetailScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="USDCDeposit" 
        component={DepositScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen
        name="USDCManage"
        component={USDCManageScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="Send"
        component={SendScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="TransactionDetail"
        component={TransactionDetailScreen}
        options={{ headerShown: false }}
      />
    </Stack.Navigator>
  );
}; 