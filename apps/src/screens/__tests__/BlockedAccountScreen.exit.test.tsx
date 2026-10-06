// A ban freezes funds while Confío beats; once the on-chain heartbeat says the
// exit is open, the suspension screen (where a banned user's app always
// opens) must offer it — nothing can clear their ban flag after Confío dies.
import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';

const mockReadHeartbeat = jest.fn();
const mockNavigate = jest.fn();
jest.mock('../../services/emergencyExit/heartbeat', () => ({ readHeartbeat: () => mockReadHeartbeat() }));
jest.mock('../../services/emergencyExit/store', () => ({ emergencyStore: {} }));
jest.mock('../../services/emergencyExit/banSignal', () => ({ isBanSignaled: async () => true }));
jest.mock('../../components/common/BrandFieldBackground', () => ({ BrandFieldBackground: () => null }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: any) => children }));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: mockNavigate, reset: jest.fn(), getState: () => ({ routeNames: [] }) }),
}));
jest.mock('@apollo/client', () => ({ gql: () => ({}) }));

import { BlockedAccountScreen } from '../BlockedAccountScreen';

const texts = (v: ReactTestRenderer) =>
  v.root.findAll((n) => typeof n.props?.children === 'string').map((n) => n.props.children).join(' | ');

const mounted: ReactTestRenderer[] = [];
const render = async (state: string) => {
  mockReadHeartbeat.mockResolvedValue({ state });
  let v!: ReactTestRenderer;
  await act(async () => { v = create(<BlockedAccountScreen />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  mounted.push(v);
  return v;
};

// Unmount so the heartbeat poll's interval never outlives a test.
afterEach(() => {
  mounted.splice(0).forEach((v) => act(() => v.unmount()));
  mockReadHeartbeat.mockReset();
  mockNavigate.mockReset();
});

it.each(['alive', 'quiet', 'unreachable', 'invalid', 'not_configured'])(
  'keeps funds frozen and offers no exit while the heartbeat is %s', async (state) => {
    const t = texts(await render(state));
    expect(t).toContain('no se puede mover');
    expect(t).not.toContain('Salida de emergencia');
  });

it('offers the exit once the chain says it is open', async () => {
  const v = await render('open');
  const t = texts(v);
  expect(t).toContain('la salida de emergencia está abierta');
  const btn = v.root.findAll((n) => n.props?.onPress && texts({ root: n } as any).includes('Salida de emergencia'))[0];
  act(() => btn.props.onPress());
  expect(mockNavigate).toHaveBeenCalledWith('EmergencyExit');
});
