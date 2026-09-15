import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text} from 'react-native';

let mockDeadline = 0;
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@react-navigation/native', () => ({useFocusEffect: () => {}, useNavigation: () => ({})}));
jest.mock('../../../contexts/AccountContext', () => ({useAccount: () => ({activeAccount: {id: 'personal_0'}})}));
jest.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({profileData: {userProfile: {id: '7'}}, accountContextTick: 1, isAuthenticated: true}),
}));
jest.mock('../../ramps/RampActionBar', () => ({RampActionBar: 'ActionBar'}));
jest.mock('../../ramps/RampHero', () => ({RampHero: 'Hero'}));
jest.mock('../../ramps/RampReveal', () => ({RampReveal: ({children}: any) => children}));
jest.mock('../../ramps/RampStepHeader', () => ({RampStepHeader: 'Step'}));
jest.mock('../../../services/brebLocation', () => ({
  BREB_PERMISSION_ERROR: 'BREB_LOCATION_PERMISSION',
  brebLocationSupported: () => true,
  hasBrebLocationPermission: jest.fn(),
  verifyBrebLocation: jest.fn(),
  brebLocationPassValid: () => Date.now() < mockDeadline,
  brebLocationPassRemainingMs: () => Math.max(0, mockDeadline - Date.now()),
}));
import {useBrebLocationPass} from '../BrebLocationGate';

function Probe({enabled = true}: {enabled?: boolean}) {
  return <Text>{useBrebLocationPass(enabled) ? 'shown' : 'hidden'}</Text>;
}
const shown = (tree: renderer.ReactTestRenderer) => tree.root.findByType(Text).props.children;

it('follows a renewed pass to its new expiry', async () => {
  jest.useFakeTimers({doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask']});
  let tree: renderer.ReactTestRenderer | undefined;
  try {
    mockDeadline = Date.now() + 60000;
    await act(async () => { tree = renderer.create(<Probe />); });
    expect(shown(tree!)).toBe('shown');
    mockDeadline = Date.now() + 120000; // renewed before the first deadline
    await act(async () => { jest.advanceTimersByTime(61000); });
    expect(shown(tree!)).toBe('shown');
    await act(async () => { jest.advanceTimersByTime(61000); });
    expect(shown(tree!)).toBe('hidden');
  } finally {
    if (tree) await act(async () => { tree!.unmount(); });
    jest.useRealTimers();
  }
});

it('never reports a pass when disabled', async () => {
  mockDeadline = Date.now() + 60000;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe enabled={false} />); });
  expect(shown(tree)).toBe('hidden');
  await act(async () => { tree.unmount(); });
});
