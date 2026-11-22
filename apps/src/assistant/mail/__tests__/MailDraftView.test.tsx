import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockMutate = jest.fn();
jest.mock('@apollo/client', () => ({
  gql: (parts: TemplateStringsArray) => parts.join(''),
  useMutation: (document: string) => [(options: any) => mockMutate(document.includes('mutation SendAssistant') ? 'send' : 'update', options)],
}));
jest.mock('../../../components/common/AppText', () => ({
  Text: require('react-native').Text,
  TextInput: require('react-native').TextInput,
}));

import MailDraftView from '../MailDraftView';

const DRAFT = {
  id: 'd1', sender: 'owner@gmail.example', to: 'ana@example.com', subject: 'Hola', body: 'Voy el martes.',
  isReply: false, replyToDiffers: false, canSend: true, displayHash: 'old',
};

let tree: renderer.ReactTestRenderer;
const flush = () => new Promise<void>((resolve) => { setImmediate(() => resolve()); });
const labels = () => tree.root.findAll((node) => typeof node.props.label === 'string').map((node) => node.props.label);
async function press(label: string) {
  await act(async () => {
    tree.root.findAll((node) => node.props.label === label)[0].props.onPress();
    await flush();
  });
}

beforeEach(() => {
  mockMutate.mockReset();
  act(() => {
    tree = renderer.create(React.createElement(MailDraftView, { initial: DRAFT, onBack: jest.fn(), onSent: jest.fn() }));
  });
});
afterEach(() => act(() => tree.unmount()));

it('sends only after the confirmation, with the hash of what it showed', async () => {
  mockMutate.mockImplementation(async (kind: string) => ({
    data: kind === 'send'
      ? { sendAssistantMailDraft: { success: true } }
      : { updateAssistantMailDraft: { success: true, draft: { ...DRAFT, displayHash: 'stored' } } },
  }));
  expect(labels()).not.toContain('Enviar este correo');
  await press('Revisar y enviar');
  expect(mockMutate.mock.calls.map(([kind]) => kind)).toEqual(['update']);
  await press('Enviar este correo');
  expect(mockMutate).toHaveBeenLastCalledWith('send', { variables: { id: 'd1', displayHash: 'stored' } });
});

it('offers no second send when the result is unknown', async () => {
  mockMutate.mockImplementation(async (kind: string) => {
    if (kind === 'send') {
      throw new Error('network');
    }
    return { data: { updateAssistantMailDraft: { success: true, draft: DRAFT } } };
  });
  await press('Revisar y enviar');
  await press('Enviar este correo');
  expect(labels()).not.toContain('Enviar este correo');
});
