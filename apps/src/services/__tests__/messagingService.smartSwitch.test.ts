// A Cuenta inteligente notification never opens over a business context.
const mockMessagingInstance = {
  hasPermission: jest.fn(),
  isDeviceRegisteredForRemoteMessages: true,
  registerDeviceForRemoteMessages: jest.fn(),
  getAPNSToken: jest.fn(),
  getToken: jest.fn(),
  onMessage: jest.fn(() => jest.fn()),
  onNotificationOpenedApp: jest.fn(() => jest.fn()),
  getInitialNotification: jest.fn(() => Promise.resolve(null)),
  onTokenRefresh: jest.fn(() => jest.fn()),
};

const mockMutate = jest.fn();
const mockGetInternetCredentials = jest.fn();
const mockSetInternetCredentials = jest.fn();
const mockRecordCrashError = jest.fn();

jest.mock('@react-native-firebase/messaging', () => {
  const messaging = () => mockMessagingInstance;
  messaging.AuthorizationStatus = {
    AUTHORIZED: 1,
    PROVISIONAL: 2,
  };
  return {
    __esModule: true,
    default: messaging,
    getMessaging: messaging,
    AuthorizationStatus: messaging.AuthorizationStatus,
    isDeviceRegisteredForRemoteMessages: () => mockMessagingInstance.isDeviceRegisteredForRemoteMessages,
    hasPermission: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.hasPermission as jest.Mock)(...args),
    registerDeviceForRemoteMessages: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.registerDeviceForRemoteMessages as jest.Mock)(...args),
    getAPNSToken: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.getAPNSToken as jest.Mock)(...args),
    getToken: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.getToken as jest.Mock)(...args),
    onMessage: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.onMessage as jest.Mock)(...args),
    onNotificationOpenedApp: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.onNotificationOpenedApp as jest.Mock)(...args),
    getInitialNotification: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.getInitialNotification as jest.Mock)(...args),
    onTokenRefresh: (_instance: unknown, ...args: unknown[]) => (mockMessagingInstance.onTokenRefresh as jest.Mock)(...args),

  };
});

jest.mock('@notifee/react-native', () => ({
  __esModule: true,
  default: {
    requestPermission: jest.fn(),
    onForegroundEvent: jest.fn(),
    getInitialNotification: jest.fn(() => Promise.resolve(null)),
    createChannel: jest.fn(),
  },
  AndroidImportance: { HIGH: 4 },
  AndroidStyle: {},
  EventType: { PRESS: 1 },
}));

jest.mock('react-native-keychain', () => ({
  __esModule: true,
  getInternetCredentials: (...args: unknown[]) => mockGetInternetCredentials(...args),
  setInternetCredentials: (...args: unknown[]) => mockSetInternetCredentials(...args),
  resetInternetCredentials: jest.fn(),
}));

jest.mock('react-native-device-info', () => ({
  __esModule: true,
  default: {
    getUniqueId: jest.fn(() => Promise.resolve('device-1')),
    getDeviceName: jest.fn(() => Promise.resolve('Test Device')),
    getVersion: jest.fn(() => '4.5.2'),
  },
}));

jest.mock('../../apollo/client', () => ({
  __esModule: true,
  apolloClient: { mutate: (...args: unknown[]) => mockMutate(...args) },
}));

const mockNavigate = jest.fn();
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: {
    current: {
      isReady: () => true,
      navigate: (...a: unknown[]) => mockNavigate(...a),
      getRootState: () => ({ routes: [{ name: 'Main' }], index: 0 }),
      getCurrentRoute: () => ({ name: 'Home' }),
    },
  },
}));
const mockContext = jest.fn();
jest.mock('../authService', () => ({
  AuthService: jest.fn().mockImplementation(() => ({ getActiveAccountContext: () => mockContext() })),
}));
jest.mock('../pushNotificationService', () => ({
  PushNotificationService: { pendingAccountSwitchGlobal: null, pendingNavigationAfterSwitch: null },
}));
jest.mock('../notificationDeduplication', () => ({
  __esModule: true,
  default: { isDuplicate: jest.fn(() => false) },
}));
jest.mock('../crashLog', () => ({
  describeTypes: jest.fn(() => ''),
  logBreadcrumb: jest.fn(),
  recordCrashError: (...args: unknown[]) => mockRecordCrashError(...args),
}));

import messagingService from '../messagingService';
import { PushNotificationService } from '../pushNotificationService';

const pending = PushNotificationService as any;
const handle = (data: any) => (messagingService as any).handleNotificationData(data, false);

describe('Cuenta inteligente notification from another context', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    pending.pendingAccountSwitchGlobal = null;
    pending.pendingNavigationAfterSwitch = null;
    jest.spyOn(messagingService as any, 'canNavigateIntoMain').mockReturnValue(true);
  });

  it('switches a business owner or employee to personal_0 before opening the screen', async () => {
    mockContext.mockResolvedValue({ type: 'business', index: 0, businessId: '19' });
    await handle({ route: 'SmartAccountBilling', account_context: 'personal' });
    expect(pending.pendingAccountSwitchGlobal).toBe('personal_0');
    expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Home' } });
    expect(mockNavigate).not.toHaveBeenCalledWith('Main', expect.objectContaining({ screen: 'SmartAccountBilling' }));
    // After the switch the deferred navigation opens the smart screen.
    pending.pendingNavigationAfterSwitch();
    await new Promise((r) => setTimeout(r, 0));
    expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'SmartAccountBilling', params: undefined });
  });

  it('switches even when the push carries no account_context', async () => {
    mockContext.mockResolvedValue({ type: 'business', index: 0, businessId: '19' });
    await handle({ data_screen: 'BeneficiaryInvite', data_designationId: 'd1' });
    expect(pending.pendingAccountSwitchGlobal).toBe('personal_0');
  });

  it('opens directly from the personal context', async () => {
    mockContext.mockResolvedValue({ type: 'personal', index: 0 });
    await handle({ route: 'SmartAccountBilling', account_context: 'personal' });
    expect(pending.pendingAccountSwitchGlobal).toBeNull();
    expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'SmartAccountBilling', params: undefined });
  });
});
