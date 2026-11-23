const mockLogFunnelEvent = jest.fn(async (..._args: unknown[]) => undefined);
let mockConversationHome = false;
jest.mock('../analyticsService', () => ({ AnalyticsService: { logFunnelEvent: (...args: unknown[]) => mockLogFunnelEvent(...args) } }));
jest.mock('../../config/features', () => ({
  get CONVERSATION_HOME_ENABLED() { return mockConversationHome; },
}));

import { logHomeNav, resetHomeNavSeen } from '../homeNavAnalytics';

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  jest.setSystemTime(new Date('2026-11-22T15:00:00Z'));
  mockConversationHome = false;
  resetHomeNavSeen();
});
afterEach(() => jest.useRealTimers());

it('counts a door once per day, however often it is tapped', () => {
  logHomeNav('tabs', 'invest');
  logHomeNav('tabs', 'invest');
  logHomeNav('tabs', 'pay');
  expect(mockLogFunnelEvent.mock.calls).toEqual([
    ['home_nav_tapped', { surface: 'tabs', target: 'invest', home: 'tabs' }],
    ['home_nav_tapped', { surface: 'tabs', target: 'pay', home: 'tabs' }],
  ]);
  // The same door from another surface is another door.
  logHomeNav('home', 'invest');
  expect(mockLogFunnelEvent).toHaveBeenCalledTimes(3);
  // A new day counts again.
  jest.setSystemTime(new Date('2026-11-23T15:00:00Z'));
  logHomeNav('tabs', 'invest');
  expect(mockLogFunnelEvent).toHaveBeenCalledTimes(4);
});

it('says which home the build has', () => {
  mockConversationHome = true;
  logHomeNav('drawer', 'invest');
  expect(mockLogFunnelEvent).toHaveBeenCalledWith('home_nav_tapped', { surface: 'drawer', target: 'invest', home: 'conversation' });
});

it('never throws into the tap that called it', async () => {
  mockLogFunnelEvent.mockRejectedValueOnce(new Error('offline'));
  expect(() => logHomeNav('header', 'menu')).not.toThrow();
  await Promise.resolve();
});
