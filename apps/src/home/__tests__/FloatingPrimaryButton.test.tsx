import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockLogHomeNav = jest.fn();
const mockPay = jest.fn();
let mockPrimary: any = { kind: 'pay', onPress: mockPay };
let mockDrawer: any = { isOpen: false };
let mockConversationHome = true;
let mockBottomInset = 0;

jest.mock('../../config/features', () => ({
  get CONVERSATION_HOME_ENABLED() { return mockConversationHome; },
}));
jest.mock('../../services/homeNavAnalytics', () => ({ logHomeNav: (...args: unknown[]) => mockLogHomeNav(...args) }));
jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: mockBottomInset, left: 0, right: 0 }),
  get initialWindowMetrics() { return { insets: { top: 0, bottom: mockBottomInset, left: 0, right: 0 } }; },
}));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../components/QrPayIcon', () => ({ QrPayIcon: 'QrPayIcon', QrShowIcon: 'QrShowIcon' }));
jest.mock('../AppDrawer', () => ({ useAppDrawer: () => mockDrawer }));
jest.mock('../usePrimaryAction', () => ({ usePrimaryAction: () => mockPrimary }));

import { FloatingPrimaryButton } from '../FloatingPrimaryButton';
import { useFloatingPrimaryInset } from '../useFloatingPrimaryInset';

const shown = async (tab: string) => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<FloatingPrimaryButton tab={tab} />); });
  const found = tree.root.findAll((n) => typeof n.props.onPress === 'function' && typeof n.props.accessibilityLabel === 'string');
  const result = found[0] ?? null;
  return { tree, button: result };
};

beforeEach(() => {
  jest.clearAllMocks();
  mockPrimary = { kind: 'pay', onPress: mockPay };
  mockDrawer = { isOpen: false };
  mockConversationHome = true;
  mockBottomInset = 0;
});

it('floats over the screens opened from the menu, and counts the tap', async () => {
  for (const tab of ['Invest', 'Comprar', 'Profile']) {
    const { tree, button } = await shown(tab);
    expect(button?.props.accessibilityLabel).toBe('Pagar con QR');
    await act(async () => { button?.props.onPress(); });
    await act(async () => tree.unmount());
  }
  expect(mockPay).toHaveBeenCalledTimes(3);
  expect(mockLogHomeNav).toHaveBeenLastCalledWith('floating', 'pay');
});

it('on Inicio the composer has the button, and Cobrar is its own screen with its own controls', async () => {
  expect((await shown('Home')).button).toBeNull();
  expect((await shown('Charge')).button).toBeNull();
});

it('steps away under the open menu, is Cobrar for a business, and is absent when the account can do neither', async () => {
  mockDrawer = { isOpen: true };
  expect((await shown('Invest')).button).toBeNull();
  mockDrawer = { isOpen: false };
  mockPrimary = { kind: 'charge', onPress: jest.fn() };
  expect((await shown('Invest')).button?.props.accessibilityLabel).toBe('Cobrar');
  mockPrimary = null;
  expect((await shown('Invest')).button).toBeNull();
});

describe('room for it at the end of a list', () => {
  let inset = -1;
  const Probe = () => {
    inset = useFloatingPrimaryInset();
    return null;
  };
  const read = async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<Probe />); });
    await act(async () => tree.unmount());
    return inset;
  };

  it('clears the button; nothing where there is no button', async () => {
    // 20 under it, 48 of button, 16 of air.
    expect(await read()).toBe(84);
    // The app's root already keeps screens above the system bar: the inset is not added again.
    mockBottomInset = 34;
    expect(await read()).toBe(84);
    mockPrimary = null;
    expect(await read()).toBe(0);
    mockPrimary = { kind: 'pay', onPress: mockPay };
    mockConversationHome = false;
    expect(await read()).toBe(0);
  });
});
