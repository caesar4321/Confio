import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text} from 'react-native';

let mockDeadline = 0;
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@react-navigation/native', () => ({useFocusEffect: (callback: any) => require('react').useEffect(callback, [callback]), useNavigation: () => ({})}));
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
import {BrebLocationGate} from '../BrebLocationGate';
import {hasBrebLocationPermission, verifyBrebLocation} from '../../../services/brebLocation';
const check = hasBrebLocationPermission as jest.Mock;
const verify = verifyBrebLocation as jest.Mock;
let tree: renderer.ReactTestRenderer;
beforeEach(() => {jest.clearAllMocks(); mockDeadline = 0;});
afterEach(async () => {if (tree) await act(async () => tree.unmount());});

it('waits for the location screen button before requesting permission', async () => {
  check.mockResolvedValue(false);
  verify.mockResolvedValue(Date.now() / 1000 + 900);
  await act(async () => {tree = renderer.create(<BrebLocationGate><Text>ready</Text></BrebLocationGate>);});
  expect(verify).not.toHaveBeenCalled();
  await act(async () => {tree.root.findByType('ActionBar' as any).props.onPrimaryPress();});
  expect(verify).toHaveBeenCalledWith('7:personal_0:1', true);
});

it('uses a silent verification when focusing with permission already granted', async () => {
  check.mockResolvedValue(true);
  verify.mockResolvedValue(Date.now() / 1000 + 900);
  await act(async () => {tree = renderer.create(<BrebLocationGate><Text>ready</Text></BrebLocationGate>);});
  expect(verify).toHaveBeenCalledWith('7:personal_0:1', false);
});

it('does not verify when the permission check resolves after leaving the screen', async () => {
  let resolve!: (allowed: boolean) => void;
  check.mockReturnValue(new Promise<boolean>(done => {resolve = done;}));
  await act(async () => {tree = renderer.create(<BrebLocationGate><Text>ready</Text></BrebLocationGate>);});
  await act(async () => tree.unmount());
  await act(async () => resolve(true));
  expect(verify).not.toHaveBeenCalled();
});
