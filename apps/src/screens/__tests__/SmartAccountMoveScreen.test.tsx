import { nav, resetMocks, setRouteParams } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../services/smartAccount';
import {
  failedRead, flush, hasTappable, movePreview, offer, ok, prepared, refused, tap, text,
} from '../../components/smartAccount/testing/fixtures';
import { SmartAccountMoveScreen } from '../SmartAccountMoveScreen';

const api = service as jest.Mocked<typeof service>;
let tree: renderer.ReactTestRenderer;
const mount = async () => {
  await act(async () => { tree = renderer.create(<SmartAccountMoveScreen />); });
  await flush();
};

beforeEach(() => {
  resetMocks();
  setRouteParams({ direction: 'in' });
  api.fetchSmartAccountMovePreview.mockImplementation(async (direction) => ok(movePreview({ direction })));
  api.prepareSmartAccountMoveEverything.mockResolvedValue(prepared());
  api.prepareSmartAccountDeposit.mockResolvedValue(prepared());
  api.prepareSmartAccountWithdraw.mockResolvedValue(prepared());
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('lists what moves and what does not, with the reason', async () => {
  await mount();
  const out = text(tree);
  expect(out).toContain('En tu billetera');
  expect(out).toContain('Confío Dollar+');
  expect(out).toContain('No se mueve');
  expect(out).toContain('La preventa bloqueada no se puede mover.');
  expect(hasTappable(tree, 'move-other:presale')).toBe(false);
});

it('moves everything in one signature after showing the summary', async () => {
  await mount();
  await tap(tree, 'move-all');
  await flush();
  expect(api.prepareSmartAccountMoveEverything).toHaveBeenCalledWith('in', 0);
  expect(text(tree)).toContain('Línea del servidor');
  await tap(tree, 'sign-confirm');
  await flush();
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(1);
  expect(text(tree)).toContain('Movimiento completo');
  await tap(tree, 'sign-done');
  expect(nav.goBack).toHaveBeenCalled();
});

it('signs each batch of a long list in order, asking for batch 0 again each time', async () => {
  // The server rebuilds the list from live balances on every prepare: after a
  // batch executes, the next one is batch 0 again (asking for 1 would skip assets).
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({ batches: 3 })));
  await mount();
  expect(text(tree)).toContain('3 firmas');
  await tap(tree, 'move-all');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush(8);
  expect(api.prepareSmartAccountMoveEverything.mock.calls.map((c) => c[1])).toEqual([0, 0, 0]);
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(3);
  expect(text(tree)).toContain('Movimiento completo');
});

it('treats nothing_to_move after an executed batch as done', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({ batches: 3 })));
  api.prepareSmartAccountMoveEverything
    .mockResolvedValueOnce(prepared())
    .mockResolvedValueOnce(prepared())
    .mockResolvedValueOnce(refused('Nada que mover.', 'nothing_to_move'));
  await mount();
  await tap(tree, 'move-all');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush(8);
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(2);
  expect(api.prepareSmartAccountMoveEverything).toHaveBeenCalledTimes(3);
  expect(text(tree)).toContain('Movimiento completo');
});

it('treats bad_batch_index after executed batches as done', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({ batches: 2 })));
  api.prepareSmartAccountMoveEverything
    .mockResolvedValueOnce(prepared())
    .mockResolvedValueOnce(refused('Índice inválido.', 'bad_batch_index'));
  await mount();
  await tap(tree, 'move-all');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush(8);
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(1);
  expect(text(tree)).toContain('Movimiento completo');
});

it('never signs more than the expected number of batches', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({ batches: 2 })));
  await mount();
  await tap(tree, 'move-all');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush(10);
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(2);
  expect(api.prepareSmartAccountMoveEverything.mock.calls.length).toBeLessThanOrEqual(4);
});

it('stops a multi-batch move at an unknown outcome and says the earlier steps went through on a failure', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({ batches: 3 })));
  api.signAndSubmitPrepared
    .mockResolvedValueOnce({ status: 'executed', txHash: '0x1' })
    .mockResolvedValueOnce({ status: 'not_sent', code: 'simulation_reverted' });
  await mount();
  await tap(tree, 'move-all');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush(8);
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(2);
  expect(text(tree)).toContain('Los pasos anteriores sí se completaron; este (firma 2 de 3) no se realizó.');
  expect(text(tree)).not.toContain('No se movió nada');
});

