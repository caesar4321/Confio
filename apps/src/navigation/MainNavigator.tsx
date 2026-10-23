import React, { useEffect } from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { MainStackParamList } from '../types/navigation';
import { BottomTabNavigator } from './BottomTabNavigator';
import { AssistantProvider } from '../assistant/AssistantContext';
import AssistantOverlay from '../assistant/AssistantOverlay';
import { CommunityShareProvider } from '../components/CommunityShareProvider';
import LegalDocumentScreen from '../screens/LegalDocumentScreen';
import VerificationScreen from '../screens/VerificationScreen';
import { ConfioAddressScreen } from '../screens/ConfioAddressScreen';
import { NotificationScreen } from '../screens/NotificationScreen';
import { CreateBusinessScreen } from '../screens/CreateBusinessScreen';
import { EditBusinessScreen } from '../screens/EditBusinessScreen';
import { EditProfileScreen } from '../screens/EditProfileScreen';
import { UpdateUsernameScreen } from '../screens/UpdateUsernameScreen';
import PhoneVerificationScreen from '../screens/PhoneVerificationScreen';
import { AccountDetailScreen } from '../screens/AccountDetailScreen';
import DepositScreen from '../screens/DepositScreen';
import USDCManageScreen from '../screens/USDCManageScreen';
import { USDCHistoryScreen } from '../screens/USDCHistoryScreen';
import { USDCConversionScreen } from '../screens/USDCConversionScreen';
import TopUpScreen from '../screens/TopUpScreen';
import { SellScreen } from '../screens/SellScreen';
import { ConvertSavingsScreen } from '../screens/ConvertSavingsScreen';
import { WithdrawSavingsScreen } from '../screens/WithdrawSavingsScreen';
import { ReceiveSavingsScreen } from '../screens/ReceiveSavingsScreen';
import { SendUsdtScreen } from '../screens/SendUsdtScreen';
import { OndoStocksInfoScreen } from '../screens/OndoStocksInfoScreen';
import { StocksListScreen } from '../screens/StocksListScreen';
import { StockDetailScreen } from '../screens/StockDetailScreen';
import { BuyStockScreen } from '../screens/BuyStockScreen';
import { SellStockScreen } from '../screens/SellStockScreen';
import { CryptoDetailScreen } from '../screens/CryptoDetailScreen';
import { BuyCryptoScreen } from '../screens/BuyCryptoScreen';
import { SellCryptoScreen } from '../screens/SellCryptoScreen';
import { FinancierasScreen } from '../screens/FinancierasScreen';
import { FinancieraDetailScreen } from '../screens/FinancieraDetailScreen';
import { FinancieraReviewScreen } from '../screens/FinancieraReviewScreen';
import { RegisterFinancieraScreen } from '../screens/RegisterFinancieraScreen';
import { MyFinancierasScreen } from '../screens/MyFinancierasScreen';
import RampInstructionsScreen from '../screens/RampInstructionsScreen';
import InfiniaPaymentScreen from '../screens/InfiniaPaymentScreen';
import CobrePaymentScreen from '../screens/CobrePaymentScreen';
import LocalAccountFundingScreen from '../screens/LocalAccountFundingScreen';
import LocalSendScreen from '../screens/LocalSendScreen';
import LocalReceiveScreen from '../screens/LocalReceiveScreen';
import LocalTransferStatusScreen from '../screens/LocalTransferStatusScreen';
import PendingIncomingScreen from '../screens/PendingIncomingScreen';
import LocalLimitIncreaseScreen from '../screens/LocalLimitIncreaseScreen';
import AdditionalDocumentScreen from '../screens/AdditionalDocumentScreen';
import LocalAccountApplicationScreen from '../screens/LocalAccountApplicationScreen';
import ReceiveScreen from '../screens/ReceiveScreen';
import { TransferScreen } from '../screens/TransferScreen';
import { DiscoverEntryScreen } from '../screens/DiscoverEntryScreen';
import EmployeesScreen from '../screens/EmployeesScreen';
import { ReceiveStackHeader, SendStackHeader } from './StackScreenHeaders';
import BrebLocationCheckScreen from '../screens/BrebLocationCheckScreen';
import RampHistoryScreen from '../screens/RampHistoryScreen';

// ... existing imports ...

