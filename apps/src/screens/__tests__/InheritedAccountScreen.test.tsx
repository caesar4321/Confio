import { nav, resetMocks, returnToPersonal, setActiveAccount, setBalanceHidden, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  failedRead, flush, hasTappable, inherited, ok, prepared, refused, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { InheritedAccountScreen } from '../InheritedAccountScreen';
import * as direct from '../../services/smartAccountDirect';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async (asTab = false) => {
  await act(async () => { tree = renderer.create(<InheritedAccountScreen asTab={asTab} />); });
  await flush();
};

beforeEach(() => {
  resetMocks();
  api.fetchInheritedAccounts.mockResolvedValue(ok([inherited()]));
  api.prepareInheritedWithdraw.mockResolvedValue(prepared());
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('shows whose account it was, its assets and exactly two actions', async () => {
  await mount();
  const out = text(tree);
  expect(out).toContain('Heredada');
  expect(out).toContain('Cuenta de Luis R.');
  expect(out).toContain('US$321.00');
  expect(out).toContain('Confío Dollar');
  expect(hasTappable(tree, 'inherited-to-wallet')).toBe(true);
  expect(hasTappable(tree, 'inherited-to-smart')).toBe(true);
  expect(out).not.toContain('Reglas');
  expect(out).not.toContain('Tu plan');
});

it('moves everything to the wallet by the server id, never an address', async () => {
  await mount();
  await tap(tree, 'inherited-to-wallet');
  await flush();
  expect(api.prepareInheritedWithdraw).toHaveBeenCalledWith('i1', ['cusd'], 'wallet');
  await tap(tree, 'sign-confirm');
  await flush();
  expect(text(tree)).toContain('Ya está en tu billetera.');
  await tap(tree, 'sign-done');
  expect(nav.goBack).toHaveBeenCalled();
});

it('moves to the own Cuenta inteligente only when there is one', async () => {
  await mount();
  await tap(tree, 'inherited-to-smart');
  await flush();
  expect(api.prepareInheritedWithdraw).toHaveBeenCalledWith('i1', ['cusd'], 'smart_account');
  await act(async () => tree.unmount());
  api.fetchInheritedAccounts.mockResolvedValue(ok([inherited({ canMoveToSmartAccount: false })]));
  await mount();
  expect(hasTappable(tree, 'inherited-to-smart')).toBe(false);
});

describe('more assets than one signature may carry', () => {
  const many = (n: number, from = 0) => Array.from({ length: n }, (_, i) => ({
    key: `t${from + i}`, kind: 'token', symbol: `T${from + i}`, name: `Token ${from + i}`,
    address: '0x' + (from + i + 1).toString(16).padStart(40, '0'), units: '1', decimals: 18,
    valueUsd: '1.00', canPayFee: false,
  }));

  it('splits 13 assets into two signatures of at most 12, re-reading between them', async () => {
    const all = many(13);
    api.fetchInheritedAccounts.mockResolvedValue(ok([inherited({ assets: all })]));
    await mount();
    await tap(tree, 'inherited-to-wallet');
    await flush();
    expect(api.prepareInheritedWithdraw).toHaveBeenCalledTimes(1);
    expect(api.prepareInheritedWithdraw.mock.calls[0][1]).toEqual(all.slice(0, 12).map((a) => a.key));
    // After the first signature the read still lags and lists everything:
    // the already-moved keys are never sent again.
    api.fetchInheritedAccounts.mockClear();
    await tap(tree, 'sign-confirm');
    await flush();
    expect(api.fetchInheritedAccounts).toHaveBeenCalled();
    expect(api.prepareInheritedWithdraw).toHaveBeenCalledTimes(2);
    expect(api.prepareInheritedWithdraw.mock.calls[1]).toEqual(['i1', ['t12'], 'wallet']);
    expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(2);
    expect(text(tree)).toContain('Ya está en tu billetera.');
  });

  it('announces every signature and stops early when the re-read has nothing left', async () => {
    api.fetchInheritedAccounts.mockResolvedValue(ok([inherited({ assets: many(25) })]));
    await mount();
    await tap(tree, 'inherited-to-wallet');
    await flush();
    expect(text(tree)).toContain('Son 3 firmas seguidas');
    // The second re-read shows only one asset left that was not yet moved.
    api.fetchInheritedAccounts.mockResolvedValue(ok([inherited({ assets: many(1, 24) })]));
    await tap(tree, 'sign-confirm');
    await flush();
    expect(api.prepareInheritedWithdraw.mock.calls.map((c) => c[1])).toEqual([
      many(12).map((a) => a.key),
      ['t24'],
    ]);
    // Third step: re-read lists only t24 (already sent) -> nothing to move, done.
    expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(2);
    expect(text(tree)).toContain('Movimiento completo');
  });

  it('a later step refused by the server says the earlier one did move', async () => {
    api.fetchInheritedAccounts.mockResolvedValue(ok([inherited({ assets: many(13) })]));
    api.prepareInheritedWithdraw
      .mockResolvedValueOnce(prepared())
      .mockResolvedValueOnce(refused('Son demasiados activos para una sola firma.', 'too_many_assets'));
    await mount();
    await tap(tree, 'inherited-to-wallet');
    await flush();
    await tap(tree, 'sign-confirm');
    await flush();
    expect(text(tree)).toContain('Los pasos anteriores sí se completaron');
  });
});

it('opens the account named in the route', async () => {
  setRouteParams({ inheritedAccountId: 'i2' });
  api.fetchInheritedAccounts.mockResolvedValue(ok([inherited(), inherited({ inheritedAccountId: 'i2', fromName: 'Marta' })]));
  await mount();
  expect(text(tree)).toContain('Cuenta de Marta');
});

it('as the Home tab picks the account of the active context', async () => {
  setActiveAccount({ id: 'smart_2', type: 'smart', index: 2, avatar: 'M', smart: { inherited: true } });
  api.fetchInheritedAccounts.mockResolvedValue(ok([
    inherited({ inheritedAccountId: 'late', fromName: 'Marta', inheritedAt: '2026-11-16T00:00:00Z' }),
    inherited({ inheritedAccountId: 'early', fromName: 'Luis R.', inheritedAt: '2026-11-01T00:00:00Z' }),
  ]));
  await mount(true);
  expect(text(tree)).toContain('Cuenta de Marta');
});

it('says so when everything was moved, with the way back as the tab', async () => {
  setActiveAccount({ id: 'smart_1', type: 'smart', index: 1, avatar: 'L', smart: { inherited: true, inheritedAccountId: 'i1' } });
  api.fetchInheritedAccounts.mockResolvedValue(ok([inherited({ assets: [], totalUsd: '0' })]));
  await mount(true);
  expect(text(tree)).toContain('Ya moviste todo');
  expect(hasTappable(tree, 'inherited-to-wallet')).toBe(false);
  await tap(tree, 'Ir a mi billetera');
  expect(returnToPersonal).toHaveBeenCalled();
});

it('offers a retry when the account cannot be loaded', async () => {
  api.fetchInheritedAccounts.mockResolvedValue(failedRead);
  await mount();
  expect(text(tree)).toContain('No pudimos cargar esto');
});

describe('Confío cannot be reached', () => {
  const glue = direct as jest.Mocked<typeof direct>;
  const ACCOUNT = '0x00000000000000000000000000000000000000bb';
  const ME = '0x19e7e376e7c213b7e7e7e46cc70a5dd086daff2a';

  it('offers the direct withdraw to the own wallet under the error, from the device record', async () => {
    api.fetchInheritedAccounts.mockResolvedValue(failedRead);
    setRouteParams({ inheritedAccountId: 'i1' });
    glue.loadInheritedDirectEntry.mockResolvedValue({ account: ACCOUNT, inheritedAccountId: 'i1', savedAt: 1 });
    glue.ownWalletAddress.mockResolvedValue(ME);
    glue.readDirectSituation.mockResolvedValue({
      me: ME, account: ACCOUNT, step: { kind: 'withdraw' },
      holdings: [{ address: '0x' + '11'.repeat(20), label: 'Confío Dollar', balance: 1n }], gas: { kind: 'enough' },
    });
    await mount();
    expect(text(tree)).toContain('No pudimos cargar esto');
    expect(text(tree)).toContain('No pudimos conectar con Confío');
    await tap(tree, 'direct-offer');
    await flush();
    expect(glue.loadInheritedDirectEntry).toHaveBeenCalledWith('i1');
    expect(text(tree)).toContain('Mover a tu billetera');
    expect(hasTappable(tree, 'direct-send')).toBe(true);
  });
});

it('respects the hide-balance setting in the hero', async () => {
  setBalanceHidden(true);
  await mount();
  const hero = tree.root.findAll((n) => n.props.testID === 'inherited-total' && typeof n.type === 'string')[0]
    ?? tree.root.findAll((n) => n.props.testID === 'inherited-total')[0];
  expect(JSON.stringify(hero.props.children)).toContain('••••••');
  expect(hero.props.accessibilityLabel).toBe('Total: saldo oculto');
});

describe('opened by the received account\'s address', () => {
  const BB = '0x00000000000000000000000000000000000000bb';
  const EE = '0x00000000000000000000000000000000000000EE';

  it('matches the address case-insensitively, not the first account', async () => {
    setRouteParams({ contractAddress: EE });
    api.fetchInheritedAccounts.mockResolvedValue(ok([
      inherited(),
      inherited({ inheritedAccountId: 'i2', fromName: 'Marta', contractAddress: EE.toLowerCase() }),
    ]));
    await mount();
    expect(text(tree)).toContain('Cuenta de Marta');
    expect(text(tree)).not.toContain('Cuenta de Luis R.');
  });

  it('waits for the account to be registered instead of showing another or an empty state', async () => {
    setRouteParams({ contractAddress: EE });
    api.fetchInheritedAccounts.mockResolvedValue(ok([inherited({ contractAddress: BB })]));
    await mount();
    const out = text(tree);
    expect(out).toContain('Estamos terminando de registrar la cuenta…');
    expect(out).not.toContain('Cuenta de Luis R.');
    expect(out).not.toContain('No encontramos esta cuenta');
    expect(hasTappable(tree, 'inherited-to-wallet')).toBe(false);

    // It appears: a retry shows it.
    api.fetchInheritedAccounts.mockResolvedValue(ok([
      inherited({ contractAddress: BB }),
      inherited({ inheritedAccountId: 'i9', fromName: 'Marta', contractAddress: EE }),
    ]));
    await tap(tree, 'Reintentar');
    await flush();
    expect(text(tree)).toContain('Cuenta de Marta');
    expect(text(tree)).not.toContain('Estamos terminando');
  });
});