it('a first-step failure still says nothing moved', async () => {
  api.signAndSubmitPrepared.mockResolvedValueOnce({ status: 'reverted', txHash: null });
  await mount();
  await tap(tree, 'move-all');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush(8);
  expect(text(tree)).toContain('No se movió nada');
});

it('never stays on "signing" when signing throws', async () => {
  api.signAndSubmitPrepared.mockRejectedValueOnce(new Error('boom'));
  await mount();
  await tap(tree, 'move-all');
  await flush();
  await tap(tree, 'sign-confirm');
  await flush(8);
  expect(text(tree)).not.toContain('Moviendo…');
  expect(text(tree)).toContain('Estamos confirmando');
});

it('switches direction and withdraws one asset', async () => {
  await mount();
  await tap(tree, 'Mover a mi billetera');
  await flush();
  expect(api.fetchSmartAccountMovePreview).toHaveBeenLastCalledWith('out');
  expect(text(tree)).toContain('En tu cuenta');
  await tap(tree, 'move-stock:AAPLon');
  expect(text(tree)).toContain('Se mueve toda tu posición (US$200.00) a tu billetera.');
  await tap(tree, 'move-one');
  await flush();
  expect(api.prepareSmartAccountWithdraw).toHaveBeenCalledWith('stock:AAPLon', 'max');
});

it('deposits part of the dollar by amount', async () => {
  await mount();
  await tap(tree, 'move-cusd_plus');
  const input = tree.root.findAll((n) => n.props.testID === 'move-amount' && typeof n.props.onChangeText === 'function')[0];
  await act(async () => { input.props.onChangeText('100'); });
  await tap(tree, 'move-one');
  await flush();
  expect(api.prepareSmartAccountDeposit).toHaveBeenCalledWith([{ assetKey: 'cusd_plus', units: '100000000000000000000' }]);
});

it('offers a retry when the list cannot be loaded', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(failedRead);
  await mount();
  expect(text(tree)).toContain('No pudimos cargar esto');
  expect(hasTappable(tree, 'move-all')).toBe(false);
});

it('says so when there is nothing to move', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({ assets: [], totalUsd: '0' })));
  await mount();
  expect(text(tree)).toContain('No hay nada que mover');
});

it('a null preview is an error with retry, not the empty state', async () => {
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(null));
  await mount();
  expect(text(tree)).toContain('No pudimos cargar esto');
  expect(text(tree)).not.toContain('No hay nada que mover');
  expect(hasTappable(tree, 'Reintentar')).toBe(true);
});

it('shows the viewer\'s dollar first, the other dollar only when nonzero and moved whole', async () => {
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ dollar: 'cusd_plus' })));
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
    assets: [
      { key: 'cusd', symbol: 'cUSD', name: 'cUSD', units: '5000000000000000000', decimals: 18, valueUsd: '5.00', included: true, reason: null },
      { key: 'cusd_plus', symbol: 'cUSD+', name: 'cUSD+', units: '500000000000000000000', decimals: 18, valueUsd: '500.00', included: true, reason: null },
      { key: 'stock:AAPLon', symbol: 'AAPLon', name: 'Apple', units: '0', decimals: 18, valueUsd: '0.00', included: true, reason: null },
    ],
  })));
  await mount();
  const ids = tree.root.findAll((n) => typeof n.props.testID === 'string' && n.props.testID.startsWith('move-') && typeof n.props.onPress === 'function')
    .map((n) => n.props.testID);
  expect([...new Set(ids)].filter((id) => id !== 'move-all')).toEqual(['move-cusd_plus', 'move-cusd']);
  // The other dollar moves whole: no amount field.
  await tap(tree, 'move-cusd');
  expect(text(tree)).toContain('Se mueve toda tu posición (US$5.00)');
});

it('hides the other dollar when it holds nothing', async () => {
  api.fetchSmartAccountOffer.mockResolvedValue(ok(offer({ dollar: 'cusd_plus' })));
  api.fetchSmartAccountMovePreview.mockResolvedValue(ok(movePreview({
    assets: [
      { key: 'cusd', symbol: 'cUSD', name: 'cUSD', units: '0', decimals: 18, valueUsd: '0.00', included: true, reason: null },
      { key: 'cusd_plus', symbol: 'cUSD+', name: 'cUSD+', units: '500000000000000000000', decimals: 18, valueUsd: '500.00', included: true, reason: null },
    ],
  })));
  await mount();
  expect(hasTappable(tree, 'move-cusd')).toBe(false);
});
