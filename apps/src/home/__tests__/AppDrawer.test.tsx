// The menu of the conversation home: the one place for the person's money,
// the product screens, and the profile with the account switcher in place.
import React from 'react';
import { Keyboard, Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
const mockOpenAssistant = jest.fn();
const mockLogHomeNav = jest.fn();
let mockAccount: any = { id: 'personal_0', type: 'personal' };
let mockPeekBadge: string | null = null;
let mockUnread = { inbox: 0, direct: 0, requests: 0 };

jest.mock('../../services/homeNavAnalytics', () => ({ logHomeNav: (...args: unknown[]) => mockLogHomeNav(...args) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { navigate: (...args: unknown[]) => mockNavigate(...args) },
}));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));
jest.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, userProfile: { firstName: 'Ana' } }),
}));
jest.mock('../../contexts/HeaderContext', () => ({ useHeader: () => ({ currentAccountAvatar: 'A' }) }));
jest.mock('../../assistant/AssistantContext', () => ({ useOptionalAssistant: () => ({ open: mockOpenAssistant }) }));
jest.mock('../../services/communityPeek', () => ({
  useCommunityPeek: () => ({}),
  peekBadge: () => mockPeekBadge,
}));
jest.mock('../../apollo/queries', () => ({ GET_MESSAGE_INBOX_UNREAD_COUNT: 'inbox', GET_DIRECT_UNREAD_SUMMARY: 'direct' }));
jest.mock('@apollo/client', () => ({
  useQuery: (query: string) => (query === 'inbox'
    ? { data: { messageInboxUnreadCount: mockUnread.inbox } }
    : { data: { directUnreadSummary: { unreadMessages: mockUnread.direct, requests: mockUnread.requests } } }),
}));

import { AppDrawerProvider, useAppDrawer } from '../AppDrawer';
import {
  requestHomeMenu, sharedHomeMoneyStore, useHomeMoneyStore, type HomeMoney, type HomeMoneyStore,
} from '../homeMoneyStore';

const handlers = {
  toggle: jest.fn(), currency: jest.fn(), refresh: jest.fn(), pull: jest.fn(), month: jest.fn(), dollar: jest.fn(), smart: jest.fn(),
  send: jest.fn(), receive: jest.fn(), switchAccount: jest.fn(), createBusiness: jest.fn(),
};
const money = (over: Partial<HomeMoney> = {}): HomeMoney => ({
  ready: true,
  total: 'US$254,30',
  masked: false,
  canToggle: true,
  toggleBalance: handlers.toggle,
  currencyCode: 'USD',
  currencyHint: 'Mostrar en bolivianos',
  toggleCurrency: handlers.currency,
  refresh: handlers.refresh,
  pull: handlers.pull,
  accounts: [
    { id: 'personal_0', name: 'Ana Pérez', kind: 'Personal', avatar: 'A', selected: true },
    { id: 'business_1_0', name: 'Panadería', kind: 'Negocio', avatar: 'P', selected: false },
  ],
  switchAccount: handlers.switchAccount,
  createBusiness: handlers.createBusiness,
  month: { kind: 'month', summary: { year: 2026, month: 11, current: { incomeUsd: '340', spendingUsd: '185' } } as any },
  openMonth: handlers.month,
  tiles: [
    { key: 'dollar', label: 'Confío Dollar+', amount: 'US$210,10', accessibilityLabel: 'Confío Dollar+, US$210,10', onPress: handlers.dollar },
    { key: 'smart', label: 'Cuenta inteligente', amount: null, offerLabel: 'Activar',
      accessibilityLabel: 'Cuenta inteligente, pagos e inversión automáticos', onPress: handlers.smart },
  ],
  openSmart: handlers.smart,
  actions: [
    { id: 'send', label: 'Enviar', icon: 'arrow-up-right', filled: true, onPress: handlers.send },
    { id: 'receive', label: 'Recibir', icon: 'arrow-down-left', filled: false, onPress: handlers.receive },
  ],
  notice: null,
  ...over,
});

