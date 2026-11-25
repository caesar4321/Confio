import React from 'react';
import { act, create } from 'react-test-renderer';

import { WhatsAppDraftCard, WhatsAppNoticeCard, WhatsAppReplyChips } from '../ChatCards';

const mockMutate = jest.fn();
const mockQuery = jest.fn();
const mockRefetch = jest.fn(async (..._a: unknown[]) => []);
const mockClient = { mutate: (...a: unknown[]) => mockMutate(...a), query: (...a: unknown[]) => mockQuery(...a),
  refetchQueries: (...a: unknown[]) => mockRefetch(...a) };
let mockLinkData: any = null;
jest.mock('@apollo/client', () => ({ gql: () => ({}), useApolloClient: () => mockClient,
  useQuery: () => ({ data: mockLinkData }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../../components/common/AppText', () => ({ Text: require('react-native').Text, TextInput: require('react-native').TextInput }));

const draft = { id: 'd1', chat: 'Farmacia Central', phone: null, body: 'Paso a las 5', status: 'draft', reason: null, displayHash: 'h1' };

beforeEach(() => jest.clearAllMocks());

async function press(tree: any, label: string) {
  const target = tree.root.findAll((n: any) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function');
  await act(async () => {
    await target[target.length - 1].props.onPress();
  });
}

it('a reply chip prepares that reply for that message, and nothing is sent', async () => {
  mockMutate.mockResolvedValue({ data: { prepareWhatsAppReply: { success: true, draft } } });
  let tree: any;
  act(() => {
    tree = create(<WhatsAppReplyChips actions={[
      { type: 'whatsapp_reply', target: '7', label: 'Paso a las 5' }, { type: 'navigate', target: 'home', label: 'x' },
    ]} />);
  });
  expect(JSON.stringify(tree.toJSON())).toContain('Paso a las 5');
  expect(JSON.stringify(tree.toJSON())).not.toContain('"x"');
  await press(tree, 'Responder: Paso a las 5');
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ variables: { noticeId: '7', body: 'Paso a las 5' } }));
  expect(mockMutate).toHaveBeenCalledTimes(1);
});

it('the card shows where it goes and the exact text; Enviar sends it once with the shown hash', async () => {
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: draft } });
  mockMutate.mockResolvedValue({ data: { sendWhatsAppDraft: { success: true, draft: { ...draft, status: 'sending' } } } });
  let tree: any;
  await act(async () => {
    tree = create(<WhatsAppDraftCard draftId="d1" />);
  });
  const words = JSON.stringify(tree.toJSON());
  expect(words).toContain('Se enviará desde tu WhatsApp a Farmacia Central:');
  expect(words).toContain('Paso a las 5');
  await press(tree, 'Enviar por WhatsApp');
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ variables: { id: 'd1', displayHash: 'h1' } }));
  expect(tree.root.findAll((n: any) => n.props.accessibilityLabel === 'Enviar por WhatsApp')).toHaveLength(0);
  act(() => tree.unmount());
});

it('a lost answer with the message on its way: a card drawn again never offers Enviar again', async () => {
  mockQuery.mockResolvedValueOnce({ data: { whatsAppDraft: { ...draft, id: 'd2' } } })
    .mockResolvedValue({ data: { whatsAppDraft: { ...draft, id: 'd2', status: 'sending' } } });
  mockMutate.mockRejectedValue(new Error('network'));
  let first: any;
  await act(async () => {
    first = create(<WhatsAppDraftCard draftId="d2" />);
  });
  await press(first, 'Enviar por WhatsApp');
  act(() => first.unmount());
  let again: any;
  await act(async () => {
    again = create(<WhatsAppDraftCard draftId="d2" />);
  });
  expect(again.root.findAll((n: any) => n.props.accessibilityLabel === 'Enviar por WhatsApp')).toHaveLength(0);
  act(() => again.unmount());
});

it('a lost answer and the server never got it: Enviar comes back', async () => {
  mockQuery.mockResolvedValue({ data: { whatsAppDraft: { ...draft, id: 'd3' } } });
  mockMutate.mockRejectedValue(new Error('network'));
  let tree: any;
  await act(async () => {
    tree = create(<WhatsAppDraftCard draftId="d3" />);
  });
  await press(tree, 'Enviar por WhatsApp');
  expect(tree.root.findAll((n: any) => n.props.accessibilityLabel === 'Enviar por WhatsApp').length).toBeGreaterThan(0);
  act(() => tree.unmount());
});

it('"Otro": what she writes goes as instructions, and the assistant writes the full reply on a card', async () => {
  mockMutate.mockResolvedValue({ data: { prepareWhatsAppReply: { success: true, draft } } });
  let tree: any;
  act(() => {
    tree = create(<WhatsAppReplyChips actions={[{ type: 'whatsapp_other', target: '7', label: 'Otro…' }]} />);
  });
  await press(tree, 'Otra respuesta');
  act(() => tree.root.findByProps({ accessibilityLabel: 'Qué quieres responder' }).props.onChangeText('que paso mañana'));
  await press(tree, 'Preparar respuesta');
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ variables: { noticeId: '7', instructions: 'que paso mañana' } }));
  expect(tree.root.findAll((n: any) => n.props.accessibilityLabel === 'Qué quieres responder')).toHaveLength(0);
});

it('"Otro" that fails keeps what she wrote', async () => {
  mockMutate.mockResolvedValue({ data: { prepareWhatsAppReply: { success: false, error: 'Llegaste al límite de hoy.' } } });
  let tree: any;
  act(() => {
    tree = create(<WhatsAppReplyChips actions={[{ type: 'whatsapp_other', target: '7', label: 'Otro…' }]} />);
  });
  await press(tree, 'Otra respuesta');
  act(() => tree.root.findByProps({ accessibilityLabel: 'Qué quieres responder' }).props.onChangeText('que paso mañana'));
  await press(tree, 'Preparar respuesta');
  expect(tree.root.findByProps({ accessibilityLabel: 'Qué quieres responder' }).props.value).toBe('que paso mañana');
  expect(JSON.stringify(tree.toJSON())).toContain('Llegaste al límite de hoy.');
});

it('a WhatsApp notice is drawn as a card: who, when, the message as a bubble, what it seems', () => {
  mockLinkData = { whatsAppLink: { notices: [{ id: '7', kind: 'order', chat: 'Farmacia Central', preview: 'Su pedido está listo',
    summary: 'Pedido listo para retirar', time: '22:08', createdAt: '' }] } };
  let tree: any;
  act(() => {
    tree = create(<WhatsAppNoticeCard action={{ type: 'whatsapp_notice', target: '7', label: 'siguió' }} fallback="texto" />);
  });
  const words = JSON.stringify(tree.toJSON());
  for (const part of ['Farmacia Central', '22:08', 'siguió escribiendo', 'Su pedido está listo', 'Parece un pedido', 'Pedido listo para retirar']) {
    expect(words).toContain(part);
  }
  mockLinkData = null;
  act(() => {
    tree.update(<WhatsAppNoticeCard action={{ type: 'whatsapp_notice', target: '7', label: '' }} fallback="«J» te escribió" />);
  });
  expect(JSON.stringify(tree.toJSON())).toContain('«J» te escribió');  // gone: its own text
});
