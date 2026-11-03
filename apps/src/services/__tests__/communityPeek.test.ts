import { AppState } from 'react-native';

const mockQuery = jest.fn();
jest.mock('../../apollo/client', () => ({ apolloClient: { query: (...args: unknown[]) => mockQuery(...args) } }));
jest.mock('react-native-keychain', () => ({
  getInternetCredentials: jest.fn(async () => null),
  setInternetCredentials: jest.fn(async () => true),
}));

const FIVE_MIN = 5 * 60 * 1000;
const flush = async () => { for (let i = 0; i < 10; i += 1) await Promise.resolve(); };

let appStateListener: ((s: string) => void) | null = null;

beforeEach(() => {
  jest.useFakeTimers();
  mockQuery.mockReset();
  mockQuery.mockResolvedValue({ data: { discoverFeed: { items: [] } } });
  (AppState as { currentState: string }).currentState = 'active';
  jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
    appStateListener = listener as (s: string) => void;
    return { remove: jest.fn() } as never;
  });
});

afterEach(() => jest.useRealTimers());

test('an app left open keeps looking for new posts, and stops in the background', async () => {
  const { watchCommunityPeek } = require('../communityPeek');
  const stop = watchCommunityPeek();
  await flush();
  expect(mockQuery).toHaveBeenCalledTimes(1);

  await jest.advanceTimersByTimeAsync(FIVE_MIN);
  await flush();
  expect(mockQuery).toHaveBeenCalledTimes(2);

  appStateListener?.('background');
  await jest.advanceTimersByTimeAsync(3 * FIVE_MIN);
  await flush();
  expect(mockQuery).toHaveBeenCalledTimes(2);

  // Back in front: looks again at once, then keeps polling.
  appStateListener?.('active');
  await flush();
  expect(mockQuery).toHaveBeenCalledTimes(3);
  await jest.advanceTimersByTimeAsync(FIVE_MIN);
  await flush();
  expect(mockQuery).toHaveBeenCalledTimes(4);

  stop();
  await jest.advanceTimersByTimeAsync(3 * FIVE_MIN);
  expect(mockQuery).toHaveBeenCalledTimes(4);
});

test('only the posts Comunidad shows are marked seen; one it has not loaded keeps its badge', async () => {
  jest.resetModules();
  const React = require('react');
  const renderer = require('react-test-renderer');
  const peek = require('../communityPeek');
  const at = (h: number) => new Date(Date.UTC(2026, 10, 3, h)).toISOString();
  const post = (id: number, h: number) => ({ id: String(id), title: '', body: '', time: '', publishedAt: at(h) });
  let current: any = null;
  const Probe = () => { current = peek.useCommunityPeek(); return null; };
  renderer.act(() => { renderer.create(React.createElement(Probe)); });

  mockQuery.mockResolvedValue({ data: { discoverFeed: { items: [post(1, 10)] } } });
  await renderer.act(async () => { await peek.refreshCommunityPeek(); });
  await renderer.act(async () => { await peek.markCommunitySeen([{ id: '1', publishedAt: at(10) }]); });
  expect(current.unread).toBe(0);

  // A poll finds two newer posts; the feed on screen has loaded only one.
  mockQuery.mockResolvedValue({ data: { discoverFeed: { items: [post(3, 12), post(2, 11), post(1, 10)] } } });
  await renderer.act(async () => { await peek.refreshCommunityPeek(); });
  expect(current.unread).toBe(2);
  await renderer.act(async () => { await peek.markCommunitySeen([{ id: '2', publishedAt: at(11) }, { id: '1', publishedAt: at(10) }]); });
  expect(current.unread).toBe(1);
});
