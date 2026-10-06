import {getDiditErrorMessage, getDiditResultSessionId} from '../diditService';

jest.mock('react-native', () => ({NativeModules: {}, Platform: {OS: 'android'}}));

it('reads the session id from the iOS result and the Android wrapper result', () => {
  expect(getDiditResultSessionId({sessionId: 'ios-1'})).toBe('ios-1');
  expect(getDiditResultSessionId({type: 'completed', session: {sessionId: 'and-1'}})).toBe('and-1');
  expect(getDiditResultSessionId({type: 'cancelled'}, 'created-1')).toBe('created-1');
});

it('reads the failure message from both result shapes', () => {
  expect(getDiditErrorMessage({type: 'failed', errorType: 'networkError', errorMessage: 'ios'})).toBe('ios');
  expect(getDiditErrorMessage({type: 'failed', error: {type: 'networkError', message: 'android'}})).toBe('android');
  expect(getDiditErrorMessage({type: 'failed'})).toBeNull();
});

it('explains a blocked retry in Spanish', () => {
  expect(getDiditErrorMessage({type: 'failed', error: {type: 'retryBlocked', message: 'Retry blocked'}}))
    .toMatch(/máximo de intentos/);
  expect(getDiditErrorMessage({type: 'failed', errorType: 'retryBlocked'})).toMatch(/máximo de intentos/);
});