import { SendWithAddressScreen } from '../screens/SendWithAddressScreen';
import { EmergencyExitScreen } from '../screens/EmergencyExitScreen';
import { BlockedAccountScreen } from '../screens/BlockedAccountScreen';
import { SendToFriendScreen } from '../screens/SendToFriendScreen';
import { FriendDetailScreen } from '../screens/FriendDetailScreen';
import { EmployeeDetailScreen } from '../screens/EmployeeDetailScreen';
import { EmployeeEditScreen } from '../screens/EmployeeEditScreen';
import { PayeeDetailScreen } from '../screens/PayeeDetailScreen';
import PayrollHistoryScreen from '../screens/PayrollHistoryScreen';
import PayrollRunsHistoryScreen from '../screens/PayrollRunsHistoryScreen';
import PayrollRunScreen from '../screens/PayrollRunScreen';
import { TransactionDetailScreen } from '../screens/TransactionDetailScreen';
import { MonthSummaryScreen } from '../screens/MonthSummaryScreen';
import { PaidOfferScreen } from '../screens/PaidOfferScreen';
import { MonthMovementsScreen } from '../screens/MonthMovementsScreen';
import { TransactionProcessingScreen } from '../screens/TransactionProcessingScreen';
import { TransactionSuccessScreen } from '../screens/TransactionSuccessScreen';
import { PaymentConfirmationScreen } from '../screens/PaymentConfirmationScreen';
import { MembershipsScreen } from '../screens/MembershipsScreen';
import { PaymentProcessingScreen } from '../screens/PaymentProcessingScreen';
import { PaymentSuccessScreen } from '../screens/PaymentSuccessScreen';
import { BusinessPaymentSuccessScreen } from '../screens/BusinessPaymentSuccessScreen';
import { TraderProfileScreen } from '../screens/TraderProfileScreen';
import { TradeConfirmScreen } from '../screens/TradeConfirmScreen';
import { TradeChatScreen } from '../screens/TradeChatScreen';
import { ActiveTradeScreen } from '../screens/ActiveTradeScreen';
import { TraderRatingScreen } from '../screens/TraderRatingScreen';
import { ScanScreen } from '../screens/ScanScreen';
import { ChargeScreen } from '../screens/ChargeScreen';
import { CreateOfferScreen } from '../screens/CreateOfferScreen';
import { PayoutMethodsScreen } from '../screens/PayoutMethodsScreen';
import { RampAddressScreen } from '../screens/RampAddressScreen';
import AchievementsScreen from '../screens/AchievementsScreen';
import { ConfioTokenInfoScreen } from '../screens/ConfioTokenInfoScreen';
import { LatamCommunityScreen } from '../screens/LatamCommunityScreen';
import { FundFlowScreen } from '../screens/FundFlowScreen';
import { StocksActivityScreen } from '../screens/StocksActivityScreen';
import { ProtectedSavingsScreen } from '../screens/ProtectedSavingsScreen';
import { HumanitarianAidScreen } from '../screens/HumanitarianAidScreen';
import { ConfioPresaleScreen } from '../screens/ConfioPresaleScreen';
import { ConfioPresaleParticipateScreen } from '../screens/ConfioPresaleParticipateScreen';
import { LoadingOverlay } from '../components/LoadingOverlay';
import { ConfioTokenomicsScreen } from '../screens/ConfioTokenomicsScreen';
import { ReferralFriendJoinedScreen } from '../screens/ReferralFriendJoinedScreen';
import { ReferralActionPromptScreen } from '../screens/ReferralActionPromptScreen';
import { ReferralEventDetailScreen } from '../screens/ReferralEventDetailScreen';
import ReferralRewardClaimScreen from '../screens/ReferralRewardClaimScreen';
import PayrollPendingScreen from '../screens/PayrollPendingScreen';
import PayrollTopUpScreen from '../screens/PayrollTopUpScreen';
import PayrollHomeScreen from '../screens/PayrollHomeScreen';
import PayrollRunDetailScreen from '../screens/PayrollRunDetailScreen';
import TransactionReceiptScreen from '../screens/TransactionReceiptScreen';
import { VerifyTransactionScreen } from '../screens/VerifyTransactionScreen';
import PayrollSetupWizard from '../screens/PayrollSetupWizard';
import PayrollRecipientsManageScreen from '../screens/PayrollRecipientsManageScreen';
import PayrollDelegatesManageScreen from '../screens/PayrollDelegatesManageScreen';
import MessageScreen from '../screens/MessageScreen';
import DiscoverPostDetailScreen from '../screens/DiscoverPostDetailScreen';
import CommunityComposeScreen from '../screens/CommunityComposeScreen';
import MarketProductScreen from '../screens/MarketProductScreen';
import MarketStoreScreen from '../screens/MarketStoreScreen';
import MarketCheckoutScreen from '../screens/MarketCheckoutScreen';
import MarketOrdersScreen from '../screens/MarketOrdersScreen';
import MarketOrderScreen from '../screens/MarketOrderScreen';
import MyMarketStoreScreen from '../screens/MyMarketStoreScreen';
import MarketProductEditScreen from '../screens/MarketProductEditScreen';
import MyCommunityPostsScreen from '../screens/MyCommunityPostsScreen';
import CommunityMemberProfileScreen from '../screens/CommunityMemberProfileScreen';
import DirectInboxScreen from '../screens/DirectInboxScreen';
import DirectChatScreen from '../screens/DirectChatScreen';
import SendTipScreen from '../screens/SendTipScreen';
import LeagueScreen from '../screens/LeagueScreen';
import TeamScreen from '../screens/TeamScreen';
import TeamEditScreen from '../screens/TeamEditScreen';
import TeamsBrowseScreen from '../screens/TeamsBrowseScreen';
import TeamInviteScreen from '../screens/TeamInviteScreen';
import TeamJoinInviteScreen from '../screens/TeamJoinInviteScreen';
import { onTeamInvite, takePendingTeamInvite } from '../services/teamInviteLinks';
import { navigationRef } from './RootNavigation';
import BlockedMembersScreen from '../screens/BlockedMembersScreen';
// import NotificationSettingsScreen from '../screens/NotificationSettingsScreen';

