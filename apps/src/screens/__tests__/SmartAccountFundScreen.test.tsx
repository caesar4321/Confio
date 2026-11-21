import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  failedRead, flush, hasTappable, movePreview, offer, ok, prepared, refused, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { SmartAccountFundScreen, fundingDollarKey } from '../SmartAccountFundScreen';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async () => {
  await act(async () => { tree = renderer.create(<SmartAccountFundScreen />); });
  await flush();
};

beforeEach(() => {
  resetMocks();
  setRouteParams({ plan: 'annual' });
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer()));
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview()));
  api.prepareSmartAccountSubscribe.mockResolvedValue(prepared({ summary: ['Plan anual · US$149.99', 'Mover a tu Cuenta inteligente: US$149.99'] }));
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('asks for the wallet list, shows the plan and what stays behind', async () => {
  await mount();
  expect(api.fetchSmartAccountMovePreview).toHaveBeenCalledWith('in');
  const out = text(tree);
  expect(out).toContain('Plan anual');
  expect(out).toContain('US$149.99');
  expect(out).toContain('Confío Dollar+');
  expect(out).toContain('Se queda en tu billetera');
  expect(out).toContain('La preventa bloqueada no se puede mover.');
});

it('prepares the minimum by default and shows the server summary before signing', async () => {
  await mount();
  await tap(tree, 'fund-review');
  await flush();
  // 149.99 of a 500.00 position of 500e18 units
  expect(api.prepareSmartAccountSubscribe).toHaveBeenCalledWith(
    'annual', [{ assetKey: 'cusd_plus', units: '149990000000000000000' }], true,
  );
  expect(text(tree)).toContain('Mover a tu Cuenta inteligente: US$149.99');
  expect(api.signAndSubmitPrepared).not.toHaveBeenCalled();
  await tap(tree, 'sign-confirm');
  await flush();
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(1);
  expect(text(tree)).toContain('Tu Cuenta inteligente está abierta');
  await tap(tree, 'sign-done');
  expect(nav.reset).toHaveBeenCalledWith({ index: 1, routes: [{ name: 'BottomTabs' }, { name: 'SmartAccountHome' }] });
});

it('adds a ticked asset whole and "Todo" as the whole dollar balance', async () => {
  await mount();
  await tap(tree, 'fund-extra-stock:AAPLon');
  await tap(tree, 'Todo, US$500.00');
  await tap(tree, 'fund-review');
  await flush();
  expect(api.prepareSmartAccountSubscribe).toHaveBeenCalledWith(
    'annual', [{ assetKey: 'cusd_plus', units: 'max' }, { assetKey: 'stock:AAPLon', units: 'max' }], true,
  );
});

it('does not prepare an amount under the first period', async () => {
  await mount();
  const input = tree.root.findAll((n) => n.props.testID === 'fund-amount' && typeof n.props.onChangeText === 'function')[0];
  await act(async () => { input.props.onChangeText('20'); });
  await tap(tree, 'fund-review');
  expect(api.prepareSmartAccountSubscribe).not.toHaveBeenCalled();
  expect(text(tree)).toContain('El mínimo es US$149.99');
});

it('says what is missing when the wallet cannot cover the first period', async () => {
  const short = movePreview();
  short.assets[0] = { ...short.assets[0], valueUsd: '20.00' };
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(short));
  await mount();
  expect(text(tree)).toContain('Necesitas US$149.99 en Confío Dollar+');
  expect(hasTappable(tree, 'fund-review')).toBe(false);
});

it('shows the server reason when it refuses, and nothing is signed', async () => {
  api.prepareSmartAccountSubscribe.mockResolvedValue(refused('Tu cuenta está en revisión.'));
  await mount();
  await tap(tree, 'fund-review');
  await flush();
  expect(text(tree)).toContain('Tu cuenta está en revisión.');
  expect(api.signAndSubmitPrepared).not.toHaveBeenCalled();
});

