import React from 'react';
import { act, create } from 'react-test-renderer';

import ConnectionsPrompt from '../ConnectionsPrompt';
import { readSnooze } from '../store';
import { useConnections } from '../useConnections';

const mockMutate = jest.fn(async () => ({}));
const mockClient = { mutate: (...args: unknown[]) => (mockMutate as any)(...args) };
jest.mock('@apollo/client', () => ({ gql: () => ({}), useApolloClient: () => mockClient }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../../components/common/AppText', () => ({ Text: require('react-native').Text }));
let mockUntil: number | undefined;
let mockUntilWhatsApp: number | undefined;
jest.mock('../store', () => ({
  useKnownSnooze: (_user: string, source: string) => (source === 'whatsapp' ? mockUntilWhatsApp : mockUntil), readSnooze: jest.fn(async () => 0), openConnections: jest.fn(), snooze: jest.fn(),
}));
let mockLink: any = null;
jest.mock('../../whatsapp/useWhatsApp', () => ({ useWhatsApp: () => ({ link: mockLink, refetch: jest.fn() }) }));
jest.mock('../useConnections', () => ({
  useViewer: () => '1',
  useConnections: jest.fn(() => ({ connections: null, build: { mail: false, calendar: false }, refetch: jest.fn() })),
}));

const render = async (element: React.ReactElement) => {
  await act(async () => {
    create(element);
  });
};
beforeEach(() => {
  jest.clearAllMocks();
  mockLink = null;
  mockUntil = undefined;
  mockUntilWhatsApp = undefined;
});

it('an ordinary turn asks the server and the keystore nothing', async () => {
  await render(<ConnectionsPrompt where="box" starters={false} messages={[{ role: 'user', body: 'manda 20 a Juan' }]} />);
  await render(<ConnectionsPrompt where="box" starters={false} />);
  expect(useConnections).not.toHaveBeenCalled();
  expect(readSnooze).not.toHaveBeenCalled();
});

it('switched off: the opening never touches the keystore', async () => {
  await render(<ConnectionsPrompt where="box" starters />);
  expect(readSnooze).not.toHaveBeenCalled();
});

it('asked mid-chat: from the cache first', async () => {
  await render(<ConnectionsPrompt where="box" starters={false} messages={[{ role: 'user', body: 'lee mi correo' }]} />);
  expect(useConnections).toHaveBeenCalledWith('1', 'cache-first');
});

const link = (over: Record<string, unknown> = {}) => ({
  state: 'none', code: null, codeAt: null, phoneHint: null, reason: null, reasonMessage: null, linkedAt: null,
  lastSyncAt: null, ownPhoneHint: '4567', consentVersion: 1, consentOutdated: false, notices: [], ...over,
});
const words = async (element: React.ReactElement) => {
  let tree: any;
  await act(async () => {
    tree = create(element);
  });
  return JSON.stringify(tree.toJSON());
};

it('the opening offers WhatsApp to whoever can link it', async () => {
  mockLink = link();
  mockUntil = 0;
  mockUntilWhatsApp = 0;
  (useConnections as jest.Mock).mockReturnValue({
    connections: { gmail: 'soon', gmailAnswered: true, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: true },
    build: { mail: false, calendar: false }, refetch: jest.fn(),
  });
  const shown = await words(<ConnectionsPrompt where="box" starters />);
  expect(shown).toContain('Vincula tu WhatsApp');
  expect(shown).toContain('Ahora no');
  mockUntilWhatsApp = Date.now() + 86400000;  // "Ahora no" on WhatsApp holds
  expect(await words(<ConnectionsPrompt where="box" starters />)).not.toContain('Vincula tu WhatsApp');
});

it('a WhatsApp that WhatsApp unlinked is offered again, and the card opens its screen', async () => {
  const { whatsAppSession } = require('../../whatsapp/session');
  const { openConnections } = require('../store');
  mockLink = link({ state: 'gone' });
  mockUntil = 0;
  mockUntilWhatsApp = 0;
  (useConnections as jest.Mock).mockReturnValue({
    connections: { gmail: 'soon', gmailAnswered: true, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: true },
    build: { mail: false, calendar: false }, refetch: jest.fn(),
  });
  let tree: any;
  await act(async () => {
    tree = create(<ConnectionsPrompt where="home" starters />);
  });
  const shown = JSON.stringify(tree.toJSON());
  expect(shown).toContain('Tu WhatsApp se desvinculó');
  expect(shown).toContain('Vincular otra vez');
  const button = tree.root.findAll((node: any) => typeof node.props.onPress === 'function'
    && node.findAll((child: any) => child.props.children === 'Vincular otra vez').length > 0)[0];
  act(() => button.props.onPress());
  expect(whatsAppSession('1').open).toBe(true);  // straight to the WhatsApp screen
  expect(openConnections).toHaveBeenCalledWith('1', 'home');
});

it('no WhatsApp card once linked', async () => {
  (useConnections as jest.Mock).mockReturnValue({
    connections: { gmail: 'soon', gmailAnswered: true, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: true },
    build: { mail: false, calendar: false }, refetch: jest.fn(),
  });
  mockUntil = 0;
  mockUntilWhatsApp = 0;
  for (const state of [link({ state: 'linked' }), link({ state: 'pairing' })]) {
    mockLink = state;
    const shown = await words(<ConnectionsPrompt where="box" starters />);
    expect(shown).not.toContain('Vincula tu WhatsApp');
    expect(shown).toContain('WhatsApp, correo y calendario');  // the chip that always stays
  }
});

it('asking about WhatsApp mid-chat brings the way to link it', async () => {
  await render(<ConnectionsPrompt where="box" starters={false} messages={[{ role: 'user', body: 'conecta mi whatsapp' }]} />);
  expect(useConnections).toHaveBeenCalledWith('1', 'cache-first');
});

it('Gmail invited in a build without Gmail: the WhatsApp card, which can be put off', async () => {
  mockLink = link();
  mockUntil = 0;
  mockUntilWhatsApp = 0;
  (useConnections as jest.Mock).mockReturnValue({
    connections: { gmail: 'invited', gmailAnswered: false, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: true },
    build: { mail: false, calendar: false }, refetch: jest.fn(),
  });
  const shown = await words(<ConnectionsPrompt where="box" starters />);
  expect(shown).toContain('Vincula tu WhatsApp');
  expect(shown).not.toContain('Ya tienes tu cupo de Gmail');
  expect(shown).toContain('Ahora no');
  expect(shown).toContain('No me interesa');
});

it('opening Confío IA with WhatsApp linked asks for a fresh read; mid-chat it does not', async () => {
  mockLink = link({ state: 'linked' });
  mockUntil = 0;
  mockUntilWhatsApp = 0;
  (useConnections as jest.Mock).mockReturnValue({
    connections: { gmail: 'soon', gmailAnswered: true, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: true },
    build: { mail: false, calendar: false }, refetch: jest.fn(),
  });
  await render(<ConnectionsPrompt where="box" starters />);
  expect(mockMutate).toHaveBeenCalledTimes(1);
  mockMutate.mockClear();
  await render(<ConnectionsPrompt where="box" starters={false} messages={[{ role: 'user', body: 'lee mi whatsapp' }]} />);
  expect(mockMutate).not.toHaveBeenCalled();
});

it('putting WhatsApp off never hides the mail card', async () => {
  mockLink = link();
  mockUntil = 0;
  mockUntilWhatsApp = Date.now() + 365 * 86400000;
  (useConnections as jest.Mock).mockReturnValue({
    connections: { gmail: 'soon', gmailAnswered: false, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: false },
    build: { mail: false, calendar: false }, refetch: jest.fn(),
  });
  const shown = await words(<ConnectionsPrompt where="box" starters />);
  expect(shown).not.toContain('Vincula tu WhatsApp');
  expect(shown).toContain('Próximamente: tu correo y tu calendario');
});

it('putting mail off never hides the WhatsApp card', async () => {
  mockLink = link();
  mockUntil = Date.now() + 14 * 86400000;
  mockUntilWhatsApp = 0;
  (useConnections as jest.Mock).mockReturnValue({
    connections: { gmail: 'soon', gmailAnswered: false, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: false },
    build: { mail: false, calendar: false }, refetch: jest.fn(),
  });
  expect(await words(<ConnectionsPrompt where="box" starters />)).toContain('Vincula tu WhatsApp');
});
