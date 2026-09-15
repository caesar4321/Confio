import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Text} from 'react-native';

let mockDeadline = 0;
let mockFocused = true;
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@react-navigation/native', () => ({useFocusEffect: (callback: any) => require('react').useEffect(() => mockFocused ? callback() : undefined, [callback, mockFocused]), useNavigation: () => ({})}));
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
beforeEach(() => {jest.clearAllMocks(); mockDeadline = 0; mockFocused = true;});
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

it('a forced check verifies again despite a cached pass', async () => {
  mockDeadline = Date.now() + 60000; // a cached pass the server may no longer accept
  check.mockResolvedValue(true);
  verify.mockResolvedValue(Date.now() / 1000 + 900);
  await act(async () => {tree = renderer.create(<BrebLocationGate force><Text>ready</Text></BrebLocationGate>);});
  expect(verify).toHaveBeenCalledWith('7:personal_0:1', false);
});

it('an unforced gate trusts a cached pass', async () => {
  mockDeadline = Date.now() + 60000;
  await act(async () => {tree = renderer.create(<BrebLocationGate><Text>ready</Text></BrebLocationGate>);});
  expect(verify).not.toHaveBeenCalled();
  expect(tree.root.findByType(Text).props.children).toBe('ready');
});

it('uses a check completed while blurred when returning to the forced screen', async () => {
  check.mockResolvedValue(true);
  let complete!: (expiry: number) => void;
  verify.mockReturnValue(new Promise<number>(resolve => {complete = resolve;}));
  const screen = () => <BrebLocationGate force><Text>ready</Text></BrebLocationGate>;
  await act(async () => {tree = renderer.create(screen());});
  mockFocused = false;
  await act(async () => {tree.update(screen());});
  mockDeadline = Date.now() + 60000;
  await act(async () => {complete(mockDeadline / 1000);});
  mockFocused = true;
  await act(async () => {tree.update(screen());});
  expect(verify).toHaveBeenCalledTimes(1);
  expect(tree.root.findByType(Text).props.children).toBe('ready');
});

it('ignores an old permission answer after leaving and returning', async () => {
  let oldPermission!: (allowed: boolean) => void;
  check.mockReturnValueOnce(new Promise<boolean>(resolve => {oldPermission = resolve;}));
  check.mockResolvedValue(true);
  verify.mockResolvedValue(Date.now() / 1000 + 900);
  const screen = () => <BrebLocationGate force><Text>ready</Text></BrebLocationGate>;
  await act(async () => {tree = renderer.create(screen());});
  mockFocused = false;
  await act(async () => {tree.update(screen());});
  mockFocused = true;
  await act(async () => {tree.update(screen());});
  await act(async () => {oldPermission(false);});
  expect(tree.root.findByType(Text).props.children).toBe('ready');
  expect(verify).toHaveBeenCalledTimes(1);
});

it('keeps an in-flight check on return instead of starting another', async () => {
  check.mockResolvedValue(true);
  let complete!: (expiry: number) => void;
  verify.mockReturnValue(new Promise<number>(resolve => {complete = resolve;}));
  const screen = () => <BrebLocationGate force><Text>ready</Text></BrebLocationGate>;
  await act(async () => {tree = renderer.create(screen());});
  mockFocused = false;
  await act(async () => {tree.update(screen());});
  mockFocused = true;
  await act(async () => {tree.update(screen());});
  await act(async () => {complete(Date.now() / 1000 + 900);});
  expect(verify).toHaveBeenCalledTimes(1);
  expect(tree.root.findByType(Text).props.children).toBe('ready');
});

it('checks again if the completed pass expires while away', async () => {
  check.mockResolvedValue(true);
  verify.mockImplementation(async () => {
    mockDeadline = Date.now() + 60000;
    return mockDeadline / 1000;
  });
  const screen = () => <BrebLocationGate force><Text>ready</Text></BrebLocationGate>;
  await act(async () => {tree = renderer.create(screen());});
  mockFocused = false;
  await act(async () => {tree.update(screen());});
  mockDeadline = 0;
  mockFocused = true;
  await act(async () => {tree.update(screen());});
  expect(verify).toHaveBeenCalledTimes(2);
  expect(tree.root.findByType(Text).props.children).toBe('ready');
});
