// Salida de emergencia, Hyperliquid leg: never withdraw while a position is
// still open (an IOC close can fill partly or not at all), and never report
// a close Hyperliquid did not fill.
jest.mock('../emergencyExit/heartbeat', () => ({ assertExitOpen: jest.fn(async () => undefined) }));

import { executeHyperCoreExit, planHyperCoreExit } from '../emergencyExit/hyperCoreExit';

const ME = '0x' + '44'.repeat(20);
const KEY = '0x' + '01'.repeat(32);
const wallet = { address: ME, privKeyHex: KEY } as any;

const fakeHyperliquid = ({ fills, spot = 0, startOpen = true }: { fills: boolean; spot?: number; startOpen?: boolean }) => {
  let open = startOpen;
  let spotUsdc = spot;
  let core = 0;
  const sent: any[] = [];
  const fetcher = jest.fn(async (url: string, init: any) => {
    const body = JSON.parse(init.body);
    const json = (v: unknown) => ({ ok: true, json: async () => v });
    if (url.endsWith('/exchange')) {
      sent.push(body.action);
      if (body.action.type === 'sendAsset' && body.action.sourceDex === 'spot') {
        core += Number(body.action.amount);
        spotUsdc = 0;
      }
      if (body.action.type === 'order') {
        if (fills) open = false;
        return json({ status: 'ok', response: { type: 'order', data: { statuses: [
          fills ? { filled: { totalSz: '0.1', avgPx: '100', oid: 1 } } : { error: 'Order could not immediately match' }] } } });
      }
      return json({ status: 'ok', response: { type: 'default' } });
    }
    if (body.type === 'perpDexs') return json([null]);
    if (body.type === 'spotClearinghouseState') return json({ balances: [{ coin: 'USDC', token: 0, total: String(spotUsdc), hold: '0' }] });
    if (body.type === 'userAbstraction') return json('unifiedAccount');
    if (body.type === 'metaAndAssetCtxs') return json([{ universe: [{ name: 'BTC', szDecimals: 3 }], collateralToken: 0 }, [{ markPx: '100' }]]);
    return json({
      withdrawable: String((open ? 0 : (startOpen ? 50 : 0)) + core),
      marginSummary: { accountValue: String((startOpen ? 50 : 0) + core) },
      assetPositions: open ? [{ position: { coin: 'BTC', szi: '0.1', entryPx: '100' } }] : [],
    });
  });
  return { fetcher: fetcher as unknown as typeof fetch, sent };
};

it('estimates the money held in open positions, not only the free balance', async () => {
  const { fetcher } = fakeHyperliquid({ fills: true });
  const plan = await planHyperCoreExit(ME, fetcher);
  expect(plan.positions).toHaveLength(1);
  expect(plan.estimatedOutUsd).toBe(49);
});

it('closes, then withdraws everything to the destination', async () => {
  const { fetcher, sent } = fakeHyperliquid({ fills: true });
  const result = await executeHyperCoreExit({ wallet, dest: '0x' + '55'.repeat(20), fetcher });
  expect(result.closed).toEqual(['BTC']);
  expect(sent.map((a) => a.type)).toEqual(['order', 'withdraw3']);
  expect(sent[1].destination).toBe('0x' + '55'.repeat(20));
});

it('an unfilled close is retried wider and never followed by a withdrawal', async () => {
  const { fetcher, sent } = fakeHyperliquid({ fills: false });
  await expect(executeHyperCoreExit({ wallet, dest: '0x' + '55'.repeat(20), fetcher })).rejects.toThrow(/No pudimos cerrar BTC/);
  expect(sent.map((a) => a.type)).toEqual(['order', 'order', 'order']);
  expect(Number(sent[2].orders[0].p)).toBeLessThan(Number(sent[0].orders[0].p));
});

it('a unified account: spot USDC joins the perps balance (standard mode first), then withdraws', async () => {
  const { fetcher, sent } = fakeHyperliquid({ fills: true, spot: 100, startOpen: false });
  const plan = await planHyperCoreExit(ME, fetcher);
  expect(plan.spotFree).toBe(100);
  expect(plan.estimatedOutUsd).toBe(99);
  await executeHyperCoreExit({ wallet, dest: '0x' + '55'.repeat(20), fetcher });
  expect(sent.map((a) => a.type)).toEqual(['userSetAbstraction', 'sendAsset', 'withdraw3']);
  expect(sent[1]).toMatchObject({ sourceDex: 'spot', destinationDex: '', destination: ME });
});

it('a dex with another collateral is listed and left alone, never closed', async () => {
  const fetcher = (async (url: string, init: any) => {
    const body = JSON.parse(init.body);
    const json = (v: unknown) => ({ ok: true, json: async () => v });
    if (body.type === 'perpDexs') return json([null, { name: 'usdh' }]);
    if (body.type === 'metaAndAssetCtxs') {
      return json(body.dex ? [{ universe: [{ name: 'usdh:X', szDecimals: 2 }], collateralToken: 360 }, [{ markPx: '10' }]]
        : [{ universe: [], collateralToken: 0 }, []]);
    }
    if (body.type === 'spotClearinghouseState') return json({ balances: [] });
    return json(body.dex
      ? { withdrawable: '0', marginSummary: { accountValue: '100' }, assetPositions: [{ position: { coin: 'usdh:X', szi: '5' } }] }
      : { withdrawable: '0', marginSummary: { accountValue: '0' }, assetPositions: [] });
  }) as unknown as typeof fetch;
  const plan = await planHyperCoreExit(ME, fetcher);
  expect(plan.positions).toEqual([]);
  expect(plan.otherCollateral).toEqual(['usdh']);
});
