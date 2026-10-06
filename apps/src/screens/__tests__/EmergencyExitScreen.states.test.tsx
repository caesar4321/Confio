// What the Emergency Exit screen shows for each on-chain heartbeat state.
// The heartbeat is the only thing that opens the exit (§ Phase 3 of
// docs/plans/salida-de-emergencia-design.md); the screen must never offer
// "Mover mi dinero" unless the chain says the exit is open.
import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';

const mockReadHeartbeat = jest.fn();
jest.mock('../../services/emergencyExit/heartbeat', () => ({
  readHeartbeat: () => mockReadHeartbeat(),
  isConfioAlive: (e: any) => e?.name === 'ConfioAliveError',
}));
const mockExecute = jest.fn();
jest.mock('../../services/emergencyExit/bscExit', () => ({
  executeBscExit: (p: any) => mockExecute(p),
  planBscExit: jest.fn(async () => ({ steps: [], bnbWei: 0n })),
  estimateBscExitGasWei: jest.fn(async () => 0n),
  installEmergencyBscTransport: () => () => {},
  BUNDLED_VAULT_ADDRESS: '0x' + '33'.repeat(20),
  BUNDLED_CUSD_ADDRESS: '',
}));
jest.mock('../../services/emergencyExit/store', () => ({
  emergencyStore: { get: async () => null, set: async () => {}, del: async () => {} },
}));
jest.mock('../../services/emergencyExit/accountRoster', () => ({
  rosterAccountKey: () => 'personal_0',
  getAccountRoster: async () => null,
  exitableAccounts: () => [{ type: 'personal', index: 0, name: 'Personal' }],
}));
jest.mock('../../services/authService', () => ({
  AuthService: { getInstance: () => ({ getActiveAccountContext: async () => ({ type: 'personal', index: 0 }) }) },
}));
jest.mock('../../services/secureDeterministicWallet', () => ({
  evmAccountKey: () => 'k',
  getEvmAddressForDisplay: async () => '0x' + '11'.repeat(20),
  getActiveEvmWallet: jest.fn(async () => ({ address: '0x' + '11'.repeat(20), privKeyHex: '00' })),
  deriveAddressesForContext: async () => ({ evm: '0x' + '11'.repeat(20) }),
}));
jest.mock('../../services/biometricAuthService', () => ({
  biometricAuthService: { authenticateEmergencyExit: jest.fn(async () => true) },
}));
jest.mock('../../services/evmWallet', () => ({ isOutcomeUnknown: () => false }));
jest.mock('../../components/AddressScannerModal', () => ({ AddressScannerModal: () => null }));
jest.mock('../../components/LoadingOverlay', () => ({ LoadingOverlay: () => null }));
jest.mock('../../components/common/BrandFieldBackground', () => ({ BrandFieldBackground: () => null }));
jest.mock('react-native-qrcode-svg', () => () => null);
jest.mock('@react-native-clipboard/clipboard', () => ({ setString: jest.fn(), getString: async () => '' }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaView: ({ children }: any) => children,
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ goBack: jest.fn(), navigate: jest.fn() }),
}));

import { EmergencyExitScreen } from '../EmergencyExitScreen';

const NOW = 1_900_000_000;
const DAY = 86_400;

const textOf = (view: ReactTestRenderer): string =>
  view.root
    .findAll((n) => typeof n.props?.children === 'string' || Array.isArray(n.props?.children))
    .map((n) => [].concat(n.props.children).filter((c) => typeof c === 'string' || typeof c === 'number').join(''))
    .join(' | ');

