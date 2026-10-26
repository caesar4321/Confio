// A retried open reuses the first open's nonce while that order may still
// reach Hyperliquid: of the two signatures, at most one can ever execute.
const store: Record<string, string> = {};
jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(async ({ service }: { service: string }) =>
    (store[service] ? { username: 'perps', password: store[service] } : false)),
  setGenericPassword: jest.fn(async (_u: string, password: string, { service }: { service: string }) => {
    store[service] = password;
    return true;
  }),
}));
const outcomes: Record<string, { outcome: string; placedMs: number | null }> = {};
jest.mock('../hyperliquidInfo', () => ({
  venueOrderOutcome: jest.fn(async (_w: string, cloid: string) => outcomes[cloid] ?? { outcome: 'unknown', placedMs: null }),
  venueLeverage: jest.fn(), venueMarket: jest.fn(), venuePosition: jest.fn(),
  fetchBounded: (url: string, init: any) => (globalThis.fetch as any)(url, init),
}));

import { openNonce } from '../perps';

const W = '0x' + '44'.repeat(20);
const A = '0x' + 'aa'.repeat(16);
const B = '0x' + 'bb'.repeat(16);

beforeEach(() => {
  jest.restoreAllMocks(); for (const k of Object.keys(store)) delete store[k]; for (const k of Object.keys(outcomes)) delete outcomes[k]; });

it('reuses the nonce while the first order never reached Hyperliquid', async () => {
  const first = await openNonce('p1', W, A);
  expect(await openNonce('p1', W, B)).toBe(first);
});

it('a fresh nonce only once an order with it was processed and died unfilled', async () => {
  const first = await openNonce('p1', W, A);
  await openNonce('p1', W, B); // B shares the nonce
  outcomes[B] = { outcome: 'dead', placedMs: first + 10 }; // the nonce is spent: neither A nor B can execute now
  expect(await openNonce('p1', W, '0x' + 'cc'.repeat(16))).not.toBe(first);
});

it('refuses another open once any order with the nonce filled', async () => {
  await openNonce('p1', W, A);
  outcomes[A] = { outcome: 'filled', placedMs: Date.now() };
  await expect(openNonce('p1', W, B)).rejects.toMatchObject({ code: 'already_open' });
});

it('two overlapping opens share one nonce and both orders are remembered', async () => {
  const [x, y] = await Promise.all([openNonce('p2', W, A), openNonce('p2', W, B)]);
  expect(x).toBe(y);
  expect(JSON.parse(store.confio_perps_open_nonce)[W].cloids.map((c: any) => c.cloid)).toEqual([A, B]);
});

it('an unresolved order too old to re-sign blocks a new signature until Hyperliquid would refuse it', async () => {
  const first = await openNonce('p3', W, A);
  const spy = jest.spyOn(Date, 'now').mockReturnValue(first + 46 * 3600 * 1000);
  await expect(openNonce('p3', W, B)).rejects.toMatchObject({ code: 'open_pending' });
  spy.mockReturnValue(first + 50 * 3600 * 1000); // past Hyperliquid's 2-day window: the old one is dead
  expect(await openNonce('p3', W, B)).not.toBe(first);
  spy.mockRestore();
});

it('an old dead order replayed as a new id is no proof, and is refused as a new order', async () => {
  const old = '0x' + 'dd'.repeat(16);
  outcomes[old] = { outcome: 'dead', placedMs: 1 }; // dead long before this open
  await openNonce('p4', W, A);
  await expect(openNonce('p4', W, old)).rejects.toMatchObject({ code: 'unsafe_plan' });
});

it('a signature left from another position shares its nonce with the next open', async () => {
  const W2 = '0x' + '66'.repeat(20);
  const first = await openNonce('btc', W2, '0x' + 'e1'.repeat(16));
  // The BTC order never reached Hyperliquid; a new ETH position opens later.
  expect(await openNonce('eth', W2, '0x' + 'e2'.repeat(16))).toBe(first);
});

it('a withheld close shares its nonce with the next open: at most one can execute', async () => {
  const W3 = '0x' + '77'.repeat(20);
  const close = await openNonce('old', W3, '0x' + 'c1'.repeat(16), 'close');
  expect(await openNonce('new', W3, '0x' + 'c2'.repeat(16), 'open')).toBe(close);
});

it('a partly filled close spends its nonce: the remainder closes with a fresh one', async () => {
  const W4 = '0x' + '88'.repeat(20);
  const c = '0x' + 'c3'.repeat(16);
  const first = await openNonce('p9', W4, c, 'close');
  outcomes[c] = { outcome: 'filled', placedMs: first + 5 };
  expect(await openNonce('p9', W4, '0x' + 'c4'.repeat(16), 'close')).not.toBe(first);
});