let drawer!: ReturnType<typeof useAppDrawer>;
let store!: HomeMoneyStore;
// What the home inside this shell has published by the time the menu opens.
let published: HomeMoney | null = null;
const publishHomeMoney = (next: HomeMoney) => { published = next; };
const Probe = () => {
  drawer = useAppDrawer();
  store = useHomeMoneyStore();
  return null;
};

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const labels = (tree: renderer.ReactTestRenderer) => tree.root
  .findAll((n) => typeof n.props.accessibilityLabel === 'string' && typeof n.props.onPress === 'function')
  .map((n) => n.props.accessibilityLabel as string);
const button = (tree: renderer.ReactTestRenderer, label: string | RegExp) => {
  const found = tree.root.findAll((n) => typeof n.props.accessibilityLabel === 'string' && typeof n.props.onPress === 'function'
    && (typeof label === 'string' ? n.props.accessibilityLabel === label : label.test(n.props.accessibilityLabel)));
  if (!found.length) throw new Error(`no button ${label}; have ${labels(tree).join(' | ')}`);
  return found[0];
};
const press = async (tree: renderer.ReactTestRenderer, label: string | RegExp) => {
  await act(async () => { button(tree, label).props.onPress(); });
};
const lastNavigation = () => mockNavigate.mock.calls[mockNavigate.mock.calls.length - 1];
const toTab = (screen: string) => ['Main', { screen: 'BottomTabs', params: { screen, params: undefined }, pop: true }];

async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AppDrawerProvider><Probe /></AppDrawerProvider>); });
  if (published) {
    const next = published;
    await act(async () => { store.publish(next); });
  }
  return tree;
}
async function openDrawer(tree: renderer.ReactTestRenderer) {
  await act(async () => { drawer.open(); });
  // The reduce-motion check resolves before the slide starts.
  await act(async () => { await Promise.resolve(); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockAccount = { id: 'personal_0', type: 'personal' };
  mockPeekBadge = null;
  mockUnread = { inbox: 0, direct: 0, requests: 0 };
  published = null;
});

describe('opening', () => {
  it('draws nothing until it is opened', async () => {
    const tree = await mount();
    expect(texts(tree)).toEqual([]);
    expect(drawer.isOpen).toBe(false);
    await act(async () => tree.unmount());
  });

  it('offers the conversation a drag to pull it open', async () => {
    const tree = await mount();
    expect(typeof drawer.openGesture.onMoveShouldSetResponder).toBe('function');
    await act(async () => tree.unmount());
  });

  it('puts the keyboard away: the menu covers the field the person was typing in', async () => {
    const dismiss = jest.spyOn(Keyboard, 'dismiss').mockImplementation(() => {});
    publishHomeMoney(money());
    const tree = await mount();
    expect(dismiss).not.toHaveBeenCalled();
    await openDrawer(tree);
    expect(dismiss).toHaveBeenCalledTimes(1);
    dismiss.mockRestore();
    await act(async () => tree.unmount());
  });

  it('while it is open the screen behind is not there for a screen reader, and the escape gesture closes it', async () => {
    publishHomeMoney(money());
    const tree = await mount();
    const behind = () => tree.root.findAll((n) => typeof n.props.accessibilityElementsHidden === 'boolean')[0];
    expect(behind().props.accessibilityElementsHidden).toBe(false);
    await openDrawer(tree);
    expect(behind().props.accessibilityElementsHidden).toBe(true);
    expect(behind().props.importantForAccessibility).toBe('no-hide-descendants');
    const overlay = tree.root.findAll((n) => n.props.accessibilityViewIsModal === true)[0];
    await act(async () => { overlay.props.onAccessibilityEscape(); });
    expect(drawer.isOpen).toBe(false);
    await act(async () => tree.unmount());
  });

  it('"muéstrame mi dinero" from the assistant opens it, on Inicio', async () => {
    publishHomeMoney(money());
    const tree = await mount();
    expect(drawer.isOpen).toBe(false);
    await act(async () => { expect(requestHomeMenu()).toBe(true); });
    expect(drawer.isOpen).toBe(true);
    expect(lastNavigation()).toEqual(toTab('Home'));
    await act(async () => { tree.unmount(); });
    // Nothing mounted to show it: the caller falls back to its own Inicio.
    expect(requestHomeMenu()).toBe(false);
  });

  it('a Cuenta inteligente context has no menu to open', async () => {
    mockAccount = { id: 'smart_0', type: 'smart', index: 0 };
    const tree = await mount();
    expect(requestHomeMenu()).toBe(false);
    await act(async () => tree.unmount());
  });

  it('closes on an account switch', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    mockAccount = { id: 'business_1_0', type: 'business' };
    await act(async () => { tree.update(<AppDrawerProvider><Probe /></AppDrawerProvider>); });
    expect(drawer.isOpen).toBe(false);
    await act(async () => tree.unmount());
  });
});

