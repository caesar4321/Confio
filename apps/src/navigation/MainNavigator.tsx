import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { BottomTabNavigator } from './BottomTabNavigator';
import LegalDocumentScreen from '../screens/LegalDocumentScreen';
import VerificationScreen from '../screens/VerificationScreen';
import { ConfioAddressScreen } from '../screens/ConfioAddressScreen';
import { NotificationScreen } from '../screens/NotificationScreen';
import { CreateBusinessScreen } from '../screens/CreateBusinessScreen';
import { EditBusinessScreen } from '../screens/EditBusinessScreen';
import { EditProfileScreen } from '../screens/EditProfileScreen';
import PhoneVerificationScreen from '../screens/PhoneVerificationScreen';
import { AccountDetailScreen } from '../screens/AccountDetailScreen';
import DepositScreen from '../screens/DepositScreen';
import USDCManageScreen from '../screens/USDCManageScreen';
import { SendWithAddressScreen } from '../screens/SendWithAddressScreen';
import { SendToFriendScreen } from '../screens/SendToFriendScreen';
import { TransactionDetailScreen } from '../screens/TransactionDetailScreen';
import { TransactionProcessingScreen } from '../screens/TransactionProcessingScreen';
import { TransactionSuccessScreen } from '../screens/TransactionSuccessScreen';
import { TraderProfileScreen } from '../screens/TraderProfileScreen';
import { TradeConfirmScreen } from '../screens/TradeConfirmScreen';
import { TradeChatScreen } from '../screens/TradeChatScreen';
import { ActiveTradeScreen } from '../screens/ActiveTradeScreen';
import { TraderRatingScreen } from '../screens/TraderRatingScreen';

console.log('MainNavigator: TransactionProcessingScreen imported:', !!TransactionProcessingScreen);
console.log('MainNavigator: TransactionSuccessScreen imported:', !!TransactionSuccessScreen);

const Stack = createNativeStackNavigator<MainStackParamList>();

export const MainNavigator = () => {
  console.log('MainNavigator: Component rendering');
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
        name="Notification" 
        component={NotificationScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="CreateBusiness" 
        component={CreateBusinessScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="EditBusiness" 
        component={EditBusinessScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="EditProfile" 
        component={EditProfileScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="PhoneVerification" 
        component={PhoneVerificationScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="TraderProfile" 
        component={TraderProfileScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="TradeConfirm" 
        component={TradeConfirmScreen}
        options={{
          headerShown: false,
        }}
      />
      <Stack.Screen 
        name="TradeChat" 
        component={TradeChatScreen}
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
        name="SendWithAddress"
        component={SendWithAddressScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="SendToFriend"
        component={SendToFriendScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="TransactionDetail"
        component={TransactionDetailScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="TransactionProcessing"
        component={TransactionProcessingScreen}
        options={{ 
          headerShown: false,
          gestureEnabled: false, // Prevent back gesture
          animation: 'slide_from_right'
        }}
        listeners={{
          focus: () => console.log('MainNavigator: TransactionProcessing screen focused'),
        }}
      />
      <Stack.Screen
        name="TransactionSuccess"
        component={TransactionSuccessScreen}
        options={{ 
          headerShown: false,
          gestureEnabled: false, // Prevent back gesture
          animation: 'slide_from_right'
        }}
        listeners={{
          focus: () => console.log('MainNavigator: TransactionSuccess screen focused'),
        }}
      />
      <Stack.Screen
        name="ActiveTrade"
        component={ActiveTradeScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="TraderRating"
        component={TraderRatingScreen}
        options={{ headerShown: false }}
      />
    </Stack.Navigator>
  );
}; 