describe('leverage updates', () => {
  const { venueLeverage } = jest.requireMock('../hyperliquidInfo') as { venueLeverage: jest.Mock };
  const { leverageNonce } = jest.requireActual('../perps') as typeof import('../perps');

  it('a new update reuses an unconfirmed one\'s nonce: a withheld 20x can never apply after it', async () => {
    const W5 = '0x' + '99'.repeat(20);
    venueLeverage.mockResolvedValue({ type: 'cross', value: 20 });
    const first = await leverageNonce(W5, 'BTC', 20);
    expect(await leverageNonce(W5, 'BTC', 2)).toBe(first);
  });

  it('never signs a no-op update (it could not prove anything later)', async () => {
    venueLeverage.mockResolvedValue({ type: 'isolated', value: 20 });
    await expect(leverageNonce('0x' + 'cd'.repeat(20), 'BTC', 20)).rejects.toMatchObject({ code: 'unsafe_plan' });
  });

  it('once the recorded setting is live on the venue, the next update gets a fresh nonce', async () => {
    const W6 = '0x' + 'ab'.repeat(20);
    venueLeverage.mockResolvedValue({ type: 'cross', value: 20 });
    const first = await leverageNonce(W6, 'BTC', 3);
    venueLeverage.mockResolvedValue({ type: 'isolated', value: 3 });
    expect(await leverageNonce(W6, 'ETH', 5)).not.toBe(first);
  });
});

it('a replacement protection shares a withheld one\'s nonce until one of them is processed', async () => {
  const { tpslNonce } = jest.requireActual('../perps') as typeof import('../perps');
  const W7 = '0x' + 'ef'.repeat(20);
  const old = '0x' + 'a1'.repeat(16);
  const first = await tpslNonce(W7, [old]);
  expect(await tpslNonce(W7, ['0x' + 'a2'.repeat(16)])).toBe(first);
  outcomes['0x' + 'a2'.repeat(16)] = { outcome: 'open', placedMs: first + 10 }; // resting: processed
  expect(await tpslNonce(W7, ['0x' + 'a3'.repeat(16)])).not.toBe(first);
});

it('a withheld protection shares its nonce with the next open: it can never act on the new position', async () => {
  const { tpslNonce } = jest.requireActual('../perps') as typeof import('../perps');
  const W8 = '0x' + 'f1'.repeat(20);
  const stop = await tpslNonce(W8, ['0x' + 'b1'.repeat(16)]);
  expect(await openNonce('next', W8, '0x' + 'b2'.repeat(16), 'open')).toBe(stop);
  outcomes['0x' + 'b2'.repeat(16)] = { outcome: 'filled', placedMs: stop + 10 }; // the open executed: nonce spent
  expect(await openNonce('after', W8, '0x' + 'b3'.repeat(16), 'open')).not.toBe(stop);
});

it('before new money moves, every outstanding nonce is spent with a noop posted straight to Hyperliquid', async () => {
  const { retireOutstanding } = jest.requireActual('../perps') as typeof import('../perps');
  const W9 = '0x' + '12'.repeat(20);
  const nonce = await openNonce('held', W9, '0x' + 'd1'.repeat(16), 'open'); // a signature that may be withheld
  const posted: any[] = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = jest.fn(async (url: string, init: any) => {
    posted.push({ url, body: JSON.parse(init.body) });
    return { ok: true, json: async () => ({ status: 'ok', response: { type: 'default' } }) };
  }) as any;
  try {
    await retireOutstanding({ address: W9, privKeyHex: '0x' + '01'.repeat(32) });
  } finally {
    globalThis.fetch = realFetch;
  }
  expect(posted).toHaveLength(1);
  expect(posted[0].url).toBe('https://api.hyperliquid.xyz/exchange');
  expect(posted[0].body).toMatchObject({ action: { type: 'noop' }, nonce });
  // The record is gone: the next open gets a fresh nonce.
  expect(await openNonce('next', W9, '0x' + 'd2'.repeat(16), 'open')).not.toBe(nonce);
});

it('a nonce too far in the future is not retirement: the record is kept', async () => {
  const { retireOutstanding, rememberNonce } = jest.requireActual('../perps') as typeof import('../perps');
  const W10 = '0x' + '13'.repeat(20);
  await rememberNonce(W10, Date.now());
  const realFetch = globalThis.fetch;
  globalThis.fetch = jest.fn(async () => ({
    ok: true, json: async () => ({ status: 'err', response: 'Invalid nonce: too far in the future' }),
  })) as any;
  try {
    await expect(retireOutstanding({ address: W10, privKeyHex: '0x' + '01'.repeat(32) }))
      .rejects.toMatchObject({ code: 'hyperliquid_unavailable' });
  } finally {
    globalThis.fetch = realFetch;
  }
  expect(JSON.parse(store.confio_perps_signed_nonces)[W10]).toHaveLength(1);
});
