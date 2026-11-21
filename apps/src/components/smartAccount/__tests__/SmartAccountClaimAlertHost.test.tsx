import { resetMocks } from '../testing/mocks';
import React from 'react';
import { AppState } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import * as service from '../../../services/smartAccount';
import { failedRead, flush, hasTappable, ok, prepared, refused, tap, text } from '../testing/fixtures';

let mockAuthenticated = true;
jest.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: mockAuthenticated }) }));
import { SmartAccountClaimAlertHost } from '../SmartAccountClaimAlertHost';

const api = service as jest.Mocked<typeof service>;
const alert = { beneficiaryName: 'Ana P.', initiatedAt: '2026-11-18T12:00:00Z', executableAt: '2099-05-17T12:00:00Z' };
let tree: renderer.ReactTestRenderer;
let appStateListener: ((s: string) => void) | undefined;
const mount = async () => {
  await act(async () => { tree = renderer.create(<SmartAccountClaimAlertHost />); });
  await flush();
};

beforeEach(() => {
  resetMocks();
  jest.useFakeTimers();
  mockAuthenticated = true;
  appStateListener = undefined;
  jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, cb: any) => {
    appStateListener = cb;
    return { remove: jest.fn() };
  }) as any);
  api.fetchSmartAccountClaimAlert.mockResolvedValue(ok(alert));
  api.prepareClaimCancel.mockResolvedValue(prepared());
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'executed', txHash: '0xabc' });
});
afterEach(async () => {
  if (tree) { await act(async () => tree.unmount()); }
  jest.useRealTimers();
  jest.restoreAllMocks();
});

it('shows nothing when no claim is pending', async () => {
  api.fetchSmartAccountClaimAlert.mockResolvedValue(ok(null));
  await mount();
  expect(tree.toJSON()).toBeNull();
});

it('shows who claimed and the date, with one button that signs the cancel directly', async () => {
  await mount();
  const out = text(tree);
  expect(out).toContain('Ana P. pidió recibir tu Cuenta inteligente');
  expect(out).toContain('Si no firmas, la cuenta pasa el');
  await tap(tree, 'claim-alert-cancel');
  await flush();
  expect(api.prepareClaimCancel).toHaveBeenCalledTimes(1);
  // No confirm step in between: the button IS the signature.
  expect(api.signAndSubmitPrepared).toHaveBeenCalledTimes(1);
  expect(text(tree)).toContain('Pedido cancelado');
});

it('cannot be dismissed with the back button', async () => {
  await mount();
  const modal = tree.root.findAll((n) => typeof n.props.onRequestClose === 'function' && n.props.statusBarTranslucent)[0];
  await act(async () => { modal.props.onRequestClose(); });
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(true);
});

it('goes away only when the server says the claim is gone', async () => {
  await mount();
  api.fetchSmartAccountClaimAlert.mockResolvedValue(ok(null));
  await tap(tree, 'claim-alert-cancel');
  await flush();
  await tap(tree, 'sign-done');
  await flush();
  expect(tree.toJSON()).toBeNull();
});

it('keeps showing when a later read fails', async () => {
  await mount();
  api.fetchSmartAccountClaimAlert.mockResolvedValue(failedRead);
  await act(async () => { jest.advanceTimersByTime(5 * 60 * 1000 + 10); });
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(true);
});

it('steps aside for a while and comes back by itself and on returning to the app', async () => {
  await mount();
  await tap(tree, 'Ahora no. El aviso vuelve en unos minutos');
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(false);
  await act(async () => { jest.advanceTimersByTime(10 * 60 * 1000 + 200); });
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(true);

  await tap(tree, 'Ahora no. El aviso vuelve en unos minutos');
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(false);
  await act(async () => { appStateListener?.('active'); });
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(true);
});

it('shows the server reason and stays when the cancel is refused', async () => {
  api.prepareClaimCancel.mockResolvedValue(refused('Cambia a tu cuenta personal para firmar.'));
  await mount();
  await tap(tree, 'claim-alert-cancel');
  await flush();
  expect(text(tree)).toContain('Cambia a tu cuenta personal para firmar.');
  expect(api.signAndSubmitPrepared).not.toHaveBeenCalled();
  await tap(tree, 'sign-failed-close');
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(true);
});

it('never calls an unknown outcome a failure', async () => {
  api.signAndSubmitPrepared.mockResolvedValue({ status: 'unknown', txHash: null });
  await mount();
  await tap(tree, 'claim-alert-cancel');
  await flush();
  expect(text(tree)).toContain('Estamos confirmando');
  expect(text(tree)).not.toContain('No se realizó');
});

it('asks nothing while signed out', async () => {
  mockAuthenticated = false;
  await mount();
  expect(api.fetchSmartAccountClaimAlert).not.toHaveBeenCalled();
  expect(tree.toJSON()).toBeNull();
});

it('after an executed cancel, a lagging read of the same claim stays hidden', async () => {
  await mount();
  // The server has not caught up yet: still reports the cancelled claim.
  await tap(tree, 'claim-alert-cancel');
  await flush();
  await tap(tree, 'sign-done');
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(false);
  await act(async () => { appStateListener?.('active'); });
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(false);
});

it('a different claim after a cancel always shows', async () => {
  await mount();
  await tap(tree, 'claim-alert-cancel');
  await flush();
  await tap(tree, 'sign-done');
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(false);
  api.fetchSmartAccountClaimAlert.mockResolvedValue(ok({ ...alert, initiatedAt: '2026-11-25T12:00:00Z' }));
  await act(async () => { appStateListener?.('active'); });
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(true);
});

it('the suppression ends once the server reports no claim; the same claim id then shows again', async () => {
  await mount();
  await tap(tree, 'claim-alert-cancel');
  await flush();
  await tap(tree, 'sign-done');
  await flush();
  api.fetchSmartAccountClaimAlert.mockResolvedValue(ok(null));
  await act(async () => { appStateListener?.('active'); });
  await flush();
  api.fetchSmartAccountClaimAlert.mockResolvedValue(ok(alert));
  await act(async () => { appStateListener?.('active'); });
  await flush();
  expect(hasTappable(tree, 'claim-alert-cancel')).toBe(true);
});