it('never calls an unknown outcome a failure', async () => {
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'unknown', txHash: '0xdead' });
  await mount();
  await tap(tree, 'fund-review');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush();
  const out = text(tree);
  expect(out).toContain('Estamos confirmando');
  expect(out).toContain('No la repitas');
  expect(out).not.toContain('No se realizó');
});

it('says nothing moved when the network rejects it', async () => {
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'reverted', txHash: '0x1' });
  await mount();
  await tap(tree, 'fund-review');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush();
  expect(text(tree)).toContain('No se realizó');
  expect(text(tree)).toContain('No se movió nada');
});

it('signs once on a double tap', async () => {
  await mount();
  await tap(tree, 'fund-review');
  await flush();
  await act(async () => {
    const b = tree.root.findAll((n) => n.props.testID === 'sign-confirm' && typeof n.props.onPress === 'function')[0];
    b.props.onPress();
    b.props.onPress();
  });
  await flush();
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(1);
});

it('offers a retry when the lists cannot be loaded', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(failedRead);
  await mount();
  expect(text(tree)).toContain('No pudimos cargar esto');
});

it('lists the other dollar with the other assets only when it holds something', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
    assets: [
      { key: 'cusd_plus', symbol: 'cUSD+', name: 'cUSD+', units: '500000000000000000000', decimals: 18, valueUsd: '500.00', included: true, reason: null },
      { key: 'cusd', symbol: 'cUSD', name: 'cUSD', units: '0', decimals: 18, valueUsd: '0.00', included: true, reason: null },
    ],
  })));
  await mount();
  expect(hasTappable(tree, 'fund-extra-cusd')).toBe(false);
  await act(async () => tree.unmount());
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
    assets: [
      { key: 'cusd_plus', symbol: 'cUSD+', name: 'cUSD+', units: '500000000000000000000', decimals: 18, valueUsd: '500.00', included: true, reason: null },
      { key: 'cusd', symbol: 'cUSD', name: 'cUSD', units: '7000000000000000000', decimals: 18, valueUsd: '7.00', included: true, reason: null },
    ],
  })));
  await mount();
  expect(hasTappable(tree, 'fund-extra-cusd')).toBe(true);
  expect(text(tree)).toContain('También puedes mover');
});

describe('the minimum follows the chosen plan, not the cheapest one', () => {
  // The server's minFirstDepositUsd is the monthly (cheapest) first period.
  beforeEach(() => {
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ minFirstDepositUsd: '14.99' })));
  });
  const amountInput = () => tree.root.findAll(
    (n) => n.props.testID === 'fund-amount' && typeof n.props.onChangeText === 'function',
  )[0];

  it('annual: prefills, gates, labels and copies the annual price', async () => {
    await mount();
    const out = text(tree);
    expect(out).toContain('Mínimo US$149.99: cubre tu primer período.');
    expect(out).not.toContain('US$14.99');
    expect(amountInput().props.value).toBe('149.99');
    expect(hasTappable(tree, 'Mínimo, US$149.99')).toBe(true);
    await act(async () => { amountInput().props.onChangeText('20'); });
    await tap(tree, 'fund-review');
    expect(api.prepareSmartAccountSubscribe).not.toHaveBeenCalled();
    expect(text(tree)).toContain('El mínimo es US$149.99');
    await tap(tree, 'Mínimo, US$149.99');
    await tap(tree, 'fund-review');
    await flush();
    expect(api.prepareSmartAccountSubscribe).toHaveBeenCalledWith(
      'annual', [{ assetKey: 'cusd_plus', units: '149990000000000000000' }], true,
    );
  });

  it('annual: a wallet that covers a month but not the year is told the annual price', async () => {
    const short = movePreview();
    short.assets[0] = { ...short.assets[0], valueUsd: '100.00' };
    api.fetchSmartAccountMovePreview.mockResolvedValue(ok(short));
    await mount();
    expect(text(tree)).toContain('Necesitas US$149.99 en Confío Dollar+');
    expect(hasTappable(tree, 'fund-review')).toBe(false);
  });

  it('monthly: the monthly price is the minimum', async () => {
    setRouteParams({ plan: 'monthly' });
    await mount();
    expect(text(tree)).toContain('Mínimo US$14.99: cubre tu primer período.');
    expect(amountInput().props.value).toBe('14.99');
    await tap(tree, 'fund-review');
    await flush();
    expect(api.prepareSmartAccountSubscribe).toHaveBeenCalledWith(
      'monthly', [{ assetKey: 'cusd_plus', units: '14990000000000000000' }], true,
    );
  });

  it('never goes under the server minimum when it is above the plan price', async () => {
    setRouteParams({ plan: 'monthly' });
    api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ minFirstDepositUsd: '20.00' })));
    await mount();
    expect(text(tree)).toContain('Mínimo US$20.00: cubre tu primer período.');
  });
});

