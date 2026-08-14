const mockMessagingInstance = {
  hasPermission: jest.fn(),
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

jest.mock('../../navigation/RootNavigation', () => ({ navigationRef: { current: null } }));
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

describe('MessagingService FCM registration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockMessagingInstance.hasPermission.mockResolvedValue(1);
    mockMessagingInstance.getToken.mockResolvedValue('same-fcm-token');
    mockGetInternetCredentials.mockImplementation((service: string) => Promise.resolve(
      service === 'confio_device_id'
        ? { username: 'device_id', password: 'device-1' }
        : { username: 'fcm_token', password: 'same-fcm-token' }
    ));
    mockSetInternetCredentials.mockResolvedValue(true);
    mockMutate.mockResolvedValue({
      data: { registerFcmToken: { success: true } },
    });
    (messagingService as any).deviceId = 'device-1';
    (messagingService as any).messageHandlersSetup = true;
    (messagingService as any).channelCreated = true;
    (messagingService as any).registrationInFlight = null;
  });

  it('re-registers an unchanged token when forced', async () => {
    await messagingService.initialize(true);

    expect(mockMutate).toHaveBeenCalledTimes(1);
    expect(mockSetInternetCredentials).toHaveBeenCalledWith(
      'confio_fcm_token',
      'fcm_token',
      'same-fcm-token'
    );
  });

  it('does not persist or report success when the server registration fails', async () => {
    mockMutate.mockRejectedValueOnce(new Error('network unavailable'));

    const registered = await messagingService.ensureTokenRegisteredForCurrentUser();

    expect(registered).toBe(false);
    expect(mockSetInternetCredentials).not.toHaveBeenCalledWith(
      'confio_fcm_token',
      'fcm_token',
      'same-fcm-token'
    );
    expect(mockRecordCrashError).toHaveBeenCalledWith(expect.any(Error));
  });

  it('treats a missing success confirmation as a failed registration', async () => {
    mockMutate.mockResolvedValueOnce({
      data: { registerFcmToken: { success: false } },
    });

    const registered = await messagingService.ensureTokenRegisteredForCurrentUser();

    expect(registered).toBe(false);
    expect(mockSetInternetCredentials).not.toHaveBeenCalledWith(
      'confio_fcm_token',
      'fcm_token',
      'same-fcm-token'
    );
    expect(mockRecordCrashError).toHaveBeenCalledWith(expect.any(Error));
  });

  it('deduplicates concurrent registration attempts for the same device token', async () => {
    let resolveRegistration: (value: unknown) => void = () => undefined;
    let markRegistrationStarted: () => void = () => undefined;
    const registrationStarted = new Promise<void>(resolve => {
      markRegistrationStarted = resolve;
    });
    mockMutate.mockImplementationOnce(() => new Promise(resolve => {
      markRegistrationStarted();
      resolveRegistration = resolve;
    }));

    const firstRegistration = messagingService.ensureTokenRegisteredForCurrentUser();
    const secondRegistration = messagingService.ensureTokenRegisteredForCurrentUser();
    await registrationStarted;

    expect(mockMutate).toHaveBeenCalledTimes(1);
    resolveRegistration({ data: { registerFcmToken: { success: true } } });

    await expect(Promise.all([firstRegistration, secondRegistration])).resolves.toEqual([true, true]);
    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  it('serializes different tokens so the newer registration finishes last', async () => {
    let resolveOldRegistration: (value: unknown) => void = () => undefined;
    let markOldRegistrationStarted: () => void = () => undefined;
    const oldRegistrationStarted = new Promise<void>(resolve => {
      markOldRegistrationStarted = resolve;
    });
    mockMutate
      .mockImplementationOnce(() => new Promise(resolve => {
        markOldRegistrationStarted();
        resolveOldRegistration = resolve;
      }))
      .mockResolvedValueOnce({ data: { registerFcmToken: { success: true } } });

    const oldRegistration = (messagingService as any).registerToken('old-token');
    const newRegistration = (messagingService as any).registerToken('new-token');
    await oldRegistrationStarted;

    expect(mockMutate).toHaveBeenCalledTimes(1);
    resolveOldRegistration({ data: { registerFcmToken: { success: true } } });
    await Promise.all([oldRegistration, newRegistration]);

    expect(mockMutate).toHaveBeenCalledTimes(2);
    expect(mockMutate.mock.calls.map(call => call[0].variables.token)).toEqual([
      'old-token',
      'new-token',
    ]);
  });
});
