import {
  MIN_VISIT_MS, SMART_ACCOUNT_EXIT_REASONS, SMART_ACCOUNT_EXIT_TITLE, parseExitQuestion,
  preloadSmartAccountExitQuestion, requestSmartAccountExitQuestion, resetSmartAccountExitForTests,
  smartAccountExitQuestion, subscribeSmartAccountExitQuestion,
} from '../smartAccountExit';

const mockQuery = jest.fn();
jest.mock('../../apollo/client', () => ({ apolloClient: { query: (...args: unknown[]) => mockQuery(...args) } }));

const memory = (at = 0) => {
  let stored = at;
  return { read: async () => stored, write: async (v: number) => { stored = v; }, get: () => stored };
};

beforeEach(() => {
  mockQuery.mockReset();
  resetSmartAccountExitForTests(memory());
});

it('built-in fallback: "Me falta verificarme" only for someone told to verify, "Otra cosa" last', () => {
  const plain = smartAccountExitQuestion(false);
  expect(plain.title).toBe(SMART_ACCOUNT_EXIT_TITLE);
  const ids = plain.reasons.map(([id]) => id);
  expect(ids).not.toContain('verify');
  expect(ids[ids.length - 1]).toBe('other');
  expect(new Set(smartAccountExitQuestion(true).reasons.map(([id]) => id)))
    .toEqual(new Set(SMART_ACCOUNT_EXIT_REASONS.map(([id]) => id)));
});

it('the server decides the title and the answers once read', async () => {
  mockQuery.mockResolvedValueOnce({ data: { smartAccountExitQuestion: {
    title: 'Nueva pregunta', options: [{ key: 'other', label: 'Otra cosa' }, { key: 'money', label: 'Sin dinero' },
      { key: 'BAD KEY', label: 'x' }, { key: 'price', label: '  ' }],
  } } });
  await preloadSmartAccountExitQuestion();
  const q = smartAccountExitQuestion(true);
  expect(q.title).toBe('Nueva pregunta');
  expect(q.reasons).toEqual([['money', 'Sin dinero'], ['other', 'Otra cosa']]);
});

it('a failed or malformed read falls back, and never keeps an older answer', async () => {
  mockQuery.mockResolvedValueOnce({ data: { smartAccountExitQuestion: {
    title: 'Vieja', options: [{ key: 'money', label: 'a' }, { key: 'other', label: 'b' }] } } });
  await preloadSmartAccountExitQuestion();
  mockQuery.mockRejectedValueOnce(new Error('old server'));
  await preloadSmartAccountExitQuestion();
  expect(smartAccountExitQuestion(false).title).toBe(SMART_ACCOUNT_EXIT_TITLE);
  expect(parseExitQuestion({ smartAccountExitQuestion: { title: 'x', options: [{ key: 'money', label: 'a' }] } })).toBeNull();
  expect(parseExitQuestion(null)).toBeNull();
});

it('an older read answering late never overwrites the latest, and the cap keeps "Otra cosa"', async () => {
  let answerOld: (v: unknown) => void = () => {};
  mockQuery.mockImplementationOnce(() => new Promise((r) => { answerOld = r; }));
  const old = preloadSmartAccountExitQuestion();
  mockQuery.mockRejectedValueOnce(new Error('offline'));
  await preloadSmartAccountExitQuestion();
  answerOld({ data: { smartAccountExitQuestion: { title: 'De otra cuenta',
    options: [{ key: 'money', label: 'a' }, { key: 'other', label: 'b' }] } } });
  await old;
  expect(smartAccountExitQuestion(false).title).toBe(SMART_ACCOUNT_EXIT_TITLE);
  const many = Array.from({ length: 12 }, (_, i) => ({ key: `k${'abcdefghijkl'[i]}`, label: `L${i}` }));
  const parsed = parseExitQuestion({ smartAccountExitQuestion: { title: 't',
    options: [...many, { key: 'ka', label: 'dup' }, { key: 'other', label: 'Otra cosa' }] } });
  expect(parsed?.reasons).toHaveLength(8);
  expect(parsed?.reasons[7]).toEqual(['other', 'Otra cosa']);
  expect(new Set(parsed?.reasons.map(([id]) => id)).size).toBe(8);
});

it('asks at most once a week per device', async () => {
  const store = memory();
  resetSmartAccountExitForTests(store);
  const asks: Array<{ title: string }> = [];
  subscribeSmartAccountExitQuestion((ask) => asks.push(ask));
  const now = Date.now();
  await expect(requestSmartAccountExitQuestion(false, 'annual', now)).resolves.toBe(true);
  await expect(requestSmartAccountExitQuestion(false, 'annual', now + 60_000)).resolves.toBe(false);
  await expect(requestSmartAccountExitQuestion(false, null, now + 8 * 24 * 3600 * 1000)).resolves.toBe(true);
  expect(asks).toHaveLength(2);
  expect(asks[0].title).toBe(SMART_ACCOUNT_EXIT_TITLE);
  expect(store.get()).toBe(now + 8 * 24 * 3600 * 1000);
});

it('never asks with no host mounted', async () => {
  await expect(requestSmartAccountExitQuestion(false, null)).resolves.toBe(false);
});

it('a quick look is not asked about', () => {
  expect(MIN_VISIT_MS).toBeGreaterThanOrEqual(3000);
});
