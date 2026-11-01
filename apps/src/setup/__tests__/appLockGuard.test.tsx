import React from 'react';
import { Alert, Modal } from 'react-native';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { alertAboveLock, LockAwareModal, setAppLocked } from '../appLockGuard';

// The guard wraps whatever Alert.alert was when it loaded.
const mockShown = jest.fn();
jest.mock('react-native/Libraries/Alert/Alert', () => ({ __esModule: true, default: { alert: (...args: unknown[]) => mockShown(...args) } }));

const nativeModal = (tree: ReactTestRenderer) =>
  tree.root.findAll(node => node.props.visible !== undefined && node.type !== LockAwareModal)[0];

describe('appLockGuard', () => {
  beforeEach(() => mockShown.mockClear());
  afterEach(() => { act(() => setAppLocked(false)); });

  // protects=no Modal stays above the app lock; fails_when=the export stops being replaced; no_claim=native presentation
  it('replaces every react-native Modal', () => {
    expect(Modal).toBe(LockAwareModal);
  });

  it('hides an open Modal while locked and restores it on unlock', () => {
    const onDismiss = jest.fn();
    let tree!: ReactTestRenderer;
    act(() => { tree = create(<Modal visible onDismiss={onDismiss} />); });
    expect(nativeModal(tree).props.visible).toBe(true);
    act(() => setAppLocked(true));
    expect(nativeModal(tree).props.visible).toBe(false);
    expect(nativeModal(tree).props.onDismiss).toBeUndefined();
    act(() => setAppLocked(false));
    expect(nativeModal(tree).props.visible).toBe(true);
    expect(nativeModal(tree).props.onDismiss).toBe(onDismiss);
  });

  it('holds an Alert until unlock', () => {
    setAppLocked(true);
    Alert.alert('held');
    alertAboveLock('lock');
    expect(mockShown.mock.calls).toEqual([['lock']]);
    setAppLocked(false);
    expect(mockShown.mock.calls).toEqual([['lock'], ['held']]);
  });

  it('drops held Alerts when the session ended', () => {
    setAppLocked(true);
    Alert.alert('held');
    setAppLocked(false, { dropHeldAlerts: true });
    expect(mockShown).not.toHaveBeenCalled();
  });

  it('does not open a closed Modal on unlock', () => {
    let tree!: ReactTestRenderer;
    act(() => { tree = create(<Modal visible={false} />); });
    act(() => setAppLocked(true));
    act(() => setAppLocked(false));
    expect(nativeModal(tree).props.visible).toBe(false);
  });
});