const mounted: ReactTestRenderer[] = [];
const render = async (status: any): Promise<ReactTestRenderer> => {
  mockReadHeartbeat.mockResolvedValue(status);
  let view!: ReactTestRenderer;
  await act(async () => { view = create(<EmergencyExitScreen />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  mounted.push(view);
  return view;
};

afterEach(() => {
  mounted.splice(0).forEach((v) => act(() => v.unmount()));
  mockReadHeartbeat.mockReset();
});

it('alive: explains the safeguard, shows the last signal, offers no exit', async () => {
  const view = await render({
    state: 'alive', chainNowSec: NOW, lastBeatSec: NOW - 3 * 3600, silenceSec: 14 * DAY,
    opensAtSec: NOW - 3 * 3600 + 14 * DAY,
  });
  const t = textOf(view);
  expect(t).toContain('Tu respaldo si Confío deja de operar');
  expect(t).toContain('Señal de Confío');
  expect(t).toContain('hace 3 h');
  expect(t).toContain('Cómo funciona');
  expect(t).toContain('Ni soporte ni nadie puede abrirte esta salida antes de tiempo');
  expect(t).toContain('Algorand no forman parte');
  expect(t).not.toContain('Mover mi dinero');
  expect(t).not.toMatch(/72 horas|Confío Face|espera de seguridad/i);
});

it('quiet: counts down to the opening date, still no exit', async () => {
  const view = await render({
    state: 'quiet', chainNowSec: NOW, lastBeatSec: NOW - 5 * DAY, silenceSec: 14 * DAY,
    opensAtSec: NOW + 9 * DAY,
  });
  const t = textOf(view);
  expect(t).toContain('Confío no da señales');
  expect(t).toContain('9 días');
  expect(t).not.toContain('Mover mi dinero');
});

it('open: goes straight into the wizard', async () => {
  const view = await render({
    state: 'open', chainNowSec: NOW, lastBeatSec: NOW - 15 * DAY, silenceSec: 14 * DAY,
    opensAtSec: NOW - DAY,
  });
  const t = textOf(view);
  expect(t).toContain('La salida está abierta');
  expect(t).toContain('PASO 1 DE 4');
  expect(t).not.toContain('Cómo funciona');
});

it('states the silence period the chain reports, not a hardcoded one', async () => {
  const view = await render({
    state: 'alive', chainNowSec: NOW, lastBeatSec: NOW - 3600, silenceSec: 30 * DAY,
    opensAtSec: NOW - 3600 + 30 * DAY,
  });
  const t = textOf(view);
  expect(t).toContain('30 días sin señal de Confío');
  expect(t).not.toContain('14 días');
});

it('never says Confío is fine when the heartbeat read itself throws', async () => {
  mockReadHeartbeat.mockRejectedValue(new TypeError('null block'));
  let view!: ReactTestRenderer;
  await act(async () => { view = create(<EmergencyExitScreen />); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  mounted.push(view);
  const t = textOf(view);
  expect(t).not.toContain('funciona con normalidad');
  expect(t).toContain('Sin conexión con la blockchain');
});

it.each(['not_configured', 'invalid', 'unreachable'])('%s: closed, never the wizard', async (state) => {
  const view = await render({ state });
  const t = textOf(view);
  expect(t).not.toContain('PASO 1 DE 4');
  expect(t).not.toContain('Mover mi dinero');
});

describe('the gate closing mid-exit', () => {
  const OPEN = {
    state: 'open', chainNowSec: NOW, lastBeatSec: NOW - 15 * DAY, silenceSec: 14 * DAY, opensAtSec: NOW - DAY,
  };
  // The TouchableOpacity element itself (its inner components repeat onPress), and a
  // disabled button is a test failure — the user couldn't tap it either.
  const touchables = (view: ReactTestRenderer) =>
    view.root.findAll((n) => (n.type as any)?.render?.displayName === 'TouchableOpacity'
      && typeof n.props?.onPress === 'function');
  const press = async (view: ReactTestRenderer, label: string) => {
    const hit = touchables(view).filter((n) => n.findAll((c) => c.props?.children === label).length > 0).pop();
    if (!hit) throw new Error(`no button "${label}"`);
    if (hit.props.disabled) throw new Error(`button "${label}" is disabled`);
    await act(async () => { await hit.props.onPress(); });
  };
  const runExit = async (gateState: string, onView?: (v: ReactTestRenderer) => void) => {
    mockExecute.mockRejectedValue(Object.assign(new Error('closed'), {
      name: 'ConfioAliveError',
      status: { state: gateState },
      partialResult: {
        completed: ['redeemCusdPlus'], txids: { redeemCusdPlus: '0x' + 'ab'.repeat(32) }, degraded: [],
        sentNow: ['redeemCusdPlus'], usdtToDest: '0', unresolved: [],
      },
    }));
    if (!mockReadHeartbeat.getMockImplementation()) mockReadHeartbeat.mockResolvedValue(OPEN);
    let view!: ReactTestRenderer;
    await act(async () => { view = create(<EmergencyExitScreen />); });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    mounted.push(view);
    onView?.(view);
    await press(view, 'Continuar');
    const input = view.root.findAll((n) => n.props?.placeholder === '0x…')[0];
    await act(async () => { input.props.onChangeText('0x' + '22'.repeat(20)); });
    await press(view, 'Continuar');
    const boxes = touchables(view).filter((n) => n.findAll((c) => c.props?.name === 'square').length === 1);
    expect(boxes).toHaveLength(4);
    for (const row of boxes) {
      await act(async () => { row.props.onPress(); });
    }
    await press(view, 'Continuar');
    await press(view, 'Mover mi dinero');
    return textOf(view);
  };

  it('an unreadable gate after a leg landed is an error with a working retry, not "Confío volvió"', async () => {
    // After the failure the phone also can't read the heartbeat (no data).
    mockReadHeartbeat.mockResolvedValueOnce(OPEN).mockResolvedValue({ state: 'unreachable' });
    let view!: ReactTestRenderer;
    const t = await runExit('unreachable', (v) => { view = v; });
    expect(t).toContain('No pudimos leer la señal de Confío');
    expect(t).toContain('revisa tu conexión — puedes reintentar'); // one retry phrase, not two
    expect(t).not.toContain('se cerró a mitad');
    mockExecute.mockClear();
    await press(view, 'Reintentar'); // throws if disabled
    expect(mockExecute).toHaveBeenCalledTimes(1); // re-read the gate, then retried
  });

  it('Confío beating again after a leg landed shows the "closed midway" receipt', async () => {
    const t = await runExit('alive');
    expect(t).toContain('La salida se cerró a mitad');
    expect(t).not.toContain('Listo');
  });
});