describe('the money block: the one place for the person\'s money', () => {
  it('total, month, wallets and the two verbs; and it asks for the balances again when it opens', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    const all = texts(tree);
    expect(all).toEqual(expect.arrayContaining([
      'Mi dinero', 'US$254,30', 'Entró US$340 · Salió US$185', 'Confío Dollar+', 'US$210,10', 'Enviar', 'Recibir',
    ]));
    // Cuenta inteligente is an offer, never a balance: "Activar", and no amount of its own.
    expect(all).toContain('Activar');
    expect(handlers.refresh).toHaveBeenCalledTimes(1);
    // Nothing to open behind the total: it is not a button.
    expect(labels(tree).some((l) => l.startsWith('Mi dinero'))).toBe(false);

    await press(tree, 'Ocultar saldo');
    await press(tree, 'Mostrar en bolivianos');
    expect(handlers.toggle).toHaveBeenCalledTimes(1);
    expect(handlers.currency).toHaveBeenCalledTimes(1);
    // The eye and the currency change what is shown here: the menu stays open.
    expect(drawer.isOpen).toBe(true);

    // A door closes the menu and then acts, and is counted.
    await press(tree, 'Enviar');
    expect(handlers.send).toHaveBeenCalledTimes(1);
    expect(drawer.isOpen).toBe(false);
    expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', 'send');
    await act(async () => tree.unmount());
  });

  it('reopened right away it does not ask for the balances twice, nor when the figures change while it is open', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    await act(async () => { drawer.close(); });
    await openDrawer(tree);
    expect(handlers.refresh).toHaveBeenCalledTimes(1);
    // A new snapshot (the eye, a balance tick) brings a new refresh function: not a reason to ask again.
    const later = jest.fn();
    await act(async () => { store.publish(money({ total: 'US$300,00', refresh: later })); });
    expect(later).not.toHaveBeenCalled();
    expect(handlers.refresh).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it('pulled down, it asks for the balances like the old Inicio and spins until they are back', async () => {
    let back!: () => void;
    handlers.pull.mockImplementationOnce(() => new Promise<void>((resolve) => { back = resolve; }));
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    const control = () => tree.root.findAll((n) => !!n.props?.refreshControl)[0].props.refreshControl.props;
    expect(control().refreshing).toBe(false);
    await act(async () => { void control().onRefresh(); });
    expect(handlers.pull).toHaveBeenCalledTimes(1);
    expect(control().refreshing).toBe(true);
    await act(async () => { back(); });
    expect(control().refreshing).toBe(false);
    // A pull that fails ends the spinner too, and the next pull asks again.
    handlers.pull.mockImplementationOnce(() => Promise.reject(new Error('sin red')));
    await act(async () => { await control().onRefresh(); });
    expect(control().refreshing).toBe(false);
    expect(handlers.pull).toHaveBeenCalledTimes(2);
    // Balances that never come back do not leave the spinner on.
    jest.useFakeTimers();
    try {
      handlers.pull.mockImplementationOnce(() => new Promise<void>(() => {}));
      await act(async () => { void control().onRefresh(); });
      expect(control().refreshing).toBe(true);
      await act(async () => { jest.advanceTimersByTime(12_000); });
      expect(control().refreshing).toBe(false);
    } finally {
      jest.useRealTimers();
    }
    await act(async () => tree.unmount());
  });

  it('the wallet strip keeps its own sideways drag: it scrolls, it does not push the menu away', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    const overlay = tree.root.findAll((n) => n.props.accessibilityViewIsModal === true)[0];
    const strip = tree.root.findAll((n) => typeof n.props.onTouchStart === 'function'
      && typeof n.props.onTouchCancel === 'function')[0];
    // One finger, 60 points to the left and barely down.
    const event = { nativeEvent: {}, touchHistory: { numberActiveTouches: 1, indexOfSingleActiveTouch: 0, mostRecentTimeStamp: 2,
      touchBank: [{ touchActive: true, startPageX: 160, startPageY: 100, startTimeStamp: 1, currentPageX: 100,
        currentPageY: 102, currentTimeStamp: 2, previousPageX: 160, previousPageY: 100, previousTimeStamp: 1 }] } };
    // (The capture pass is where the responder measures the move.)
    expect(overlay.props.onMoveShouldSetResponderCapture(event)).toBe(false);
    // A finger down anywhere else: a leftward drag is the menu's.
    overlay.props.onTouchStartCapture();
    expect(overlay.props.onMoveShouldSetResponder(event)).toBe(true);
    // Down on the strip: the same drag is left to the strip, until the finger lifts.
    overlay.props.onTouchStartCapture();
    strip.props.onTouchStart();
    expect(overlay.props.onMoveShouldSetResponder(event)).toBe(false);
    strip.props.onTouchEnd();
    expect(overlay.props.onMoveShouldSetResponder(event)).toBe(true);
    // And the strip is what holds the wallets.
    expect(strip.findAll((n) => n.props.accessibilityLabel === 'Confío Dollar+, US$210,10').length).toBeGreaterThan(0);
    // Wallets that all fit do not scroll: there a drag to the left closes the menu like anywhere else.
    const scroller = strip.findAll((n) => n.props.horizontal === true && typeof n.props.onContentSizeChange === 'function')[0];
    await act(async () => {
      scroller.props.onLayout({ nativeEvent: { layout: { width: 300 } } });
      scroller.props.onContentSizeChange(256, 60);
    });
    expect(tree.root.findAll((n) => typeof n.props.onTouchStart === 'function'
      && typeof n.props.onTouchCancel === 'function')).toHaveLength(0);
    // Sliding away, it takes no more taps.
    expect(tree.root.findAll((n) => n.props.accessibilityViewIsModal === true)[0].props.pointerEvents).toBe('box-none');
    await act(async () => { drawer.close(); });
    expect(tree.root.findAll((n) => n.props.accessibilityViewIsModal === true)[0].props.pointerEvents).toBe('none');
    await act(async () => tree.unmount());
  });

  it('before the first balances answer the total is a dash, never a zero or a mask', async () => {
    const tree = await openDrawer(await mount());
    expect(texts(tree)).toContain('—');
    expect(texts(tree).join('')).not.toMatch(/US\$|•/);
    await act(async () => tree.unmount());
  });

  it('a hidden balance masks the total and the month line', async () => {
    publishHomeMoney(money({ masked: true, total: '••••••' }));
    const tree = await openDrawer(await mount());
    const all = texts(tree);
    expect(all).toContain('••••••');
    expect(all).toContain('Entró •••• · Salió ••••');
    expect(all.join(' ')).not.toContain('340');
    expect(button(tree, 'Mostrar saldo')).toBeTruthy();
    await act(async () => tree.unmount());
  });

  it('no eye for an employee without viewBalance, no currency switch where there is no local currency', async () => {
    mockAccount = { id: 'business_1_0', type: 'business', isEmployee: true, business: { name: 'Panadería' } };
    publishHomeMoney(money({ masked: true, total: '••••••', canToggle: false, currencyCode: null, tiles: [], openSmart: null, actions: [] }));
    const tree = await openDrawer(await mount());
    expect(labels(tree).some((l) => /saldo$/.test(l))).toBe(false);
    expect(labels(tree)).not.toContain('Mostrar en bolivianos');
    const all = texts(tree);
    expect(all).not.toContain('Cuenta inteligente');
    expect(all).not.toContain('Enviar');
    expect(all).toContain('Panadería');
    expect(labels(tree)).toContain('Perfil y ajustes de Panadería, Empleado');
    await act(async () => tree.unmount());
  });

  it('before the first balances answer the strip keeps its place and the Cuenta inteligente row is already there', async () => {
    // A refresh or a late first answer must not push the rows below down.
    publishHomeMoney(money({ tiles: [] }));
    const tree = await openDrawer(await mount());
    const all = texts(tree);
    expect(all.filter((t) => t === '—')).toHaveLength(2);
    expect(all).toContain('Cuenta inteligente');
    await press(tree, 'Cuenta inteligente');
    expect(handlers.smart).toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it('each home shell has its own figures: a second one, stacked on top, never touches the first', async () => {
    publishHomeMoney(money());
    const first = await openDrawer(await mount());
    const firstStore = store;
    expect(firstStore).not.toBe(sharedHomeMoneyStore);
    publishHomeMoney(money({ total: 'US$9,99' }));
    const second = await mount();
    expect(store).not.toBe(firstStore);
    await act(async () => { second.unmount(); });
    expect(firstStore.get().total).toBe('US$254,30');
    expect(texts(first)).toContain('US$254,30');
    await act(async () => { first.unmount(); });
  });
});

describe('the screens', () => {
  it('"Inicio" is the way back to the conversation from every other screen', async () => {
    // On iOS there is no hardware back: without this row Invertir, Comunidad,
    // Comprar and Perfil would have no labelled way home.
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    expect(texts(tree)).toEqual(expect.arrayContaining(['Inicio', 'Invertir', 'Comunidad', 'Comprar', 'Mensajes']));
    await press(tree, 'Inicio');
    expect(lastNavigation()).toEqual(toTab('Home'));
    expect(drawer.isOpen).toBe(false);
    expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', 'home');
    await act(async () => tree.unmount());
  });

  it('opens the product screens as the same tab routes, and says which door was used', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    await press(tree, 'Comprar');
    expect(lastNavigation()).toEqual(toTab('Comprar'));

    await openDrawer(tree);
    await press(tree, 'Comunidad');
    expect(lastNavigation()[1].params.screen).toBe('Invest');
    expect(lastNavigation()[1].params.params.segment).toBe('community');

    await openDrawer(tree);
    await press(tree, 'Cuenta inteligente');
    expect(handlers.smart).toHaveBeenCalledTimes(1);

    await openDrawer(tree);
    await press(tree, 'Confío Dollar+, US$210,10');
    expect(handlers.dollar).toHaveBeenCalledTimes(1);
    expect(mockLogHomeNav.mock.calls.map(([, target]) => target)).toEqual(['comprar', 'community', 'smart_account', 'wallet_dollar']);
    await act(async () => tree.unmount());
  });

  it('"Invitar y ganar" and "El fundador" close the menu, apart from the product screens, each with its own screen', async () => {
    publishHomeMoney(money());
    let tree = await openDrawer(await mount());
    const rows = texts(tree);
    expect(rows.indexOf('Invitar y ganar')).toBeGreaterThan(rows.indexOf('Mensajes'));
    expect(rows.indexOf('El fundador')).toBe(rows.indexOf('Invitar y ganar') + 1);
    await press(tree, 'Invitar y ganar');
    expect(lastNavigation()).toEqual(['Main', { screen: 'Invite' }]);
    expect(drawer.isOpen).toBe(false);
    expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', 'invite');
    await act(async () => tree.unmount());
    tree = await openDrawer(await mount());
    await press(tree, 'El fundador');
    expect(lastNavigation()).toEqual(['Main', { screen: 'Founder' }]);
    expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', 'founder');
    await act(async () => tree.unmount());
    // A business has no invitations of its own; the founder is everyone's.
    mockAccount = { id: 'business_1_0', type: 'business', business: { name: 'Panadería' } };
    const business = await openDrawer(await mount());
    expect(texts(business)).not.toContain('Invitar y ganar');
    expect(texts(business)).toContain('El fundador');
    await act(async () => business.unmount());
  });

  it('keeps the Comunidad badge and counts unread messages; Mensajes opens where the unread is', async () => {
    mockPeekBadge = '3';
    mockUnread = { inbox: 1, direct: 2, requests: 1 };
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    expect(drawer.hasNews).toBe(true);
    expect(button(tree, 'Comunidad, 3 publicaciones nuevas')).toBeTruthy();
    await press(tree, 'Mensajes, 4 sin leer');
    expect(mockOpenAssistant).toHaveBeenLastCalledWith({ channel: 'mensajes' });

    mockUnread = { inbox: 2, direct: 0, requests: 0 };
    await openDrawer(tree);
    await press(tree, 'Mensajes, 2 sin leer');
    expect(mockOpenAssistant).toHaveBeenLastCalledWith({ channel: 'julian' });
    await act(async () => tree.unmount());
  });

  it('one new post reads in the singular; a never-opened Comunidad shows a dot; nothing new, no dot on the menu', async () => {
    publishHomeMoney(money());
    let tree = await openDrawer(await mount());
    expect(drawer.hasNews).toBe(false);
    expect(button(tree, 'Comunidad')).toBeTruthy();
    await act(async () => tree.unmount());

    mockPeekBadge = '1';
    tree = await openDrawer(await mount());
    expect(button(tree, 'Comunidad, 1 publicación nueva')).toBeTruthy();
    await act(async () => tree.unmount());

    mockPeekBadge = '';
    tree = await openDrawer(await mount());
    expect(drawer.hasNews).toBe(true);
    expect(button(tree, 'Comunidad, hay novedades')).toBeTruthy();
    await act(async () => tree.unmount());
  });
});

