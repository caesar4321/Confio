// A Cuenta inteligente push tapped while a business context is active
// switches to the person first (the deferred HomeScreen switch), then opens.
jest.mock('@react-native-firebase/messaging', () => ({}));
jest.mock('@notifee/react-native', () => ({ __esModule: true, default: {} }));
jest.mock('react-native-keychain', () => ({}));
jest.mock('../crashLog', () => ({ describeTypes: jest.fn(() => ''), logBreadcrumb: jest.fn(), recordCrashError: jest.fn() }));
jest.mock('../localTransferNavigation', () => ({ localTransferRoute: () => null }));
jest.mock('../notificationOpenStore', () => ({}));
const mockNavigate = jest.fn();
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { isReady: () => true, navigate: (...a: unknown[]) => mockNavigate(...a) },
  navigate: jest.fn(),
}));
const mockContext = jest.fn();
jest.mock('../authService', () => ({
  AuthService: jest.fn().mockImplementation(() => ({ getActiveAccountContext: () => mockContext() })),
}));

import { PushNotificationService } from '../pushNotificationService';

const service = PushNotificationService.getInstance() as any;
const open = (data: Record<string, string>) => service.handleNotificationNavigation({ data });

beforeEach(() => {
  jest.clearAllMocks();
  PushNotificationService.clearPendingAccountSwitch();
  PushNotificationService.clearPendingNavigation();
});

it('switches a business context to personal_0, then opens the smart screen', async () => {
  mockContext.mockResolvedValue({ type: 'business', index: 0, businessId: '19' });
  await open({ data_route: 'SmartAccountBilling', account_context: 'personal' });
  expect(PushNotificationService.getPendingAccountSwitch()).toBe('personal_0');
  expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Home' } });
  PushNotificationService.getPendingNavigation()!();
  expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'SmartAccountBilling', params: undefined });
});

it('switches without an account_context too', async () => {
  mockContext.mockResolvedValue({ type: 'business', index: 0, businessId: '19' });
  await open({ data_screen: 'InheritedAccount', data_inheritedAccountId: 'i7' });
  expect(PushNotificationService.getPendingAccountSwitch()).toBe('personal_0');
});

it('opens straight away from the smart context', async () => {
  mockContext.mockResolvedValue({ type: 'smart', index: 0 });
  await open({ data_route: 'SmartAccountRules', account_context: 'personal' });
  expect(PushNotificationService.getPendingAccountSwitch()).toBeNull();
  expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'SmartAccountRules', params: undefined });
});

it('the in-app list uses the same deferred switch', () => {
  const go = jest.fn();
  PushNotificationService.deferSwitchThenNavigate('personal_0', go);
  expect(PushNotificationService.getPendingAccountSwitch()).toBe('personal_0');
  expect(PushNotificationService.getPendingNavigation()).toBe(go);
  expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Home' } });
});
