import React from 'react';
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
const mockReadHeartbeat = jest.fn();
jest.mock('../../services/emergencyExit/heartbeat', () => ({ readHeartbeat: () => mockReadHeartbeat() }));
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { Text, TouchableOpacity } from 'react-native';
import { AppLockScreen } from '../AppLockScreen';

// Salida de emergencia is not a fallback for a failed unlock: it appears on
// the lock screen only once the on-chain heartbeat says the exit is open.
const renderLock = async (state: string) => {
  mockReadHeartbeat.mockResolvedValue({ state });
  const handlers = { onUnlock: jest.fn(), onSignOut: jest.fn(), onEmergencyExit: jest.fn() };
  let view!: ReactTestRenderer;
  await act(async () => { view = create(<AppLockScreen visible {...handlers} />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  const recovery = view.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Salida de emergencia'));
  return { view, recovery, ...handlers };
};

afterEach(() => mockReadHeartbeat.mockReset());

it.each(['alive', 'quiet', 'unreachable', 'invalid', 'not_configured'])(
  'offers no emergency exit while the heartbeat is %s', async (state) => {
    const { view, recovery } = await renderLock(state);
    expect(recovery).toBeUndefined();
    act(() => view.unmount());
  });

it('offers recovery once the exit is open, without unlocking or deleting the session', async () => {
  const { view, recovery, onEmergencyExit, onUnlock, onSignOut } = await renderLock('open');
  act(() => recovery!.props.onPress());
  expect(onEmergencyExit).toHaveBeenCalledTimes(1);
  expect(onUnlock).not.toHaveBeenCalled();
  expect(onSignOut).not.toHaveBeenCalled();
  act(() => view.unmount());
});

it('a failed heartbeat read keeps the exit hidden', async () => {
  mockReadHeartbeat.mockRejectedValue(new Error('offline'));
  let view!: ReactTestRenderer;
  await act(async () => {
    view = create(<AppLockScreen visible onUnlock={jest.fn()} onSignOut={jest.fn()} onEmergencyExit={jest.fn()} />);
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  expect(view.root.findAllByType(Text).some(t => t.props.children === 'Salida de emergencia')).toBe(false);
  act(() => view.unmount());
});
