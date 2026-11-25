import React from 'react';
import renderer, { act } from 'react-test-renderer';
import {
  HomeMoneyStoreProvider, createHomeMoneyStore, registerHomeMenu, requestHomeMenu,
  sharedHomeMoneyStore, useHomeMoney, type HomeMoney,
} from '../homeMoneyStore';

const snapshot = (total: string): HomeMoney => ({
  ready: true, total, masked: false, canToggle: true, toggleBalance: () => {}, month: { kind: 'hidden' },
  currencyCode: 'USD', currencyHint: 'Mostrar en bolivianos', toggleCurrency: () => {}, refresh: () => {}, pull: () => {},
  accounts: [], switchAccount: () => {}, createBusiness: () => {},
  openMonth: () => {}, tiles: [], actions: [], notice: null,
});

let renders = 0;
let seen: HomeMoney | null = null;
const Probe = () => {
  renders += 1;
  seen = useHomeMoney();
  return null;
};

beforeEach(() => {
  sharedHomeMoneyStore.reset();
  renders = 0;
  seen = null;
});

it('publishing the same snapshot again notifies nobody (a render must not feed itself)', async () => {
  const store = createHomeMoneyStore();
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<HomeMoneyStoreProvider value={store}><Probe /></HomeMoneyStoreProvider>); });
  const first = snapshot('US$1,00');
  await act(async () => { store.publish(first); });
  const after = renders;
  expect(seen).toBe(first);
  await act(async () => {
    store.publish(first);
    store.publish(first);
  });
  expect(renders).toBe(after);
  await act(async () => { store.publish(snapshot('US$2,00')); });
  expect(renders).toBe(after + 1);
  await act(async () => { store.reset(); });
  expect(seen?.ready).toBe(false);
  await act(async () => tree.unmount());
});

it('two shells keep their own figures: one clearing its store never blanks the other', async () => {
  const first = createHomeMoneyStore();
  const second = createHomeMoneyStore();
  const mine = snapshot('US$1,00');
  first.publish(mine);
  second.publish(snapshot('US$2,00'));
  second.reset();
  expect(first.get()).toBe(mine);
  expect(second.get().ready).toBe(false);
  // Without a shell around it, a reader gets the shared store.
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  expect(seen).toBe(sharedHomeMoneyStore.get());
  await act(async () => tree.unmount());
});

it('"muéstrame mi dinero" opens the menu of the shell on top, and an older one going away does not unhook it', () => {
  const older = jest.fn();
  const newer = jest.fn();
  expect(requestHomeMenu()).toBe(false);
  const undoOlder = registerHomeMenu(older);
  const undoNewer = registerHomeMenu(newer);
  expect(requestHomeMenu()).toBe(true);
  expect(newer).toHaveBeenCalledTimes(1);
  expect(older).not.toHaveBeenCalled();
  // The newer shell goes away: the older one answers again.
  undoNewer();
  expect(requestHomeMenu()).toBe(true);
  expect(older).toHaveBeenCalledTimes(1);
  undoOlder();
  undoOlder();
  expect(requestHomeMenu()).toBe(false);
});
