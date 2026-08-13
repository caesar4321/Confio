const mockGetInitialURL = jest.fn();
const mockAddEventListener = jest.fn();
const mockGetInternetCredentials = jest.fn();
const mockSetInternetCredentials = jest.fn();
const mockGetInstallReferrerInfo = jest.fn();
let linkListener: ((event: { url: string }) => void) | undefined;
let storedPassword: string | null;

jest.mock('react-native', () => ({
  Linking: {
    getInitialURL: (...args: unknown[]) => mockGetInitialURL(...args),
    addEventListener: (...args: unknown[]) => mockAddEventListener(...args),
  },
  Platform: { OS: 'android' },
}));

jest.mock('react-native-keychain', () => ({
  getInternetCredentials: (...args: unknown[]) => mockGetInternetCredentials(...args),
  setInternetCredentials: (...args: unknown[]) => mockSetInternetCredentials(...args),
}));

jest.mock('react-native-play-install-referrer', () => ({
  PlayInstallReferrer: {
    getInstallReferrerInfo: (...args: unknown[]) => mockGetInstallReferrerInfo(...args),
  },
}));

jest.mock('react-native-url-polyfill/auto', () => ({}));

import { DeepLinkHandler } from '../deepLinkHandler';

describe('DeepLinkHandler referral attribution', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    storedPassword = null;
    mockGetInternetCredentials.mockImplementation(async () => storedPassword === null ? false : ({
      username: 'deferred_link',
      password: storedPassword,
    }));
    mockSetInternetCredentials.mockImplementation(async (_service, _username, password) => {
      storedPassword = password;
    });
    mockAddEventListener.mockImplementation((_event, listener) => {
      linkListener = listener;
      return { remove: jest.fn() };
    });
    linkListener = undefined;
  });

  it('runs install-referrer capture once and keeps the referral for HomeScreen', async () => {
    mockGetInitialURL.mockResolvedValue(null);
    mockGetInstallReferrerInfo.mockImplementation((callback) => callback({
      installReferrer: 'referral_code=WILBERHL&utm_content=WILBERHL&click_id=click-1&channel=whatsapp',
    }, null));

    const handler = new DeepLinkHandler();
    await Promise.all([handler.init(), handler.init()]);

    expect(mockGetInstallReferrerInfo).toHaveBeenCalledTimes(1);
    expect(mockSetInternetCredentials).toHaveBeenCalledTimes(1);
    expect(JSON.parse(mockSetInternetCredentials.mock.calls[0][2])).toMatchObject({
      type: 'referral',
      payload: 'WILBERHL',
      metadata: { clickId: 'click-1', channel: 'whatsapp' },
    });
  });

  it('captures an installed-app /invite link with its click attribution', async () => {
    mockGetInitialURL.mockResolvedValue(
      'https://confio.lat/invite/WILBERHL?click_id=click-2&session_id=session-2&channel=whatsapp',
    );

    const handler = new DeepLinkHandler();
    await handler.init();

    expect(mockGetInstallReferrerInfo).not.toHaveBeenCalled();
    expect(mockSetInternetCredentials).toHaveBeenCalledTimes(1);
    expect(JSON.parse(mockSetInternetCredentials.mock.calls[0][2])).toMatchObject({
      type: 'referral',
      payload: 'WILBERHL',
      metadata: {
        clickId: 'click-2',
        sessionId: 'session-2',
        channel: 'whatsapp',
      },
    });
  });

  it('notifies authenticated consumers when an invite opens in a warm app', async () => {
    mockGetInitialURL.mockResolvedValue(null);

    const handler = new DeepLinkHandler();
    const listener = jest.fn();
    handler.addReferralListener(listener);
    await handler.init();

    linkListener?.({ url: 'https://confio.lat/invite/WILBERHL?channel=whatsapp' });
    await new Promise(resolve => setImmediate(resolve));

    expect(listener).toHaveBeenCalledTimes(1);
    expect(JSON.parse(mockSetInternetCredentials.mock.calls[0][2])).toMatchObject({
      type: 'referral',
      payload: 'WILBERHL',
    });
  });

  it('retries initialization after listener setup fails', async () => {
    mockGetInitialURL.mockResolvedValue(null);
    mockAddEventListener
      .mockImplementationOnce(() => { throw new Error('native listener unavailable'); })
      .mockImplementationOnce((_event, listener) => {
        linkListener = listener;
        return { remove: jest.fn() };
      });

    const handler = new DeepLinkHandler();
    await expect(handler.init()).rejects.toThrow('native listener unavailable');
    await expect(handler.init()).resolves.toBeUndefined();

    expect(mockAddEventListener).toHaveBeenCalledTimes(2);
  });

  it('retries cold-start attribution after secure storage fails', async () => {
    mockGetInitialURL.mockResolvedValue('https://confio.lat/invite/WILBERHL');
    mockSetInternetCredentials
      .mockRejectedValueOnce(new Error('keychain unavailable'))
      .mockImplementation(async (_service, _username, password) => {
        storedPassword = password;
      });

    const handler = new DeepLinkHandler();
    await expect(handler.init()).rejects.toThrow('keychain unavailable');
    await expect(handler.init()).resolves.toBeUndefined();

    expect(JSON.parse(storedPassword!)).toMatchObject({
      type: 'referral',
      payload: 'WILBERHL',
    });
  });

  it('does not let an older referral clear a newer warm-app referral', async () => {
    const older = { type: 'referral', payload: 'FIRST', timestamp: 1 } as const;
    const newer = { type: 'referral', payload: 'SECOND', timestamp: 2 } as const;
    storedPassword = JSON.stringify(newer);

    const handler = new DeepLinkHandler();
    await expect(handler.clearDeferredLink(older)).resolves.toBe(false);

    expect(JSON.parse(storedPassword!)).toEqual(newer);
    expect(mockSetInternetCredentials).not.toHaveBeenCalled();
  });

  it('does not clear a valid deferred referral during navigation readiness checks', async () => {
    const pending = {
      type: 'referral',
      payload: 'WILBERHL',
      timestamp: Date.now(),
    };
    mockGetInitialURL.mockResolvedValue(null);
    storedPassword = JSON.stringify(pending);

    const handler = new DeepLinkHandler();
    await handler.checkDeferredLinks();

    expect(mockSetInternetCredentials).not.toHaveBeenCalled();
  });

  it('clears an expired deferred referral instead of submitting stale attribution', async () => {
    const expired = {
      type: 'referral',
      payload: 'WILBERHL',
      timestamp: Date.now() - (49 * 60 * 60 * 1000),
    };
    mockGetInitialURL.mockResolvedValue(null);
    storedPassword = JSON.stringify(expired);

    const handler = new DeepLinkHandler();
    await handler.init();

    expect(mockSetInternetCredentials).toHaveBeenCalledWith(
      'confio_deferred_link',
      'deferred_link',
      'null',
    );
  });

  it('clears retired influencer attribution instead of retaining it forever', async () => {
    const influencer = {
      type: 'influencer',
      payload: 'legacy-campaign',
      timestamp: Date.now(),
    };
    mockGetInitialURL.mockResolvedValue(null);
    storedPassword = JSON.stringify(influencer);

    const handler = new DeepLinkHandler();
    await handler.init();

    expect(storedPassword).toBe('null');
  });
});
