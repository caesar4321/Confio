// The conversation as Inicio: the same chat as the floating box, drawn inline
// (docs/designs/ai-assistant-first-redesign.md 7.3-7.5).
import React from 'react';
import { Image, Modal, ScrollView, Text as RNText, TextInput as RNTextInput } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockAsk = jest.fn();
const mockRunHere = jest.fn();
const mockPreparePayment = jest.fn();
const mockPaymentCode = jest.fn(async (_uri: string): Promise<string | null> => null);
const mockAskPhoto = jest.fn();
const mockPick = jest.fn();
const mockOpenBox = jest.fn();
const mockOpenDestination = jest.fn();
const mockGuidePress = jest.fn();
const mockFinishReply = jest.fn();
const mockSetMicBusy = jest.fn();
let mockThread: any;
let mockThreadError: unknown;
let mockThreadLoading = false;
let mockGuide: any = null;
let mockGuidePending = false;
let mockGuideReplied = false;
let mockGuideSettled = true;
let mockGuideEnabled: boolean | undefined;
let mockAccount: any = { id: 'personal_0', type: 'personal' };
let mockAssistant: any;
let mockPollIntervals: Record<string, number | undefined> = {};
let mockSkips: Record<string, boolean | undefined> = {};
let mockThreadData: any;
const mockRefetchThread = jest.fn(async () => ({}));
const mockSuggestions = { assistantSuggestions: {
  starters: [{ id: 's1', text: 'Pagar un QR', prompt: 'Abre QR para pagar', kind: 'prompt' }], probe: null,
} };

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock('../../components/common/AppText', () => {
  const { Text, TextInput } = require('react-native');
  return { Text, TextInput };
});
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));
jest.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ userProfile: { username: 'ana' }, refreshProfile: jest.fn(async () => {}) }),
}));
jest.mock('../../assets/svg/WhatsApp.svg', () => 'WhatsAppLogo');
jest.mock('../PaymentIntentCard', () => ({ PaymentIntentCard: 'PaymentIntentCard' }));
jest.mock('../mail/ChatCards', () => ({ MailDraftCard: 'MailDraftCard', MailReplyChip: 'MailReplyChip',
  MailNoticeCard: 'MailNoticeCard', parseMailNotice: () => null }));
jest.mock('../whatsapp/ChatCards', () => ({ WhatsAppDraftCard: 'WhatsAppDraftCard', WhatsAppReplyChips: 'WhatsAppReplyChips', WhatsAppConsentChip: 'WhatsAppConsentChip',
  WhatsAppNoticeCard: 'WhatsAppNoticeCard', noticeAction: () => null }));
