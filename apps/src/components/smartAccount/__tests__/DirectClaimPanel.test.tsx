import { resetMocks } from '../testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { flush, tap, tappable, text } from '../testing/fixtures';
import { DirectClaimPanel } from '../DirectClaimPanel';

const direct = require('../../../services/smartAccountDirect');
const ACCOUNT = '0x00000000000000000000000000000000000000aa';
const ME = '0x00000000000000000000000000000000000000bb';

let tree: renderer.ReactTestRenderer;
beforeEach(() => {
  resetMocks();
  direct.loadDirectEntry.mockResolvedValue({ account: ACCOUNT, designationId: 'd1', savedAt: 1 });
  direct.ownWalletAddress.mockResolvedValue(ME);
  direct.readDirectSituation.mockResolvedValue({
    me: ME, account: ACCOUNT, step: { kind: 'initiate' }, holdings: [], gas: { kind: 'enough' },
  });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('two taps in the same frame sign once', async () => {
  let finish!: (v: unknown) => void;
  direct.runDirectStep.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  await act(async () => { tree = renderer.create(<DirectClaimPanel designationId="d1" serverDown />); });
  await tap(tree, 'direct-offer');
  await flush();
  const send = tappable(tree, 'direct-send').props.onPress;
  // Both presses land before React re-renders the button away.
  await act(async () => { send(); send(); });
  expect(direct.runDirectStep).toHaveBeenCalledTimes(1);

  await act(async () => { finish({ status: 'executed' }); });
  await flush();
  expect(text(tree)).toContain('Tu pedido quedó en la red.');
});

it('a cancelled signature frees the guard so the person can sign again', async () => {
  direct.runDirectStep.mockResolvedValueOnce({ status: 'cancelled' }).mockResolvedValueOnce({ status: 'executed' });
  await act(async () => { tree = renderer.create(<DirectClaimPanel designationId="d1" serverDown />); });
  await tap(tree, 'direct-offer');
  await flush();
  await tap(tree, 'direct-send');
  await flush();
  await tap(tree, 'direct-send');
  await flush();
  expect(direct.runDirectStep).toHaveBeenCalledTimes(2);
});