describe('the profile and its accounts, at the foot', () => {
  it('the name is a labelled door to Perfil and its settings', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    // "Perfil y ajustes" under the name says what the row opens.
    expect(texts(tree)).toEqual(expect.arrayContaining(['Ana', 'Perfil y ajustes', 'Cambiar']));
    await press(tree, 'Perfil y ajustes de Ana, Personal');
    expect(lastNavigation()).toEqual(toTab('Profile'));
    await act(async () => tree.unmount());
  });

  it('"Cambiar" opens the other accounts in place, in the menu, not as a pop-up over it', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    // Folded until asked for.
    expect(texts(tree)).not.toContain('Panadería');
    expect(button(tree, 'Cambiar de cuenta').props.accessibilityState).toEqual({ expanded: false });
    await press(tree, 'Cambiar de cuenta');
    expect(drawer.isOpen).toBe(true);
    expect(texts(tree)).toEqual(expect.arrayContaining(['Cambiar a', 'Panadería', 'Negocio', 'Crear cuenta de negocio']));
    expect(button(tree, 'Cambiar de cuenta').props.accessibilityState).toEqual({ expanded: true });
    // The account in use is the foot's own row: it is not listed a second time.
    expect(texts(tree)).not.toContain('Ana Pérez');
    expect(texts(tree)).not.toContain('Personal');
    // The same button folds it again.
    await press(tree, 'Cambiar de cuenta');
    expect(texts(tree)).not.toContain('Panadería');
    expect(handlers.switchAccount).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it('choosing another account goes to Inicio (where the switch and its progress live) and switches', async () => {
    publishHomeMoney(money());
    const tree = await openDrawer(await mount());
    await press(tree, 'Cambiar de cuenta');
    await press(tree, 'Cambiar a Panadería, Negocio');
    expect(lastNavigation()).toEqual(toTab('Home'));
    expect(handlers.switchAccount).toHaveBeenCalledWith('business_1_0');
    expect(drawer.isOpen).toBe(false);
    expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', 'switch_account');
    // Reopened, the list is folded again.
    await openDrawer(tree);
    expect(texts(tree)).not.toContain('Panadería');
    await act(async () => tree.unmount());
  });

  it('with one account there is nothing to change to, only a business account to create', async () => {
    publishHomeMoney(money({ accounts: [{ id: 'personal_0', name: 'Ana Pérez', kind: 'Personal', avatar: 'A', selected: true }] }));
    const tree = await openDrawer(await mount());
    await press(tree, 'Cambiar de cuenta');
    expect(texts(tree)).not.toContain('Cambiar a');
    await press(tree, 'Crear cuenta de negocio');
    expect(handlers.createBusiness).toHaveBeenCalledTimes(1);
    expect(drawer.isOpen).toBe(false);
    expect(mockLogHomeNav).toHaveBeenLastCalledWith('drawer', 'create_business');
    await act(async () => tree.unmount());
  });
});
