import React from 'react';
import { act, create } from 'react-test-renderer';
import { BackHandler } from 'react-native';
jest.mock('../EmergencyExitScreen', () => ({ EmergencyExitScreen: 'EmergencyExitScreen' }));
jest.mock('@react-navigation/native', () => ({
  useFocusEffect: (effect: () => void) => require('react').useEffect(effect, [effect]),
}));
import { EmergencyExitScreen } from '../EmergencyExitScreen';
import { EmergencyRecoveryScreen, emergencyRecoveryOptions } from '../EmergencyRecoveryScreen';

it('uses only the custom header and returns to the lock via close or hardware back', () => {
  const close = jest.fn();
  const remove = jest.fn();
  let back!: () => boolean;
  const spy = jest.spyOn(BackHandler, 'addEventListener').mockImplementation((_event, handler) => {
    back = handler as () => boolean;
    return { remove };
  });
  let view!: ReturnType<typeof create>;
  act(() => { view = create(<EmergencyRecoveryScreen onClose={close} />); });
  expect(emergencyRecoveryOptions.headerShown).toBe(false);
  expect(emergencyRecoveryOptions.gestureEnabled).toBe(false);
  act(() => view.root.findByType(EmergencyExitScreen).props.onClose());
  expect(close).toHaveBeenCalledTimes(1);
  act(() => { expect(back()).toBe(true); });
  expect(close).toHaveBeenCalledTimes(2);
  act(() => view.unmount());
  expect(remove).toHaveBeenCalledTimes(1);
  spy.mockRestore();
});
