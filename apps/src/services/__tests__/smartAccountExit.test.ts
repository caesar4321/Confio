import {
  MIN_VISIT_MS, SMART_ACCOUNT_EXIT_REASONS, requestSmartAccountExitQuestion, resetSmartAccountExitForTests,
  smartAccountExitReasons, subscribeSmartAccountExitQuestion,
} from '../smartAccountExit';

const memory = (at = 0) => {
  let stored = at;
  return { read: async () => stored, write: async (v: number) => { stored = v; }, get: () => stored };
};

beforeEach(() => resetSmartAccountExitForTests(memory()));

it('offers "Me falta verificarme" only to someone told to verify, and "Otra cosa" last', () => {
  const plain = smartAccountExitReasons(false).map(([id]) => id);
  expect(plain).not.toContain('verify');
  expect(plain[plain.length - 1]).toBe('other');
  expect(smartAccountExitReasons(true).map(([id]) => id)).toContain('verify');
  expect(new Set(smartAccountExitReasons(true).map(([id]) => id))).toEqual(new Set(SMART_ACCOUNT_EXIT_REASONS.map(([id]) => id)));
});

it('asks at most once a week per device', async () => {
  const store = memory();
  resetSmartAccountExitForTests(store);
  const asks: unknown[] = [];
  subscribeSmartAccountExitQuestion((ask) => asks.push(ask));
  const now = Date.now();
  await expect(requestSmartAccountExitQuestion(false, 'annual', now)).resolves.toBe(true);
  await expect(requestSmartAccountExitQuestion(false, 'annual', now + 60_000)).resolves.toBe(false);
  await expect(requestSmartAccountExitQuestion(false, null, now + 8 * 24 * 3600 * 1000)).resolves.toBe(true);
  expect(asks).toHaveLength(2);
  expect(store.get()).toBe(now + 8 * 24 * 3600 * 1000);
});

it('never asks with no host mounted', async () => {
  await expect(requestSmartAccountExitQuestion(false, null)).resolves.toBe(false);
});

it('a quick look is not asked about', () => {
  expect(MIN_VISIT_MS).toBeGreaterThanOrEqual(3000);
});