jest.mock('../StockTradeCard', () => ({ StockTradeCard: 'StockTradeCard' }));
jest.mock('../AddressForm', () => ({ AddressForm: 'AddressForm' }));
jest.mock('../TopUpForm', () => ({
  TopUpForm: 'TopUpForm',
  resolveTopUp: (a: any) => (a.type === 'form' && String(a.target).startsWith('topup')
    ? { label: a.label, prefill: a.target === 'topup' ? null : { currency: 'BOB', amount: '500' } } : null),
}));
jest.mock('../../services/messagingService', () => ({
  __esModule: true,
  default: { areNotificationsEnabled: jest.fn(async () => true), requestPermissions: jest.fn(async () => true) },
}));
jest.mock('../stockTrade', () => ({
  resolveTrade: (a: any) => (a.type === 'trade' ? { side: 'buy', ticker: a.ticker, amountUsd: 20, label: a.label } : null),
}));
jest.mock('../HereForm', () => ({
  HereForm: 'HereForm',
  resolveForm: (a: any) => (a.type === 'form' ? { key: a.target, label: a.label } : null),
}));
jest.mock('../../services/paymentIntent', () => {
  class PaymentIntentError extends Error {
    code: string;
    constructor(message: string, code = '') { super(message); this.code = code; }
  }
  return { PaymentIntentError, preparePaymentInChat: (...args: unknown[]) => mockPreparePayment(...args) };
});
jest.mock('../../services/qrFromImage', () => ({ paymentCodeInImage: (uri: string) => mockPaymentCode(uri) }));
jest.mock('../hereActions', () => ({
  HERE_CARDS: {
    invite_whatsapp: { icon: 'whatsapp', hint: 'Tu enlace y tu código, listos' },
    set_username: { icon: 'at-sign', hint: 'También cambia tu código', changes: true },
  },
  resolveHere: (a: any) => (a.type === 'do' ? { key: a.target.split(':')[0], arg: a.target.split(':')[1], label: a.label } : null),
  runHere: (...args: unknown[]) => mockRunHere(...args),
}));
jest.mock('../../navigation/RootNavigation', () => ({ navigationRef: { navigate: jest.fn() } }));
jest.mock('../../services/paidOffers', () => ({ logDoorShown: jest.fn() }));
jest.mock('../../components/smartAccount/useSmartRead', () => ({ useSmartRead: () => ({ data: undefined, failed: false }) }));
jest.mock('../../services/smartAccount', () => ({
  fetchSmartAccountEntry: jest.fn(), isSmartAccountOpen: () => false, isSmartAccountOpening: () => false,
}));
jest.mock('../../components/svg/CuentaInteligenteMark', () => 'CuentaInteligenteMark');
jest.mock('../../components/QrPayIcon', () => ({ QrPayIcon: 'QrPayIcon', QrShowIcon: 'QrShowIcon' }));
jest.mock('../../apollo/mutations', () => ({ MARK_MESSAGE_CHANNEL_SEEN: 'markSeen' }));
jest.mock('../../apollo/queries', () => ({
  GET_DIRECT_UNREAD_SUMMARY: 'direct', GET_MESSAGE_INBOX: 'inbox', GET_MESSAGE_INBOX_UNREAD_COUNT: 'unread',
}));
jest.mock('../../components/DirectInboxContent', () => ({ DirectInboxContent: 'DirectInboxContent' }));
jest.mock('../../components/MessageInboxContent', () => ({ MessageInboxContent: 'MessageInboxContent' }));
jest.mock('../../components/MessageInboxShared', () => ({ ChannelAvatar: 'ChannelAvatar' }));
jest.mock('../api', () => ({
  ANSWER_ASSISTANT_PROBE: 'answerProbe', ASK_ASSISTANT: 'ask', ASK_ASSISTANT_WITH_PHOTO: 'askPhoto',
  PHOTO_ONLY_BODY: '📷 Foto', GET_ASSISTANT_PLAN: 'plan',
  GET_ASSISTANT_SUGGESTIONS: 'suggestions', GET_ASSISTANT_THREAD: 'thread', RETURN_TO_ASSISTANT: 'return',
}));
jest.mock('../AssistantMascot', () => 'AssistantMascot');
jest.mock('../MascotPicker', () => 'MascotPicker');
jest.mock('../connections/ConnectionsHost', () => 'ConnectionsHost');
jest.mock('../connections/ConnectionsPrompt', () => 'ConnectionsPrompt');
jest.mock('../../services/systemPicker', () => ({ pickFromLibrary: (...args: unknown[]) => mockPick(...args) }));
jest.mock('../AssistantPlusPanel', () => 'AssistantPlusPanel');
jest.mock('../VoiceCallPanel', () => 'VoiceCallPanel');
jest.mock('../SmartContextNotice', () => ({
  SmartContextAssistantNotice: 'SmartContextAssistantNotice',
  isSmartContext: (account: any) => (account?.type || '').toLowerCase() === 'smart',
}));
jest.mock('../callStore', () => ({ clearCallError: jest.fn(), startCall: jest.fn(), useCall: () => ({ state: 'idle', error: null }) }));
jest.mock('../voiceNote', () => ({
  MAX_VOICE_NOTE_MS: 120000, isVoiceNoteAvailable: true,
  cancelVoiceNote: jest.fn(async () => {}), startVoiceNote: jest.fn(async () => true), stopVoiceNote: jest.fn(async () => null),
}));
jest.mock('../destinations', () => ({
  TAP_ONLY_KEYS: new Set(['cuenta_inteligente']),
  cardFor: (key: string) => (key === 'receive' ? { icon: 'arrow-down-left', hint: 'Tu número Confío y tus cuentas' }
    : key === 'pay_qr' ? { icon: 'qr-pay', hint: 'Escanea un QR y paga' } : { icon: 'activity', hint: '' }),
  openDestination: (...args: unknown[]) => mockOpenDestination(...args),
  resolveNavigate: (action: any) => (action.target ? { key: action.target, label: action.label, ticker: action.ticker } : null),
}));
jest.mock('../guidePointer', () => ({ requestGuideWalk: jest.fn() }));
jest.mock('../useHomeGuide', () => ({
  useHomeGuide: (enabled: boolean) => {
    mockGuideEnabled = enabled;
    return {
      guide: enabled ? mockGuide : null,
      replied: mockGuideReplied,
      settled: !enabled || mockGuideSettled,
      pending: mockGuidePending,
      press: (chip: unknown) => mockGuidePress(chip),
      beginReply: () => (enabled && mockGuide ? { step: mockGuide.step, finish: mockFinishReply } : null),
    };
  },
}));
jest.mock('../AssistantContext', () => ({ useAssistant: () => mockAssistant }));
jest.mock('@apollo/client', () => ({
  useApolloClient: () => ({ query: jest.fn(), refetchQueries: jest.fn(async () => []) }),
  useMutation: (mutation: string) => [
    mutation === 'ask' ? mockAsk : mutation === 'askPhoto' ? mockAskPhoto : jest.fn(async () => ({})),
  ],
  useQuery: (query: string, options: { skip?: boolean; pollInterval?: number }) => {
    mockSkips[query] = options.skip;
    mockPollIntervals[query] = options.pollInterval;
    if (options.skip) return { data: undefined, loading: false, refetch: jest.fn(async () => ({})) };
    // Like Apollo, the same answer is the same object on every render.
    if (query === 'thread') {
      if (mockThread && mockThreadData?.assistantThread !== mockThread) mockThreadData = { assistantThread: mockThread };
      return { data: mockThread ? mockThreadData : undefined, loading: mockThreadLoading,
        error: mockThreadError, refetch: mockRefetchThread };
    }
    if (query === 'suggestions') {
      return { data: mockSuggestions, refetch: mockRefetchThread };
    }
    return { data: undefined, loading: false, refetch: jest.fn(async () => ({})) };
  },
}));

import AssistantSheet, { type AssistantHomeProps } from '../AssistantSheet';

const PROFILE = { mascot: 'CAT', mascotName: '', mascotColor: '#10B981', customPetUrl: null };
const message = (id: string, role: string, body: string, actions: unknown[] = []) => ({
  id, role, body, createdAt: '2026-11-21T10:00:00Z', senderName: role === 'user' ? 'Tú' : 'Confío', modality: 'TEXT', actions,
});
const thread = (messages: unknown[], over: object = {}) => ({
  enabled: true, mode: 'AI', hasMore: false, profile: PROFILE, messages, ...over,
});
const pay = jest.fn();
const home = (over: Partial<AssistantHomeProps> = {}): AssistantHomeProps => ({
  active: true, name: 'Ana', primary: { kind: 'pay', onPress: pay }, notice: null, ...over,
});

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const buttons = (tree: renderer.ReactTestRenderer) => tree.root
  .findAll((n) => typeof n.props.accessibilityLabel === 'string' && typeof n.props.onPress === 'function')
  .map((n) => n.props.accessibilityLabel as string);
