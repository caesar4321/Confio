import React from 'react';
import { act, create } from 'react-test-renderer';

import type { Connections, GmailState } from '../api';
import { ConnectionsSheet } from '../ConnectionsHost';

let mockTyped: string | undefined;
const mockAnswer = jest.fn(async () => ({ data: { answerAssistantMailConnection: { success: true } } }));
jest.mock('@apollo/client', () => ({ gql: () => ({}), useMutation: () => [mockAnswer] }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaProvider: 'SafeAreaProvider', SafeAreaView: 'SafeAreaView' }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../../components/common/AppText', () => {
  const RN = require('react-native');
  return { Text: RN.Text, TextInput: RN.TextInput };
});
jest.mock('../../calendar/CalendarConnectSheet', () => 'CalendarConnectSheet');
jest.mock('../../mail/MailSheet', () => 'MailSheet');
jest.mock('../../mail/session', () => ({ mailSession: () => ({ open: false }), closeMailSession: jest.fn() }));
jest.mock('../store', () => ({
  closeConnections: jest.fn(), useConnectionsOpen: () => true, keepTypedEmail: jest.fn(),
  typedEmail: () => mockTyped,
}));
jest.mock('../useConnections', () => ({ useConnections: jest.fn() }));
let mockLink: any = null;
jest.mock('../../whatsapp/useWhatsApp', () => ({ useWhatsApp: () => ({ link: mockLink, refetch: jest.fn(async () => ({})) }) }));
jest.mock('../../whatsapp/WhatsAppSheet', () => 'WhatsAppSheet');
const mockWhatsAppSession = { open: false };
jest.mock('../../whatsapp/session', () => ({
  whatsAppSession: () => mockWhatsAppSession,
  closeWhatsAppSession: () => { mockWhatsAppSession.open = false; },
}));
jest.mock('../../calendar/consent', () => ({ readCalendarConsent: jest.fn(async () => null) }));
jest.mock('../../calendar/deviceCalendar', () => ({ hasCalendarAccess: jest.fn(async () => true), calendarSupported: () => true }));

function show(gmail: GmailState, mail = false) {
  const data: Connections = {
    gmail, gmailAnswered: false, googleEmail: null, suggestedEmail: 'ana@gmail.com', calendar: 'soon', calendarAnswered: false,
  };
  let tree: any;
  act(() => {
    tree = create(<ConnectionsSheet userId="1" data={data} build={{ mail, calendar: false }} refresh={jest.fn()} />);
  });
  const words = () => JSON.stringify(tree.toJSON());
  const press = async (label: string) => {
    const target = tree.root.findAll((node: any) => typeof node.props.onPress === 'function'
      && node.findAll((child: any) => child.props.children === label).length > 0);
    await act(async () => {
      // Innermost, and the first one (Gmail comes before the calendar).
      await target.find((node: any) => !target.some((other: any) => other !== node
        && node.findAll((child: any) => child === other).length > 0)).props.onPress();
    });
  };
  return { words, press, root: () => tree.root };
}

beforeEach(() => {
  mockAnswer.mockClear();
  mockTyped = undefined;
  mockLink = null;
});

beforeEach(() => {
  mockWhatsAppSession.open = false;
});

it('one full-screen sheet at a time: the list hides while a sheet is open', async () => {
  mockLink = { state: 'none', phoneHint: null, consentOutdated: false, consentVersion: 1, reasonMessage: null } as any;
  const { words, press, root } = show('soon');
  await press('Vincular WhatsApp');
  const modal = root().findAll((node: any) => node.props && node.props.onRequestClose && 'visible' in node.props)[0];
  expect(modal.props.visible).toBe(false);
  expect(words()).toContain('WhatsAppSheet');
});

it('an older server without WhatsApp shows no WhatsApp row', () => {
  expect(show('soon').words()).not.toContain('Vincular WhatsApp');
});

it('WhatsApp: anyone can open the way to link it', async () => {
  mockLink = {
    state: 'none', code: null, codeAt: null, phoneHint: null, reason: null, reasonMessage: null, linkedAt: null,
    lastSyncAt: null, ownPhoneHint: null, suggestedPhone: null, consentVersion: 4, consentOutdated: false, notices: [],
  };
  const { words, press } = show('soon');
  expect(words()).toContain('respondes desde aquí');
  await press('Vincular WhatsApp');
  expect(words()).toContain('WhatsAppSheet');
});

it('full: says so, asks for no address, and takes the waitlist answer', async () => {
  const { words, press } = show('full');
  expect(words()).toContain('Cupos completos');
  expect(words()).not.toContain('El Gmail que quieres conectar');
  await press('Sí, avísame');
  expect(mockAnswer).toHaveBeenCalledWith({ variables: { feature: 'gmail', wants: true, googleEmail: null } });
});

it('places left: sends the address to add in Google', async () => {
  const { press } = show('request');
  await press('Pedir un cupo');
  expect(mockAnswer).toHaveBeenCalledWith({ variables: { feature: 'gmail', wants: true, googleEmail: 'ana@gmail.com' } });
});

it('waiting: can leave the list', async () => {
  const { press } = show('waiting_full');
  await press('Salir de la lista');
  expect(mockAnswer).toHaveBeenCalledWith({ variables: { feature: 'gmail', wants: false, googleEmail: null } });
});

it('invited but an old build: no button to a screen it lacks', () => {
  const { words } = show('invited');
  expect(words()).toContain('Actualiza la app');
  expect(words()).not.toContain('Conectar Gmail');
});

it('invited: connect', () => {
  expect(show('invited', true).words()).toContain('Conectar Gmail');
});

it('back from the app lock: what they typed, not the sign-in Gmail', async () => {
  mockTyped = 'second@gmail.com';
  const { press } = show('request');
  await press('Pedir un cupo');
  expect(mockAnswer).toHaveBeenCalledWith({ variables: { feature: 'gmail', wants: true, googleEmail: 'second@gmail.com' } });
});