import { MigrationModal } from '../components/MigrationModal';
import { OnboardingModalCoordinator } from '../components/OnboardingModalCoordinator';
import messagingService from '../services/messagingService';
import { pushNotificationService } from '../services/pushNotificationService';
import { deepLinkHandler } from '../utils/deepLinkHandler';
import { usePushNotificationContext } from '../hooks/usePushNotificationContext';
const Stack = createNativeStackNavigator<MainStackParamList>();

export const MainNavigator = () => {
  const { checkAndShowPrompt } = usePushNotificationContext();

  useEffect(() => {
    const timer = setTimeout(() => {
      pushNotificationService.processPendingNotification();
      messagingService.processPendingNotification();
      deepLinkHandler.checkDeferredLinks().catch(() => {});
    }, 250);

    return () => clearTimeout(timer);
  }, []);

  // Team invite links (Invitar a un amigo): shown as soon as the main screens are up.
  useEffect(() => {
    const show = (token: string) => {
      setTimeout(() => (navigationRef as any).navigate('Main', { screen: 'TeamJoinInvite', params: { token } }), 300);
    };
    takePendingTeamInvite().then((waiting) => { if (waiting) show(waiting); }).catch(() => {});
    return onTeamInvite((token) => {
      // Shown now: clear it so the next start doesn't open it again.
      takePendingTeamInvite().catch(() => {});
      show(token);
    });
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      checkAndShowPrompt().catch(() => {});
    }, 1200);

    return () => clearTimeout(timer);
  }, [checkAndShowPrompt]);

  return (
    <AssistantProvider>
      <Stack.Navigator
        screenOptions={{
          headerShown: false,
          animation: 'none',
          detachInactiveScreens: true,
        }}
      >
        <Stack.Screen name="BottomTabs" component={BottomTabNavigator} />
        {/* ... existing screens ... */}
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
          name="PayoutMethods"
          component={PayoutMethodsScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="RampAddress"
          component={RampAddressScreen}
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
          name="HomeMessages"
          component={MessageScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="DiscoverPostDetail"
          component={DiscoverPostDetailScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="CommunityCompose"
          component={CommunityComposeScreen}
          options={{
            headerShown: false,
          }}
        />
        {/* Comprar (marketplace) */}
        <Stack.Screen name="MarketProduct" component={MarketProductScreen} options={{ headerShown: false }} />
        <Stack.Screen name="MarketStore" component={MarketStoreScreen} options={{ headerShown: false }} />
        <Stack.Screen name="MarketCheckout" component={MarketCheckoutScreen} options={{ headerShown: false }} />
        <Stack.Screen name="MarketOrders" component={MarketOrdersScreen} options={{ headerShown: false }} />
        <Stack.Screen name="MarketOrder" component={MarketOrderScreen} options={{ headerShown: false }} />
        <Stack.Screen name="MyMarketStore" component={MyMarketStoreScreen} options={{ headerShown: false }} />
        <Stack.Screen name="MarketProductEdit" component={MarketProductEditScreen} options={{ headerShown: false }} />
        <Stack.Screen
          name="MyCommunityPosts"
          component={MyCommunityPostsScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="CommunityMemberProfile"
          component={CommunityMemberProfileScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="SendTip"
          component={SendTipScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="League"
          component={LeagueScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="Team"
          component={TeamScreen}
          // One screen per team: a team opened from another team's page is its own screen.
          getId={({ params }) => params?.teamId}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="TeamEdit"
          component={TeamEditScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="TeamInvite"
          component={TeamInviteScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="TeamJoinInvite"
          component={TeamJoinInviteScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="TeamsBrowse"
          component={TeamsBrowseScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="DirectInbox"
          component={DirectInboxScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="DirectChat"
          component={DirectChatScreen}
          // One screen per conversation: opening another chat (a push, a
          // profile) never reuses this one's state or sends to its recipient.
          getId={({ params }) => params?.conversationId ?? (params?.userId ? `user-${params.userId}` : undefined)}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="BlockedMembers"
          component={BlockedMembersScreen}
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
          name="UpdateUsername"
          component={UpdateUsernameScreen}
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
          name="TopUp"
          component={TopUpScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="Sell"
          component={SellScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="ConvertSavings"
          component={ConvertSavingsScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen name="InfiniaPayment" component={InfiniaPaymentScreen} options={{ headerShown: false }} />
        <Stack.Screen name="CobrePayment" component={CobrePaymentScreen} options={{ headerShown: false }} />
        <Stack.Screen name="LocalAccountFunding" component={LocalAccountFundingScreen} options={{ headerShown: false }} />
        <Stack.Screen name="LocalSend" component={LocalSendScreen} options={{ headerShown: false }} />
        <Stack.Screen name="LocalReceive" component={LocalReceiveScreen} options={{ headerShown: false }} />
        <Stack.Screen name="Receive" component={ReceiveScreen} options={{ headerShown: true, header: () => <ReceiveStackHeader /> }} />
        {/* Keep legacy Discover links working through the restored tab. */}
        <Stack.Screen name="Send" component={TransferScreen} options={{ headerShown: true, header: () => <SendStackHeader /> }} />
        <Stack.Screen name="Discover" component={DiscoverEntryScreen} />
        <Stack.Screen name="Employees" component={EmployeesScreen} options={{ headerShown: true, title: 'Empleados' }} />
        <Stack.Screen name="LocalTransferStatus" component={LocalTransferStatusScreen} options={{ headerShown: false }} />
        <Stack.Screen name="PendingIncoming" component={PendingIncomingScreen} options={{ headerShown: false }} />
        <Stack.Screen name="LocalLimitIncrease" component={LocalLimitIncreaseScreen} options={{ headerShown: false }} />
        <Stack.Screen name="AdditionalDocument" component={AdditionalDocumentScreen} options={{ headerShown: false }} />
        <Stack.Screen name="LocalAccountApplication" component={LocalAccountApplicationScreen} options={{ headerShown: false }} />
        <Stack.Screen name="BrebLocationCheck" component={BrebLocationCheckScreen} options={{ headerShown: false }} />
        <Stack.Screen
          name="WithdrawSavings"
          component={WithdrawSavingsScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="ReceiveSavings"
          component={ReceiveSavingsScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="SendUsdt"
          component={SendUsdtScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="OndoStocksInfo"
          component={OndoStocksInfoScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="StocksList"
          component={StocksListScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="StockDetail"
          component={StockDetailScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="BuyStock"
          component={BuyStockScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="SellStock"
          component={SellStockScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="CryptoDetail"
          component={CryptoDetailScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="BuyCrypto"
          component={BuyCryptoScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="SellCrypto"
          component={SellCryptoScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="Financieras"
          component={FinancierasScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="FinancieraDetail"
          component={FinancieraDetailScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="FinancieraReview"
          component={FinancieraReviewScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="RegisterFinanciera"
          component={RegisterFinancieraScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="MyFinancieras"
          component={MyFinancierasScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="RampInstructions"
          component={RampInstructionsScreen}
          options={{
            headerShown: false,
          }}
        />
        <Stack.Screen
          name="RampHistory"
          component={RampHistoryScreen}
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
          name="EmergencyExit"
          component={EmergencyExitScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="BlockedAccount"
          component={BlockedAccountScreen}
          options={{ headerShown: false, gestureEnabled: false }}
        />
        <Stack.Screen
          name="SendToFriend"
          component={SendToFriendScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="FriendDetail"
          component={FriendDetailScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="EmployeeDetail"
          component={EmployeeDetailScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="EmployeeEdit"
          component={EmployeeEditScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayeeDetail"
          component={PayeeDetailScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollHistory"
          component={PayrollHistoryScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollRunsHistory"
          component={PayrollRunsHistoryScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollRun"
          component={PayrollRunScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="TransactionDetail"
          component={TransactionDetailScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="MonthSummary"
          component={MonthSummaryScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PaidOffer"
          component={PaidOfferScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="MonthMovements"
          component={MonthMovementsScreen}
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
        />
        <Stack.Screen
          name="TransactionSuccess"
          component={TransactionSuccessScreen}
          options={{
            headerShown: false,
            gestureEnabled: false, // Prevent back gesture
            animation: 'slide_from_right'
          }}
        />
        <Stack.Screen
          name="Memberships"
          component={MembershipsScreen}
          options={{ headerShown: false, animation: 'slide_from_right' }}
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
            animation: 'slide_from_right'
            // NOTE: no `presentation: 'modal'` here. On iOS a modal screen owns its own
            // native container, so every screen pushed above it (PaymentSuccess, and then
            // BottomTabs) renders inset inside the sheet. Back navigation is already
            // blocked by gestureEnabled: false plus the guards in PaymentProcessingScreen.
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
          options={{ headerShown: false, freezeOnBlur: true }}
        />
        <Stack.Screen
          name="Charge"
          component={ChargeScreen}
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
        <Stack.Screen
          name="LatamCommunity"
          component={LatamCommunityScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="FundFlow"
          component={FundFlowScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="StocksActivity"
          component={StocksActivityScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="ProtectedSavings"
          component={ProtectedSavingsScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="HumanitarianAid"
          component={HumanitarianAidScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="ConfioPresale"
          component={ConfioPresaleScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="ConfioPresaleParticipate"
          component={ConfioPresaleParticipateScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="ConfioTokenomics"
          component={ConfioTokenomicsScreen}
          options={{ headerShown: false }}
        />

        <Stack.Screen
          name="ReferralFriendJoined"
          component={ReferralFriendJoinedScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="ReferralActionPrompt"
          component={ReferralActionPromptScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="ReferralEventDetail"
          component={ReferralEventDetailScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="ReferralRewardClaim"
          component={ReferralRewardClaimScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollPending"
          component={PayrollPendingScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollTopUp"
          component={PayrollTopUpScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollHome"
          component={PayrollHomeScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollRunDetail"
          component={PayrollRunDetailScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="TransactionReceipt"
          component={TransactionReceiptScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollReceipt"
          component={TransactionReceiptScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="VerifyTransaction"
          component={VerifyTransactionScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollSetupWizard"
          component={PayrollSetupWizard}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollRecipientsManage"
          component={PayrollRecipientsManageScreen}
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name="PayrollDelegatesManage"
          component={PayrollDelegatesManageScreen}
          options={{ headerShown: false }}
        />
        {/* Notification settings screen is currently hidden from profile navigation.
      <Stack.Screen
        name="NotificationSettings"
        component={NotificationSettingsScreen}
        options={{ headerShown: false }}
      />
      */}
      </Stack.Navigator>
      <AssistantOverlay />
      {/* The one "share to Comunidad" sheet, above every screen (services/communityShare). */}
      <CommunityShareProvider />
      <MigrationModal />
      <OnboardingModalCoordinator />
    </AssistantProvider>
  );
};