describe('the funding dollar is the one the person holds', () => {
  const row = (key: string, valueUsd: string, units: string) => ({
    key, symbol: key, name: key, units, decimals: 18, valueUsd, included: true, reason: null,
  });
  const cusd = (usdValue: string, units: string) => row('cusd', usdValue, units);
  const plus = (usdValue: string, units: string) => row('cusd_plus', usdValue, units);
  const stock = row('stock:AAPLon', '200.00', '1000000000000000000');

  it('picks the only dollar held, else the one covering the minimum, else the offer\'s', () => {
    const min = 14999n;
    expect(fundingDollarKey([cusd('500.00', '500000000000000000000'), stock], 'cusd_plus', min)).toBe('cusd');
    expect(fundingDollarKey([plus('0', '0'), cusd('500.00', '500000000000000000000')], 'cusd_plus', min)).toBe('cusd');
    expect(fundingDollarKey([plus('20.00', '20000000000000000000'), cusd('500.00', '500000000000000000000')], 'cusd_plus', min)).toBe('cusd');
    expect(fundingDollarKey([plus('500.00', '500000000000000000000'), cusd('500.00', '500000000000000000000')], 'cusd', min)).toBe('cusd');
    expect(fundingDollarKey([plus('20.00', '20000000000000000000'), cusd('30.00', '30000000000000000000')], 'cusd_plus', min)).toBe('cusd_plus');
    expect(fundingDollarKey([stock], 'cusd_plus', min)).toBe('cusd_plus');
  });

  it('funds from the other dollar when that is the one held, never saying US$0', async () => {
    api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
      assets: [cusd('500.00', '500000000000000000000'), stock],
    })));
    await mount();
    const out = text(tree);
    expect(out).not.toContain('US$0.00');
    expect(out).not.toContain('Necesitas');
    await tap(tree, 'fund-review');
    await flush();
    expect(api.prepareSmartAccountSubscribe).toHaveBeenCalledWith(
      'annual', [{ assetKey: 'cusd', units: '149990000000000000000' }], true,
    );
  });

  it('holding both, uses whichever covers the minimum', async () => {
    api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
      assets: [plus('20.00', '20000000000000000000'), cusd('500.00', '500000000000000000000')],
    })));
    await mount();
    expect(text(tree)).not.toContain('Necesitas');
    await tap(tree, 'fund-review');
    await flush();
    expect(api.prepareSmartAccountSubscribe).toHaveBeenCalledWith(
      'annual', [{ assetKey: 'cusd', units: '149990000000000000000' }], true,
    );
  });

  it('short in the dollar held: the notice names that dollar and its real balance', async () => {
    api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
      assets: [cusd('20.00', '20000000000000000000')],
    })));
    await mount();
    const out = text(tree);
    expect(out).toContain('Hoy tienes US$20.00 en tu billetera');
    expect(out).not.toContain('US$0.00');
  });
});
