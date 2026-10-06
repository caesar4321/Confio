import {getDiditErrorMessage, getDiditResultSessionId} from '../diditService';

jest.mock('react-native', () => ({NativeModules: {}, Platform: {OS: 'android'}}));

it('reads the session id from the iOS result and the Android wrapper result', () => {
  expect(getDiditResultSessionId({sessionId: 'ios-1'})).toBe('ios-1');
  expect(getDiditResultSessionId({type: 'completed', session: {sessionId: 'and-1'}})).toBe('and-1');
  expect(getDiditResultSessionId({type: 'cancelled'}, 'created-1')).toBe('created-1');
});

it('explains known failures in Spanish from both result shapes', () => {
  expect(getDiditErrorMessage({type: 'failed', errorType: 'networkError', errorMessage: 'Network error'}))
    .toMatch(/conexión a internet/);
  expect(getDiditErrorMessage({type: 'failed', error: {type: 'sessionExpired', message: 'Session expired'}}))
    .toMatch(/expiró/);
  expect(getDiditErrorMessage({type: 'failed', error: {type: 'retryBlocked', message: 'Retry blocked'}}))
    .toMatch(/máximo de intentos/);
});

it('never passes the SDK\'s English text through', () => {
  expect(getDiditErrorMessage({type: 'failed', errorType: 'unknown', errorMessage: 'Something broke'})).toBeNull();
  expect(getDiditErrorMessage({type: 'failed', error: {type: 'unknown', message: 'Timed out waiting for SDK'}})).toBeNull();
  expect(getDiditErrorMessage({type: 'failed'})).toBeNull();
});