const button = (tree: renderer.ReactTestRenderer, label: string) => {
  const found = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function');
  if (!found.length) throw new Error(`no button ${label}; have ${buttons(tree).join(' | ')}`);
  return found[0];
};
const pressText = async (tree: renderer.ReactTestRenderer, label: string) => {
  // The innermost match: wrappers such as the chip row also take an onPress prop.
  const node = tree.root.findAll((n) => typeof n.props.onPress === 'function'
    && n.findAllByType(RNText).some((t) => [t.props.children].flat(Infinity).join('') === label)).pop();
  if (!node) throw new Error(`nothing pressable says ${label}`);
  await act(async () => { node.props.onPress(); });
};
const type = async (tree: renderer.ReactTestRenderer, value: string) => {
  await act(async () => { tree.root.findByType(RNTextInput).props.onChangeText(value); });
};
async function mount(props: AssistantHomeProps = home()) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AssistantSheet home={props} />); });
  return tree;
}
// As in the app: the screen is up first, and the thread arrives a moment later.
async function mountThenLoad(loaded: unknown, props: AssistantHomeProps = home()) {
  mockThread = null;
  mockThreadLoading = true;
  const tree = await mount(props);
  mockThread = loaded;
  mockThreadLoading = false;
  await act(async () => { tree.update(<AssistantSheet home={props} />); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockThread = thread([]);
  mockThreadError = undefined;
  mockThreadLoading = false;
  mockGuide = null;
  mockGuidePending = false;
  mockGuideReplied = false;
  mockGuideSettled = true;
  mockAccount = { id: 'personal_0', type: 'personal' };
  mockPollIntervals = {};
  mockSkips = {};
  mockAsk.mockResolvedValue({ data: { askAssistant: {
    success: true, mode: 'AI', actions: [],
    userMessage: message('11', 'user', 'hola'), reply: message('12', 'assistant', '¡Hola, Ana!'),
  } } });
  mockAssistant = {
    isOpen: false, close: jest.fn(), openSeq: 0, homeSeq: 0, homeActive: true, open: mockOpenBox, setMicBusy: mockSetMicBusy,
    route: 'Home', plan: null, setPlan: jest.fn(), available: true, aiEnabled: true, bubbleAnchor: null,
    showNavNote: jest.fn(), setBoxShown: jest.fn(),
    consumePrompt: () => undefined, consumePicker: () => false, consumeProbe: () => false, consumePlus: () => false,
    consumeCall: () => false, consumeChannel: () => undefined, consumeDmFolder: () => undefined,
    consumeVoiceNote: () => false, consumeVoiceNoteData: () => undefined,
  };
});

describe('an empty thread', () => {
  it('greets by name, offers the chips, and is never drawn in the floating box', async () => {
    const tree = await mount();
    const all = texts(tree);
    expect(all).toContain('Hola, Ana.');
    expect(all).toContain('¿Qué quieres que haga por ti hoy?');
    expect(all).toContain('Pagar un QR');
    // The box's "customise" chip is not here: the assistant's face is that door.
    expect(all).not.toContain('✨ Personaliza a tu asistente');
    expect(buttons(tree)).toContain('Personaliza a tu asistente');
    // It scrolls: the opening question with its chips is taller than a small phone.
    expect(tree.root.findAllByType(ScrollView).some((s) => s.props.keyboardShouldPersistTaps === 'handled')).toBe(true);
    expect(tree.root.findAllByType(Modal)).toHaveLength(0);
    // The box's own chrome (channel heads, its close button, the offer strip) is not here.
    expect(buttons(tree)).not.toContain('Cerrar');
    expect(buttons(tree)).not.toContain('Conoce Cuenta inteligente');
    expect(mockAssistant.setBoxShown).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it('without a name, and when people answer instead of the assistant', async () => {
    mockThread = thread([], { enabled: false });
    mockAssistant.aiEnabled = false;
    const tree = await mount(home({ name: undefined }));
    const all = texts(tree);
    expect(all).toContain('Hola.');
    expect(all).toContain('Escríbenos y el equipo de Confío te responde aquí.');
    expect(all).toContain('Te responde una persona del equipo de Confío.');
    await act(async () => tree.unmount());
  });

  it('does not greet until the server has said whether there is a first step (no swap a moment later)', async () => {
    mockGuideSettled = false;
    const tree = await mount();
    const all = texts(tree);
    expect(all).not.toContain('Hola, Ana.');
    expect(all).not.toContain('Pagar un QR');
    // The assistant's face and the composer are there meanwhile.
    expect(buttons(tree)).toEqual(expect.arrayContaining(['Personaliza a tu asistente', 'Pagar con QR']));
    mockGuideSettled = true;
    await act(async () => { tree.update(<AssistantSheet home={home()} />); });
    expect(texts(tree)).toEqual(expect.arrayContaining(['Hola, Ana.', 'Pagar un QR']));
    await act(async () => tree.unmount());
  });

  it('an older server with no ranked chips: the fallback teaches the wallet list, not the button beside it', async () => {
    const ranked = mockSuggestions.assistantSuggestions.starters;
    mockSuggestions.assistantSuggestions.starters = [];
    try {
      const tree = await mount();
      expect(texts(tree)).toContain('Muéstrame mi dinero');
      expect(texts(tree)).not.toContain('Abre QR para pagar');
      await act(async () => tree.unmount());
    } finally {
      mockSuggestions.assistantSuggestions.starters = ranked;
    }
  });

  it('a first load shows no greeting yet, and a failed one offers to retry', async () => {
    mockThread = null;
    mockThreadLoading = true;
    let tree = await mount();
    expect(texts(tree)).not.toContain('Hola, Ana.');
    // Pagar is there even before the conversation is.
    expect(button(tree, 'Pagar con QR')).toBeTruthy();
    await act(async () => tree.unmount());

    mockThreadLoading = false;
    mockThreadError = new Error('network');
    tree = await mount();
    expect(texts(tree)).toEqual(expect.arrayContaining(['No pudimos cargar tu conversación.', 'Reintentar']));
    expect(texts(tree)).not.toContain('Hola, Ana.');
    await act(async () => tree.unmount());
  });
});

describe('the primary button', () => {
  it('is Pagar while the field is empty and becomes send once the person types', async () => {
    const tree = await mount();
    // Round and icon-only, the size of the send button it turns into.
    expect(tree.root.findAllByType('QrPayIcon' as any)).toHaveLength(1);
    // The field itself invites a request.
    expect(tree.root.findByType(RNTextInput).props.placeholder).toBe('Pídeme lo que quieras');
    await act(async () => { button(tree, 'Pagar con QR').props.onPress(); });
    expect(pay).toHaveBeenCalledTimes(1);
    expect(mockAsk).not.toHaveBeenCalled();
    // The mic sits inside the field until there is text.
    expect(buttons(tree)).toContain('Grabar audio');

    await type(tree, 'hola');
    expect(buttons(tree)).not.toContain('Pagar con QR');
    expect(buttons(tree)).not.toContain('Grabar audio');
    await act(async () => { button(tree, 'Enviar').props.onPress(); });
    expect(mockAsk).toHaveBeenCalledTimes(1);
    expect(mockAsk.mock.calls[0][0].variables).toMatchObject({ body: 'hola', screen: 'Home', guideStep: null });
    // Sent: the field is empty again and Pagar is back.
    expect(buttons(tree)).toContain('Pagar con QR');
    expect(texts(tree)).toEqual(expect.arrayContaining(['hola', '¡Hola, Ana!']));
    await act(async () => tree.unmount());
  });

  it('is Cobrar for a business', async () => {
    const charge = jest.fn();
    mockAccount = { id: 'business_1_0', type: 'business' };
    const tree = await mount(home({ primary: { kind: 'charge', onPress: charge } }));
    expect(tree.root.findAllByType('QrShowIcon' as any)).toHaveLength(1);
    await act(async () => { button(tree, 'Cobrar').props.onPress(); });
    expect(charge).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it('an account that can neither pay nor charge only gets send', async () => {
    const tree = await mount(home({ primary: null }));
    expect(buttons(tree)).not.toContain('Pagar con QR');
    expect(button(tree, 'Enviar').props.disabled).toBe(true);
    await type(tree, 'hola');
    expect(button(tree, 'Enviar').props.disabled).toBe(false);
    await act(async () => tree.unmount());
  });
});

describe('a thread with history', () => {
  it('at the start of each visit the open question leads the chips, as on an empty thread', async () => {
    const tree = await mountThenLoad(thread([message('1', 'assistant', 'Listo.')]));
    const all = texts(tree);
    expect(all).toEqual(expect.arrayContaining(['Listo.', '¿Qué quieres que haga por ti hoy?', 'Pagar un QR']));
    // Once the person has written, the conversation is under way: no question, no chips.
    await type(tree, 'hola');
    await act(async () => { button(tree, 'Enviar').props.onPress(); });
    expect(texts(tree)).not.toContain('¿Qué quieres que haga por ti hoy?');
    await act(async () => tree.unmount());
  });

  it('a long press on a message copies it and says so', async () => {
    const Clipboard = require('@react-native-clipboard/clipboard');
    const tree = await mountThenLoad(thread([
      message('1', 'user', '¿Cómo recargo?'),
      message('2', 'assistant', 'Desde Recibir: elige tu banco.'),
    ]));
    const bubble = tree.root.findAll((n) => typeof n.props?.onLongPress === 'function'
      && n.findAll((c) => c.props?.children === 'Desde Recibir: elige tu banco.').length > 0)[0];
    jest.useFakeTimers();
    try {
      await act(async () => { bubble.props.onLongPress(); });
      expect(Clipboard.setString).toHaveBeenCalledWith('Desde Recibir: elige tu banco.');
      expect(texts(tree)).toContain('Copiado');
      await act(async () => { jest.advanceTimersByTime(1600); });
      expect(texts(tree)).not.toContain('Copiado');
    } finally {
      jest.useRealTimers();
    }
    await act(async () => tree.unmount());
  });

  it('shows the last conversation and opens what its chips name without closing anything', async () => {
    const tree = await mountThenLoad(thread([
      message('1', 'user', '¿Cómo recargo?'),
      message('2', 'assistant', 'Desde Recibir.', [{ type: 'navigate', target: 'receive', label: 'Abrir Recibir' }]),
    ]));
    expect(texts(tree)).toEqual(expect.arrayContaining(['¿Cómo recargo?', 'Desde Recibir.', 'Abrir Recibir']));
    expect(texts(tree)).not.toContain('Hola, Ana.');
    jest.useFakeTimers();
    try {
      await pressText(tree, 'Abrir Recibir');
      await act(async () => { jest.runOnlyPendingTimers(); });
    } finally {
      jest.useRealTimers();
    }
    expect(mockOpenDestination).toHaveBeenCalledWith('receive', { isBusiness: false, ticker: undefined, messageId: undefined });
    expect(mockAssistant.close).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it('a screen is a card: its name, what it is for, and the whole card opens it', async () => {
    const tree = await mountThenLoad(thread([
      message('1', 'user', '¿Cómo recibo dinero?'),
      message('2', 'assistant', 'Puedes recibir de dos formas. Toca la que quieras.', [
        { type: 'card', destination: 'receive', target: 'receive', label: 'Abrir Recibir' },
        { type: 'card', destination: 'profile', target: 'share_username', label: 'Compartir mi usuario' },
      ]),
    ]));
    // Read out as one thing: the name and what it does.
    // The card says what it opens, and what that is for.
    expect(buttons(tree)).toEqual(expect.arrayContaining(['Abrir Recibir. Tu número Confío y tus cuentas', 'Compartir mi usuario']));
    expect(texts(tree)).toEqual(expect.arrayContaining(['Abrir Recibir', 'Tu número Confío y tus cuentas', 'Compartir mi usuario']));
    jest.useFakeTimers();
    try {
      await act(async () => { button(tree, 'Compartir mi usuario').props.onPress(); });
      await act(async () => { jest.runOnlyPendingTimers(); });
    } finally {
      jest.useRealTimers();
    }
    expect(mockOpenDestination).toHaveBeenCalledWith('share_username', { isBusiness: false, ticker: undefined, messageId: undefined });
    await act(async () => tree.unmount());
  });

  it('a form for details the person types here: one per answer, and a prepared payment refreshes the thread', async () => {
    const tree = await mountThenLoad(thread([
      message('1', 'user', 'quiero enviar por pago móvil a mi mamá'),
      message('2', 'assistant', 'Escribe aquí sus datos y cuánto envías.', [
        { type: 'form', target: 'pagomovil_payment', label: 'Enviar por Pago Móvil' },
        { type: 'form', target: 'profile_name', label: 'Cambiar mi nombre' },
      ]),
    ]));
    const forms = tree.root.findAllByType('HereForm' as any);
    expect(forms.map((f) => [f.props.formKey, f.props.label])).toEqual([['pagomovil_payment', 'Enviar por Pago Móvil']]);
    mockRefetchThread.mockClear();
    await act(async () => { forms[0].props.onPrepared(); });
    expect(mockRefetchThread).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it('a top-up is its own form, with the amount the person wrote, and the one form of that answer', async () => {
    const tree = await mountThenLoad(thread([
      message('1', 'user', 'quiero recargar 500 bolivianos'),
      message('2', 'assistant', 'Elige cómo pagas y toca Crear recarga.', [
        { type: 'form', target: 'topup:BOB=500', label: 'Recargar 500 bolivianos' },
        { type: 'form', target: 'profile_name', label: 'Cambiar mi nombre' },
      ]),
    ]));
    const forms = tree.root.findAllByType('TopUpForm' as any);
    expect(forms.map((f) => [f.props.messageId, f.props.label, f.props.prefill])).toEqual(
      [['2', 'Recargar 500 bolivianos', { currency: 'BOB', amount: '500' }]]);
    // On Inicio the order is created right here (no hand-over to the screen).
    expect(forms[0].props.onLeaveBox).toBeUndefined();
    expect(tree.root.findAllByType('HereForm' as any)).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it('a stock trade is its own card on the message, one per answer, and never a chip that opens a screen', async () => {
    const tree = await mountThenLoad(thread([
      message('1', 'user', 'compra 20 dólares de Apple'),
      message('2', 'assistant', 'Revisa la tarjeta y aprueba ahí.', [
        { type: 'trade', ticker: 'AAPL', target: 'buy:20.00', label: 'Comprar US$20 de Apple Inc.' },
        { type: 'trade', ticker: 'MSFT', target: 'buy:20.00', label: 'Comprar US$20 de Microsoft' },
      ]),
    ]));
    const cards = tree.root.findAllByType('StockTradeCard' as any);
    expect(cards.map((c) => [c.props.messageId, c.props.action.ticker])).toEqual([['2', 'AAPL']]);
    expect(texts(tree).join(' ')).not.toContain('Comprar US$20 de Apple Inc.');
    await act(async () => tree.unmount());
  });

  it('a prepared payment is its own card, read from the server by the message, and never a chip that opens Pagar', async () => {
    jest.useFakeTimers();
    try {
      const chip = { type: 'navigate', destination: 'pay_qr', target: 'payment_intent', label: 'Revisar y pagar' };
      mockAsk.mockResolvedValue({ data: { askAssistant: {
        success: true, mode: 'AI', actions: [chip],
        userMessage: message('11', 'user', 'paga este código 000201…'),
        reply: message('12', 'assistant', 'Preparé el pago. Revísalo en la tarjeta.', [chip]),
      } } });
      const tree = await mount();
      await type(tree, 'paga este código 000201…');
      await act(async () => { button(tree, 'Enviar').props.onPress(); });
      await act(async () => { jest.advanceTimersByTime(2000); });
      const cards = tree.root.findAllByType('PaymentIntentCard' as any);
      expect(cards.map((c) => c.props.messageId)).toEqual(['12']);
      // On Inicio it approves in place; only the floating box (a modal) sends the person away.
      expect(cards[0].props.onLeaveBox).toBeUndefined();
      expect(buttons(tree).some((l) => l.startsWith('Revisar y pagar'))).toBe(false);
      // Paying is approved on the card: the answer never opens a screen by itself.
      expect(mockOpenDestination).not.toHaveBeenCalled();
      await act(async () => tree.unmount());
    } finally {
      jest.useRealTimers();
    }
  });

  it('a card that does the thing here: nothing happens before the tap, and then the card says so', async () => {
    const tree = await mountThenLoad(thread([
      message('1', 'user', 'quiero invitar a mi hija y cambiar mi usuario a ana_perez'),
      message('2', 'assistant', 'Toca para invitarla, y este otro botón cambia tu usuario.', [
        { type: 'do', target: 'invite_whatsapp', label: 'Invitar por WhatsApp' },
        { type: 'do', target: 'set_username:ana_perez', label: 'Usar @ana_perez' },
      ]),
    ]));
    expect(buttons(tree)).toEqual(expect.arrayContaining([
      'Invitar por WhatsApp. Tu enlace y tu código, listos', 'Usar @ana_perez. También cambia tu código']));
    expect(mockRunHere).not.toHaveBeenCalled();
    expect(mockOpenDestination).not.toHaveBeenCalled();

    // Inviting opens WhatsApp: the card stays as it was, to use again.
    mockRunHere.mockResolvedValueOnce(null);
    await act(async () => { await button(tree, 'Invitar por WhatsApp. Tu enlace y tu código, listos').props.onPress(); });
    expect(mockRunHere.mock.calls[0][0]).toMatchObject({ key: 'invite_whatsapp' });
    expect(mockRunHere.mock.calls[0][1].username).toBe('ana');
    expect(buttons(tree)).toContain('Invitar por WhatsApp. Tu enlace y tu código, listos');

    // A change that fails says why, and can be tried again.
    mockRunHere.mockResolvedValueOnce({ error: 'Este nombre de usuario ya está en uso.' });
    await act(async () => { await button(tree, 'Usar @ana_perez. También cambia tu código').props.onPress(); });
    expect(texts(tree)).toContain('Este nombre de usuario ya está en uso.');
    // Done: the card says so and is no longer a button to press twice.
    mockRunHere.mockResolvedValueOnce({ done: 'Listo: ahora eres @ana_perez' });
    await act(async () => { await button(tree, 'Usar @ana_perez. Este nombre de usuario ya está en uso.').props.onPress(); });
    expect(texts(tree)).toContain('Listo: ahora eres @ana_perez');
    const done = tree.root.findAll((n) => n.props.accessibilityLabel === 'Listo: ahora eres @ana_perez'
      && typeof n.props.onPress === 'function')[0];
    expect(done.props.disabled).toBe(true);
    await act(async () => { await done.props.onPress(); });
    expect(mockRunHere).toHaveBeenCalledTimes(3);
    await act(async () => tree.unmount());
  });

  it('an answer that leaves cards does not move the app; one that opens a screen does', async () => {
    jest.useFakeTimers();
    try {
      mockAsk.mockResolvedValue({ data: { askAssistant: {
        success: true, mode: 'AI',
        actions: [{ type: 'card', destination: 'receive', target: 'receive', label: 'Abrir Recibir' }],
        userMessage: message('11', 'user', '¿cómo recibo?'),
        reply: message('12', 'assistant', 'Así.', [{ type: 'card', destination: 'receive', target: 'receive', label: 'Abrir Recibir' }]),
      } } });
      const tree = await mount();
      await type(tree, '¿cómo recibo?');
      await act(async () => { button(tree, 'Enviar').props.onPress(); });
      await act(async () => { jest.advanceTimersByTime(2000); });
      // The card is there to tap; nothing opened by itself.
      expect(buttons(tree)).toContain('Abrir Recibir. Tu número Confío y tus cuentas');
      expect(mockOpenDestination).not.toHaveBeenCalled();

      mockAsk.mockResolvedValue({ data: { askAssistant: {
        success: true, mode: 'AI',
        actions: [{ type: 'navigate', destination: 'receive', target: 'receive', label: 'Abrir Recibir' }],
        userMessage: message('13', 'user', 'abre recibir'),
        reply: message('14', 'assistant', 'Te abrí Recibir.', [{ type: 'navigate', destination: 'receive', target: 'receive', label: 'Abrir Recibir' }]),
      } } });
      await type(tree, 'abre recibir');
      await act(async () => { button(tree, 'Enviar').props.onPress(); });
      await act(async () => { jest.advanceTimersByTime(2000); });
      expect(mockOpenDestination).toHaveBeenCalledWith('receive', expect.anything());
      await act(async () => tree.unmount());
    } finally {
      jest.useRealTimers();
    }
  });

  it('"Mensajes" opens Julian\'s channel in the box, and the assistant\'s face its settings', async () => {
    const tree = await mountThenLoad(thread([
      message('2', 'assistant', 'Mira tus mensajes.', [{ type: 'navigate', target: 'messages', label: 'Mensajes' }]),
    ]));
    await pressText(tree, 'Mensajes');
    expect(mockOpenBox).toHaveBeenCalledWith({ channel: 'julian' });
    expect(mockOpenDestination).not.toHaveBeenCalled();
    expect(tree.root.findByType('MascotPicker' as any).props.visible).toBe(false);
    await act(async () => { button(tree, 'Personaliza a tu asistente').props.onPress(); });
    expect(tree.root.findByType('MascotPicker' as any).props.visible).toBe(true);
    await act(async () => tree.unmount());
  });

  it('asks the server less often than the box, and not at all while Inicio is covered', async () => {
    let tree = await mount();
    expect(mockPollIntervals.thread).toBe(30000);
    // The channel heads belong to the box: their reads are skipped here.
    expect(mockSkips.inbox).toBe(true);
    expect(mockSkips.direct).toBe(true);
    await act(async () => tree.unmount());

    tree = await mount(home({ active: false }));
    expect(mockSkips.thread).toBe(true);
    expect(mockPollIntervals.thread).toBe(0);
    expect(mockGuideEnabled).toBe(false);
    await act(async () => tree.unmount());
  });
});

describe('the first steps, said in the conversation', () => {
  const TOP_UP = {
    step: 'top_up', stage: 'top_up', text: 'Ya puedes recargar. ¿Empezamos?', presentation: 'bubble',
    chips: [{ label: 'Sí, ir a Recargar', kind: 'navigate', answer: '', trail: [] },
      { label: 'Ahora no', kind: 'dismiss', answer: '', trail: [] }],
  };

  it('replace the greeting and the suggestion chips of an empty thread', async () => {
    mockGuide = TOP_UP;
    const tree = await mount();
    const all = texts(tree);
    expect(all).toEqual(expect.arrayContaining(['Ya puedes recargar. ¿Empezamos?', 'Sí, ir a Recargar', 'Ahora no']));
    expect(all).not.toContain('Hola, Ana.');
    expect(all).not.toContain('Pagar un QR');
    await pressText(tree, 'Sí, ir a Recargar');
    expect(mockGuidePress).toHaveBeenCalledWith(TOP_UP.chips[0]);
    await act(async () => tree.unmount());
  });

  it('are the newest message of a thread with history', async () => {
    mockGuide = TOP_UP;
    const tree = await mountThenLoad(thread([message('1', 'assistant', 'Tu identidad fue aprobada.')]));
    const all = texts(tree);
    expect(all).toEqual(expect.arrayContaining(['Tu identidad fue aprobada.', 'Ya puedes recargar. ¿Empezamos?', 'Ahora no']));
    expect(all).not.toContain('Pagar un QR');
    await act(async () => tree.unmount());
  });

  it('once the person has written back, only the chips stay, under the reply', async () => {
    mockGuide = TOP_UP;
    mockGuideReplied = true;
    const tree = await mountThenLoad(thread([message('1', 'user', '¿cuánto cuesta?'), message('2', 'assistant', 'Lo ves antes de confirmar.')]));
    const all = texts(tree);
    expect(all).toEqual(expect.arrayContaining(['Lo ves antes de confirmar.', 'Sí, ir a Recargar', 'Ahora no']));
    expect(all).not.toContain('Ya puedes recargar. ¿Empezamos?');
    await pressText(tree, 'Ahora no');
    expect(mockGuidePress).toHaveBeenCalledWith(TOP_UP.chips[1]);
    await act(async () => tree.unmount());
  });

  it('a typed answer keeps to the step and counts once the assistant replies', async () => {
    mockGuide = TOP_UP;
    const tree = await mount();
    await type(tree, '¿cuánto cuesta?');
    await act(async () => { button(tree, 'Enviar').props.onPress(); });
    expect(mockAsk.mock.calls[0][0].variables).toMatchObject({ body: '¿cuánto cuesta?', guideStep: 'top_up' });
    expect(mockFinishReply).toHaveBeenCalledWith(true);
    await act(async () => tree.unmount());
  });

  it('are for personal accounts with the assistant answering, never for a business', async () => {
    mockGuide = TOP_UP;
    mockAccount = { id: 'business_1_0', type: 'business' };
    let tree = await mount();
    expect(mockGuideEnabled).toBe(false);
    expect(texts(tree)).not.toContain('Ya puedes recargar. ¿Empezamos?');
    await act(async () => tree.unmount());

    mockAccount = { id: 'personal_0', type: 'personal' };
    mockAssistant.aiEnabled = false;
    tree = await mount();
    expect(mockGuideEnabled).toBe(false);
    await act(async () => tree.unmount());
  });
});

describe('polling and the microphone', () => {
  it('a poll never takes the greeting and chips of an empty thread away', async () => {
    const tree = await mount();
    expect(texts(tree)).toContain('Hola, Ana.');
    // Apollo reports every poll as loading.
    mockThreadLoading = true;
    await act(async () => { tree.update(<AssistantSheet home={home()} />); });
    expect(texts(tree)).toEqual(expect.arrayContaining(['Hola, Ana.', 'Pagar un QR']));
    await act(async () => tree.unmount());
  });

  it('the recorder takes the microphone from the wake word and gives it back', async () => {
    const tree = await mount();
    await act(async () => { button(tree, 'Grabar audio').props.onPress(); });
    expect(mockSetMicBusy).toHaveBeenLastCalledWith(true);
    await act(async () => { button(tree, 'Cancelar audio').props.onPress(); });
    expect(mockSetMicBusy).toHaveBeenLastCalledWith(false);
    await act(async () => tree.unmount());
  });
});

describe('money waiting on the person', () => {
  it('is one line above the composer', async () => {
    const onPress = jest.fn();
    const tree = await mount(home({ notice: { key: 'pendingIncoming', icon: 'download', text: 'Tienes dinero por recibir', onPress } }));
    expect(texts(tree)).toContain('Tienes dinero por recibir');
    await act(async () => { button(tree, 'Tienes dinero por recibir').props.onPress(); });
    expect(onPress).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });
});

describe('a photo', () => {
  const picked = { assets: [{ uri: 'file:///tmp/cartel.jpg', base64: 'QUJD', type: 'image/jpg' }] };
  const sentPhoto = (id: string, body = '📷 Foto') => ({ ...message(id, 'user', body), modality: 'PHOTO' });
  const images = (tree: renderer.ReactTestRenderer) => tree.root.findAllByType(Image).map((i) => i.props.source.uri);
  beforeEach(() => {
    mockPick.mockResolvedValue(picked);
    mockAskPhoto.mockResolvedValue({ data: { askAssistant: {
      success: true, mode: 'AI', actions: [],
      userMessage: sentPhoto('21'), reply: message('22', 'assistant', 'Dice «Cerrado los lunes».'),
    } } });
  });

  it('the image button opens the phone\'s photos; the photo waits above the field and goes with the message', async () => {
    const tree = await mount();
    await act(async () => { button(tree, 'Adjuntar una foto').props.onPress(); });
    // Resized on the phone, one photo, with its bytes.
    expect(mockPick).toHaveBeenCalledWith(expect.objectContaining({
      mediaType: 'photo', selectionLimit: 1, includeBase64: true, maxWidth: 1600, maxHeight: 1600,
    }));
    expect(images(tree)).toEqual(['file:///tmp/cartel.jpg']);
    expect(tree.root.findByType(RNTextInput).props.placeholder).toBe('Agrega un mensaje');
    // A photo alone is something to send: the round button is send, and there is no audio with it.
    expect(buttons(tree)).not.toContain('Pagar con QR');
    expect(buttons(tree)).not.toContain('Grabar audio');
    expect(buttons(tree)).toEqual(expect.arrayContaining(['Quitar foto', 'Cambiar la foto']));

    await act(async () => { button(tree, 'Enviar').props.onPress(); });
    expect(mockAsk).not.toHaveBeenCalled();
    expect(mockAskPhoto.mock.calls[0][0].variables).toEqual({
      body: null, photoBase64: 'QUJD', photoMimeType: 'image/jpg', screen: 'Home', timezone: expect.anything(), guideStep: null,
    });
    // Sent: the photo is in the person's bubble (its stand-in words are not), the field is as before.
    expect(images(tree)).toEqual(['file:///tmp/cartel.jpg']);
    expect(texts(tree)).toContain('Dice «Cerrado los lunes».');
    expect(texts(tree)).not.toContain('📷 Foto');
    expect(buttons(tree)).not.toContain('Quitar foto');
    expect(buttons(tree)).toContain('Pagar con QR');
    await act(async () => tree.unmount());
  });

  it('goes with the words typed beside it', async () => {
    mockAskPhoto.mockResolvedValue({ data: { askAssistant: {
      success: true, mode: 'AI', actions: [],
      userMessage: sentPhoto('31', '¿Qué dice?'), reply: message('32', 'assistant', 'Dice «Abierto».'),
    } } });
    const tree = await mount();
    await act(async () => { button(tree, 'Adjuntar una foto').props.onPress(); });
    await type(tree, '¿Qué dice?');
    await act(async () => { button(tree, 'Enviar').props.onPress(); });
    expect(mockAskPhoto.mock.calls[0][0].variables).toMatchObject({ body: '¿Qué dice?', photoBase64: 'QUJD' });
    expect(texts(tree)).toEqual(expect.arrayContaining(['¿Qué dice?', 'Dice «Abierto».']));
    await act(async () => tree.unmount());
  });

  it('can be taken off before sending, and a closed picker changes nothing', async () => {
    const tree = await mount();
    mockPick.mockResolvedValueOnce({ didCancel: true });
    await act(async () => { button(tree, 'Adjuntar una foto').props.onPress(); });
    expect(images(tree)).toEqual([]);
    expect(buttons(tree)).toContain('Pagar con QR');

    await act(async () => { button(tree, 'Adjuntar una foto').props.onPress(); });
    await act(async () => { button(tree, 'Quitar foto').props.onPress(); });
    expect(images(tree)).toEqual([]);
    expect(buttons(tree)).toContain('Pagar con QR');
    expect(mockAskPhoto).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it('a send that fails gives the photo and its words back, with the reason', async () => {
    mockAskPhoto.mockResolvedValue({ data: { askAssistant: {
      success: false, error: 'No pude leer esa foto. Prueba con otra.', actions: [], mode: 'AI',
    } } });
    const tree = await mount();
    await act(async () => { button(tree, 'Adjuntar una foto').props.onPress(); });
    await type(tree, 'mira');
    await act(async () => { button(tree, 'Enviar').props.onPress(); });
    expect(texts(tree)).toContain('No pude leer esa foto. Prueba con otra.');
    expect(images(tree)).toEqual(['file:///tmp/cartel.jpg']);
    expect(tree.root.findByType(RNTextInput).props.value).toBe('mira');
    expect(buttons(tree)).toContain('Quitar foto');
    await act(async () => tree.unmount());
  });

  it('a file too heavy for the server is refused on the phone', async () => {
    mockPick.mockResolvedValue({ assets: [{ uri: 'file:///tmp/big.jpg', base64: 'A'.repeat(2_300_001), type: 'image/jpeg' }] });
    const tree = await mount();
    await act(async () => { button(tree, 'Adjuntar una foto').props.onPress(); });
    expect(texts(tree)).toContain('Esa foto pesa demasiado. Prueba con otra.');
    expect(images(tree)).toEqual([]);
    await act(async () => tree.unmount());
  });

  it('is for the assistant: no button while people answer', async () => {
    let tree = await mountThenLoad(thread([message('1', 'team', 'Hola, soy Julian.')], { mode: 'HUMAN' }));
    expect(buttons(tree)).not.toContain('Adjuntar una foto');
    await act(async () => tree.unmount());
    mockAssistant.aiEnabled = false;
    tree = await mountThenLoad(thread([], { enabled: false }));
    expect(buttons(tree)).not.toContain('Adjuntar una foto');
    await act(async () => tree.unmount());
  });

  it('one sent earlier, whose file is not on this phone, says "Foto" over its words', async () => {
    const tree = await mountThenLoad(thread([
      sentPhoto('41'), message('42', 'assistant', 'Veo un recibo.'),
      sentPhoto('43', '¿Y este?'), message('44', 'assistant', 'Una factura.'),
    ]));
    const all = texts(tree);
    expect(all.filter((t) => t === 'Foto')).toHaveLength(2);
    expect(all).toContain('¿Y este?');
    expect(all).not.toContain('📷 Foto');
    expect(images(tree)).toEqual([]);
    await act(async () => tree.unmount());
  });

  it('a payment QR is not a picture to look at: it becomes a payment to review, in the conversation', async () => {
    mockPaymentCode.mockResolvedValueOnce('00020126580014br.gov.bcb.pix…6304ABCD');
    mockPreparePayment.mockResolvedValueOnce({ id: 'intent-1' });
    const tree = await mount();
    await act(async () => { await button(tree, 'Adjuntar una foto').props.onPress(); });
    expect(mockPaymentCode).toHaveBeenCalledWith('file:///tmp/cartel.jpg');
    expect(mockPreparePayment).toHaveBeenCalledWith('00020126580014br.gov.bcb.pix…6304ABCD', 'shared_qr');
    // The card arrives as a line of the thread; nothing is attached or sent to the assistant.
    expect(mockRefetchThread).toHaveBeenCalled();
    expect(images(tree)).toEqual([]);
    expect(mockAskPhoto).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it('a refusal to prepare it is said; where payments are not offered yet the picture is just a picture', async () => {
    const { PaymentIntentError } = require('../../services/paymentIntent');
    const tree = await mount();
    mockPaymentCode.mockResolvedValueOnce('000201…');
    mockPreparePayment.mockRejectedValueOnce(new PaymentIntentError('Este código no trae un monto.', 'no_amount'));
    await act(async () => { await button(tree, 'Adjuntar una foto').props.onPress(); });
    expect(texts(tree)).toContain('Este código no trae un monto.');
    expect(images(tree)).toEqual([]);

    mockPaymentCode.mockResolvedValueOnce('000201…');
    mockPreparePayment.mockRejectedValueOnce(new PaymentIntentError('Todavía no puedo preparar pagos desde aquí.', 'unavailable'));
    await act(async () => { await button(tree, 'Adjuntar una foto').props.onPress(); });
    expect(images(tree)).toEqual(['file:///tmp/cartel.jpg']);
    expect(texts(tree)).not.toContain('Todavía no puedo preparar pagos desde aquí.');
    await act(async () => tree.unmount());
  });

  it('the floating box has the same button', async () => {
    mockAssistant.isOpen = true;
    mockAssistant.homeActive = false;
    mockThread = thread([message('1', 'assistant', 'Hola.')]);
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<AssistantSheet />); });
    await act(async () => { button(tree, 'Adjuntar una foto').props.onPress(); });
    expect(images(tree)).toEqual(['file:///tmp/cartel.jpg']);
    await act(async () => { button(tree, 'Enviar').props.onPress(); });
    expect(mockAskPhoto.mock.calls[0][0].variables).toMatchObject({ body: null, photoBase64: 'QUJD' });
    await act(async () => tree.unmount());
  });
});

describe('the floating box is unchanged', () => {
  it('still draws as a modal with its channel heads, and reads its own open state', async () => {
    mockAssistant.isOpen = true;
    mockAssistant.homeActive = false;
    mockThread = thread([message('1', 'assistant', 'Hola.')]);
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<AssistantSheet />); });
    expect(tree.root.findAllByType(Modal)).toHaveLength(1);
    expect(buttons(tree)).toContain('Cerrar');
    expect(buttons(tree)).not.toContain('Pagar con QR');
    expect(mockPollIntervals.thread).toBe(15000);
    expect(mockSkips.inbox).toBe(false);
    expect(mockGuideEnabled).toBe(false);
    // The box never touches the shared microphone flag: the wake word is off while it is open.
    expect(mockSetMicBusy).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });
});
