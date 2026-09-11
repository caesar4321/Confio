/**
 * MigrationModal failure-prompt lifecycle (stranded-V1 lockout, 2026-09-10).
 *
 * The modal covers the whole app, so its prompts must never stack, must always
 * leave a way out that really ends the lockout, and nothing started for one
 * identity may act for another — including after logout unmounts the modal.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert, AppState, Modal } from 'react-native';

const mockCheck = jest.fn();
const mockPerform = jest.fn();
const mockSignOut = jest.fn();
const mockOAuth = jest.fn();
let mockAuthState = { isAuthenticated: true, accountContextTick: 0 };

jest.mock('../../services/migrationService', () => {
  class DriveAuthorizationRequiredError extends Error {}
  return {
    DriveAuthorizationRequiredError,
    migrationService: {
      checkNeedsMigration: (...args: any[]) => mockCheck(...args),
      performMigration: (...args: any[]) => mockPerform(...args),
    },
  };
});
// Stubbed only so older versions of the modal still load; the modal must sign
// out through the auth context, never through this service.
jest.mock('../../services/authService', () => ({
  __esModule: true,
  default: { signOut: jest.fn().mockResolvedValue(undefined) },
}));
jest.mock('../../services/oauthStorageService', () => ({
  oauthStorage: { getOAuthSubject: (...args: any[]) => mockOAuth(...args) },
}));
jest.mock('../../config/env', () => ({ GOOGLE_CLIENT_IDS: { production: { web: 'web' } } }));
jest.mock('../../utils/accountManager', () => ({ AccountManager: {} }));
jest.mock('../../apollo/client', () => ({ apolloClient: { reFetchObservableQueries: jest.fn() } }));
jest.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ ...mockAuthState, signOut: (...args: any[]) => mockSignOut(...args) }),
}));

import { MigrationModal } from '../MigrationModal';

const { DriveAuthorizationRequiredError } = jest.requireMock('../../services/migrationService');

let appStateHandler: (state: string) => void = () => {};
const alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
  appStateHandler = handler;
  return { remove: jest.fn() };
}) as any);

const flush = () => act(async () => { await new Promise<void>(resolve => setImmediate(() => resolve())); });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
};
const promptTitle = (call: number) => alertSpy.mock.calls[call][0];
const promptButtons = (call: number) => (alertSpy.mock.calls[call][2] || []) as any[];
const button = (call: number, text: string) => promptButtons(call).find(b => b.text === text);
const modalVisible = (tree: renderer.ReactTestRenderer) => tree.root.findByType(Modal).props.visible;

const render = async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<MigrationModal />); });
  await flush();
  await flush();
  return tree;
};
const switchAccount = async (tree: renderer.ReactTestRenderer, tick: number) => {
  mockAuthState = { isAuthenticated: true, accountContextTick: tick };
  await act(async () => { tree.update(<MigrationModal />); });
};

beforeEach(() => {
  alertSpy.mockClear();
  mockCheck.mockReset().mockResolvedValue({ needsMigration: true });
  mockPerform.mockReset().mockRejectedValue(new DriveAuthorizationRequiredError());
  mockSignOut.mockReset().mockResolvedValue(undefined);
  mockOAuth.mockReset().mockResolvedValue({ provider: 'google', subject: 'sub' });
  mockAuthState = { isAuthenticated: true, accountContextTick: 0 };
});

it('asks to sign in again when the Drive token is gone, never prompting for Drive itself', async () => {
  const tree = await render();

  expect(alertSpy).toHaveBeenCalledTimes(1);
  expect(promptTitle(0)).toBe('Inicia sesión de nuevo');
  expect(promptButtons(0).map(b => b.text)).toEqual(['Cerrar sesión']);
  await act(async () => { button(0, 'Cerrar sesión').onPress(); });
  expect(mockSignOut).toHaveBeenCalledTimes(1);
  await act(async () => { tree.unmount(); });
});

it('ends the lockout when the user signs out from a failure prompt', async () => {
  mockPerform.mockReset().mockResolvedValue(false);
  // What the real context does: its signOut flips isAuthenticated.
  mockSignOut.mockImplementation(async () => {
    mockAuthState = { ...mockAuthState, isAuthenticated: false };
  });
  const tree = await render();
  expect(modalVisible(tree)).toBe(true);

  await act(async () => { await button(0, 'Cerrar sesión').onPress(); });
  await act(async () => { tree.update(<MigrationModal />); });

  expect(modalVisible(tree)).toBe(false);
  await act(async () => { tree.unmount(); });
});

it('does not stack a second prompt when the app returns to the foreground', async () => {
  const tree = await render();

  await act(async () => { appStateHandler('active'); });
  await flush();

  expect(mockCheck).toHaveBeenCalledTimes(1);
  expect(alertSpy).toHaveBeenCalledTimes(1);
  await act(async () => { tree.unmount(); });
});

it('makes an old prompt inert once the user changes, and checks the new user', async () => {
  const tree = await render();

  mockAuthState = { isAuthenticated: false, accountContextTick: 0 };
  await act(async () => { tree.update(<MigrationModal />); });
  mockCheck.mockResolvedValue({ needsMigration: false });
  await switchAccount(tree, 1);
  await flush();

  expect(mockCheck).toHaveBeenCalledTimes(2);
  await act(async () => { button(0, 'Cerrar sesión').onPress(); });
  expect(mockSignOut).not.toHaveBeenCalled();
  await act(async () => { tree.unmount(); });
});

it('drops a check whose identity changed while its OAuth lookup was pending', async () => {
  const lookup = deferred<any>();
  mockOAuth.mockReset()
    .mockReturnValueOnce(lookup.promise)
    .mockResolvedValue({ provider: 'google', subject: 'sub' });
  mockCheck.mockResolvedValue({ needsMigration: false });
  const tree = await render();

  await switchAccount(tree, 1); // turned away: the old check still waits on OAuth
  await act(async () => { lookup.resolve({ provider: 'google', subject: 'old-sub' }); });
  await flush();

  // The old check stopped at its first await; only the new identity was checked.
  expect(mockOAuth).toHaveBeenCalledTimes(2);
  expect(mockCheck).toHaveBeenCalledTimes(1);
  expect(mockCheck.mock.calls[0][1]).toBe('sub');
  await act(async () => { tree.unmount(); });
});

it('drops a pending check when logout unmounts the modal', async () => {
  const lookup = deferred<any>();
  mockOAuth.mockReset().mockReturnValue(lookup.promise);
  const tree = await render();

  await act(async () => { tree.unmount(); });
  await act(async () => { lookup.resolve({ provider: 'google', subject: 'sub' }); });
  await flush();

  expect(mockCheck).not.toHaveBeenCalled();
});

it('keeps the no-OAuth sign-in prompt single and bound to its identity', async () => {
  mockOAuth.mockReset().mockResolvedValue(null);
  const tree = await render();
  expect(promptTitle(0)).toBe('Actualización de Seguridad');

  await act(async () => { appStateHandler('active'); });
  await flush();
  expect(alertSpy).toHaveBeenCalledTimes(1);

  mockOAuth.mockResolvedValue({ provider: 'google', subject: 'sub' });
  mockCheck.mockResolvedValue({ needsMigration: false });
  await switchAccount(tree, 1);
  await flush();
  await act(async () => { await button(0, 'Iniciar Sesión').onPress(); });
  expect(mockSignOut).not.toHaveBeenCalled();
  await act(async () => { tree.unmount(); });
});

it('opens no prompt for a migration that fails after logout unmounts the modal', async () => {
  let failLate!: (error: Error) => void;
  mockPerform.mockReset().mockReturnValue(new Promise((_, reject) => { failLate = reject; }));
  const tree = await render();

  await act(async () => { tree.unmount(); });
  await act(async () => { failLate(new Error('network lost')); });
  await flush();

  expect(alertSpy).not.toHaveBeenCalled();
  expect(mockCheck).toHaveBeenCalledTimes(1);
});

it('never migrates on behalf of an identity that changed while its check ran', async () => {
  const oldCheck = deferred<any>();
  mockCheck.mockReset()
    .mockReturnValueOnce(oldCheck.promise)
    .mockResolvedValue({ needsMigration: false });
  const tree = await render();

  await switchAccount(tree, 1); // turned away: the old check is still running
  await act(async () => { oldCheck.resolve({ needsMigration: true }); });
  await flush();

  expect(mockPerform).not.toHaveBeenCalled();
  expect(mockCheck).toHaveBeenCalledTimes(2); // the denied check ran for the new identity
  await act(async () => { tree.unmount(); });
});

it('hides the modal and re-checks when the account changes mid-migration', async () => {
  const pending = deferred<boolean>();
  mockPerform.mockReset().mockReturnValue(pending.promise);
  const tree = await render();

  mockCheck.mockResolvedValue({ needsMigration: false });
  await switchAccount(tree, 1); // turned away: the old migration is still running
  await act(async () => { pending.resolve(false); });
  await flush();

  expect(alertSpy).not.toHaveBeenCalled();
  expect(mockCheck).toHaveBeenCalledTimes(2);
  await act(async () => { tree.unmount(); });
});

it("does not let an earlier success hide a later identity's migration", async () => {
  jest.useFakeTimers({ doNotFake: ['setImmediate', 'nextTick', 'queueMicrotask'] });
  try {
    const later = deferred<boolean>();
    mockPerform.mockReset().mockResolvedValueOnce(true).mockReturnValueOnce(later.promise);
    const tree = await render(); // the first identity migrates; its hide timer is pending

    await switchAccount(tree, 1); // the next identity starts its own migration
    await flush();
    expect(mockPerform).toHaveBeenCalledTimes(2);

    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(modalVisible(tree)).toBe(true);
    await act(async () => { tree.unmount(); });
  } finally {
    jest.useRealTimers();
  }
});

it('shows a refusal with a way out instead of retrying on a timer', async () => {
  mockPerform.mockReset().mockResolvedValue(false);
  const tree = await render();

  expect(promptTitle(0)).toBe('Actualización Fallida');
  expect(promptButtons(0).map(b => b.text)).toEqual(['Cerrar sesión', 'Reintentar']);
  await act(async () => { button(0, 'Cerrar sesión').onPress(); });
  expect(mockSignOut).toHaveBeenCalledTimes(1);
  expect(mockPerform).toHaveBeenCalledTimes(1);
  await act(async () => { tree.unmount(); });
});
