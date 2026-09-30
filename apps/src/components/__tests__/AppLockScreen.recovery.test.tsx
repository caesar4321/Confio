import React from 'react';
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
import { act, create } from 'react-test-renderer';
import { Text, TouchableOpacity } from 'react-native';
import { AppLockScreen } from '../AppLockScreen';

it('offers recovery without unlocking or deleting the saved session', () => {
  const onUnlock = jest.fn(), onSignOut = jest.fn(), onEmergencyExit = jest.fn();
  let view: ReturnType<typeof create>;
  act(() => { view = create(<AppLockScreen visible onUnlock={onUnlock} onSignOut={onSignOut} onEmergencyExit={onEmergencyExit} />); });
  const recovery = view!.root.findAllByType(TouchableOpacity).find(node =>
    node.findAllByType(Text).some(text => text.props.children === 'Salida de emergencia'))!;
  act(() => recovery.props.onPress());
  expect(onEmergencyExit).toHaveBeenCalledTimes(1);
  expect(onUnlock).not.toHaveBeenCalled();
  expect(onSignOut).not.toHaveBeenCalled();
  act(() => view!.unmount());
});
