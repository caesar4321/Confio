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
import { USDCWithdrawScreen } from '../screens/USDCWithdrawScreen';
import { USDCHistoryScreen } from '../screens/USDCHistoryScreen';
import { USDCConversionScreen } from '../screens/USDCConversionScreen';
import { SendWithAddressScreen } from '../screens/SendWithAddressScreen';
import { SendToFriendScreen } from '../screens/SendToFriendScreen';
import { TransactionDetailScreen } from '../screens/TransactionDetailScreen';
import { TransactionProcessingScreen } from '../screens/TransactionProcessingScreen';
import { TransactionSuccessScreen } from '../screens/TransactionSuccessScreen';
import { PaymentConfirmationScreen } from '../screens/PaymentConfirmationScreen';
import { PaymentProcessingScreen } from '../screens/PaymentProcessingScreen';
import { PaymentSuccessScreen } from '../screens/PaymentSuccessScreen';
import { BusinessPaymentSuccessScreen } from '../screens/BusinessPaymentSuccessScreen';
import { TraderProfileScreen } from '../screens/TraderProfileScreen';
import { TradeConfirmScreen } from '../screens/TradeConfirmScreen';
import { TradeChatScreen } from '../screens/TradeChatScreen';
import { ActiveTradeScreen } from '../screens/ActiveTradeScreen';
import { TraderRatingScreen } from '../screens/TraderRatingScreen';
import { ScanScreen } from '../screens/ScanScreen';
import { CreateOfferScreen } from '../screens/CreateOfferScreen';
import { BankInfoScreen } from '../screens/BankInfoScreen';
import { AchievementsScreen } from '../screens/AchievementsScreen';
import { ConfioTokenInfoScreen } from '../screens/ConfioTokenInfoScreen';
import { PushNotificationModal } from '../components/PushNotificationModal';
import { usePushNotificationPrompt } from '../hooks/usePushNotificationPrompt';

console.log('MainNavigator: TransactionProcessingScreen imported:', !!TransactionProcessingScreen);
console.log('MainNavigator: TransactionSuccessScreen imported:', !!TransactionSuccessScreen);

const Stack = createNativeStackNavigator<MainStackParamList>();

export const MainNavigator = () => {
  console.log('MainNavigator: Component rendering');
  
  // Hook for push notification prompt
  const { showModal, handleAllow, handleDeny } = usePushNotificationPrompt();
  
  return (
    <>
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
        name="BankInfo" 
        component={BankInfoScreen}
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
        name="USDCWithdraw"
        component={USDCWithdrawScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="USDCHistory"
        component={USDCHistoryScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="USDCConversion"
        component={USDCConversionScreen}
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
        name="PaymentConfirmation"
        component={PaymentConfirmationScreen}
        options={{ 
          headerShown: false,
          animation: 'slide_from_bottom'
        }}
      />
      <Stack.Screen
        name="PaymentProcessing"
        component={PaymentProcessingScreen}
        options={{ 
          headerShown: false,
          gestureEnabled: false, // Prevent back gesture
          animation: 'slide_from_right',
          presentation: 'modal' // Ensure it's treated as a modal
        }}
        listeners={{
          focus: () => console.log('MainNavigator: PaymentProcessing screen focused'),
          beforeRemove: (e) => {
            console.log('MainNavigator: PaymentProcessing screen being removed');
          }
        }}
      />
      <Stack.Screen
        name="PaymentSuccess"
        component={PaymentSuccessScreen}
        options={{ 
          headerShown: false,
          gestureEnabled: false, // Prevent back gesture
          animation: 'slide_from_right'
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
      <Stack.Screen
        name="BusinessPaymentSuccess"
        component={BusinessPaymentSuccessScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="Scan"
        component={ScanScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="CreateOffer"
        component={CreateOfferScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="Achievements"
        component={AchievementsScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="ConfioTokenInfo"
        component={ConfioTokenInfoScreen}
        options={{ headerShown: false }}
      />
    </Stack.Navigator>
      
      {/* Push Notification Permission Modal */}
      <PushNotificationModal
        visible={showModal}
        onAllow={handleAllow}
        onDeny={handleDeny}
      />
    </>
  );
}; 