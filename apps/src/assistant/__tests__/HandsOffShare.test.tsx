/* eslint-disable @typescript-eslint/no-require-imports */
// The Comunidad share of a hands-off chat trade: offered once, when the card sees the trade turn done.
import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockQuery = jest.fn();
const mockShare = jest.fn();
let mockDex = true;

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({
  Text: require('react-native').Text, TextInput: require('react-native').TextInput,
}));
jest.mock('../../components/common/Button', () => ({ Button: () => null }));
jest.mock('../../config/features', () => ({ get DEX_TRADING_UI_ENABLED() { return mockDex; } }));
jest.mock('../../components/smartAccount/SignFlowSheet', () => ({ SignFlowSheet: () => null }));
jest.mock('../../components/smartAccount/useSignFlow', () => ({
  useSignFlow: () => ({ state: { phase: 'idle' }, start: jest.fn() }),
}));
jest.mock('../../services/communityShare', () => ({ requestActivityShare: (...a: unknown[]) => mockShare(...a) }));
const mockClient = { query: (...a: unknown[]) => mockQuery(...a), mutate: jest.fn() };
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useApolloClient: () => mockClient,
}));

import { HandsOffCards } from '../HandsOffCards';

const TRADE = '1b0c2a4e-1111-4222-8333-944455556666';
const HASH = '0xabc123';

/** The server: the trade's states in order (the last one stays), and its asset kind. */
function serve(states: Array<{ status: string; txHash?: string }>, assetKind = 'stock') {
  let i = 0;
  mockQuery.mockImplementation(({ query }: { query: string }) => {
    if (query.includes('AssistantRelayTradeKind')) {
      return Promise.resolve({ data: { assistantRelayTrade: { assetKind } } });
    }
    const state = states[Math.min(i, states.length - 1)];
    i += 1;
    const row = { label: 'Comprar US$1 de AAPL', txHash: '', ...state };
    return Promise.resolve({ data: { assistantRelayTrade: row, assistantRelayPurchase: { ...row, amount: '12.5' } } });
  });
}

async function flush() {
  for (let n = 0; n < 6; n += 1) {
    await act(async () => { await Promise.resolve(); });
  }
}

async function mount(onLeave?: () => void, type = 'relay_trade', onSettled?: () => void) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(<HandsOffCards messageId="9" actions={[{ type, target: TRADE } as any]}
      onOpen={jest.fn()} onLeave={onLeave} onSettled={onSettled} />);
  });
  await flush();
  return tree;
}

async function poll() {
  await act(async () => { jest.advanceTimersByTime(4000); });
  await flush();
}

beforeEach(() => {
  jest.useFakeTimers();
  mockQuery.mockReset();
  mockShare.mockReset();
  mockDex = true;
});

afterEach(() => {
  jest.useRealTimers();
});

it('offers the stock share once when the trade turns done on screen', async () => {
  serve([{ status: 'pending' }, { status: 'done', txHash: HASH }]);
  const tree = await mount();
  expect(mockShare).not.toHaveBeenCalled();
  await poll();
  expect(mockShare).toHaveBeenCalledTimes(1);
  expect(mockShare).toHaveBeenCalledWith({ group: 'stock', reference: HASH });
  await poll();
  await act(async () => { tree.update(<HandsOffCards messageId="9" actions={[{ type: 'relay_trade', target: TRADE } as any]}
    onOpen={jest.fn()} />); });
  await flush();
  expect(mockShare).toHaveBeenCalledTimes(1);
});

it('never offers it for a trade already done when the card appeared (an old message)', async () => {
  serve([{ status: 'done', txHash: HASH }]);
  const tree = await mount();
  await poll();
  expect(mockShare).not.toHaveBeenCalled();
  // The button is still there for whoever wants it.
  expect(tree.root.findAllByProps({ testID: 'relay-trade-share' }).length).toBeGreaterThan(0);
});

it('offers the crypto share for bitcoin or gold', async () => {
  serve([{ status: 'pending' }, { status: 'done', txHash: HASH }], 'crypto');
  await mount();
  await poll();
  expect(mockShare).toHaveBeenCalledWith({ group: 'crypto', reference: HASH });
});

it('no crypto share on a build without bitcoin and gold', async () => {
  mockDex = false;
  serve([{ status: 'pending' }, { status: 'done', txHash: HASH }], 'crypto');
  const tree = await mount();
  await poll();
  expect(mockShare).not.toHaveBeenCalled();
  expect(tree.root.findAllByProps({ testID: 'relay-trade-share' })).toHaveLength(0);
});

it('in the floating box it is the button: the box closes first', async () => {
  const onLeave = jest.fn();
  serve([{ status: 'pending' }, { status: 'done', txHash: HASH }]);
  const tree = await mount(onLeave);
  await poll();
  expect(mockShare).not.toHaveBeenCalled();
  await act(async () => { tree.root.findAllByProps({ testID: 'relay-trade-share' })[0].props.onPress(); });
  expect(onLeave).toHaveBeenCalledTimes(1);
  await act(async () => { jest.advanceTimersByTime(300); });
  expect(mockShare).toHaveBeenCalledWith({ group: 'stock', reference: HASH });
});

it('a failed trade offers nothing', async () => {
  serve([{ status: 'pending' }, { status: 'failed' }]);
  await mount();
  await poll();
  expect(mockShare).not.toHaveBeenCalled();
});

describe('the result note comes in at once', () => {
  it('a trade seen settling reloads the conversation, now and once more a moment later', async () => {
    const onSettled = jest.fn();
    serve([{ status: 'pending' }, { status: 'done', txHash: HASH }]);
    await mount(undefined, 'relay_trade', onSettled);
    expect(onSettled).not.toHaveBeenCalled();
    await poll();
    expect(onSettled).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(3000); });
    expect(onSettled).toHaveBeenCalledTimes(2);
    await poll();
    await act(async () => { jest.advanceTimersByTime(10000); });
    expect(onSettled).toHaveBeenCalledTimes(2);
  });

  it('a failed trade reloads it too (its note says why)', async () => {
    const onSettled = jest.fn();
    serve([{ status: 'pending' }, { status: 'failed' }]);
    await mount(undefined, 'relay_trade', onSettled);
    await poll();
    expect(onSettled).toHaveBeenCalled();
  });

  it('a Comprar purchase seen settling reloads it', async () => {
    const onSettled = jest.fn();
    serve([{ status: 'pending' }, { status: 'done' }]);
    await mount(undefined, 'relay_purchase', onSettled);
    await poll();
    expect(onSettled).toHaveBeenCalledTimes(1);
  });

  it('never for a card already settled (an old message, or the result note itself)', async () => {
    const onSettled = jest.fn();
    serve([{ status: 'done', txHash: HASH }]);
    const tree = await mount(undefined, 'relay_trade', onSettled);
    await poll();
    expect(onSettled).not.toHaveBeenCalled();
    // The note carries the same card: there it offers the share as a button.
    expect(tree.root.findAllByProps({ testID: 'relay-trade-share' }).length).toBeGreaterThan(0);
  });
});
