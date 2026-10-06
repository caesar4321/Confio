import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Linking, Text, TouchableOpacity} from 'react-native';
import AdditionalDocumentScreen from '../AdditionalDocumentScreen';
import {createAdditionalDocumentBrowserSession} from '../../services/localMoney';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({useSafeAreaInsets: () => ({top: 0, bottom: 0, left: 0, right: 0})}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({goBack: jest.fn(), isFocused: () => true}),
  useRoute: () => ({params: {idCountry: 'COL', documentTypes: ['P']}}),
}));
jest.mock('../../services/localMoney', () => ({
  createAdditionalDocumentSession: jest.fn(),
  createAdditionalDocumentBrowserSession: jest.fn(),
  syncAdditionalDocument: jest.fn(),
}));
jest.mock('../../services/diditService', () => ({
  getDiditErrorMessage: jest.fn(),
  getDiditResultSessionId: jest.fn(),
  startDiditVerification: jest.fn(),
  openDiditSessionUrl: jest.requireActual('../../services/diditService').openDiditSessionUrl,
}));

const browserButton = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(n => n.type === TouchableOpacity
    && n.findAllByType(Text).some(t => String(t.props.children).includes('navegador')), {deep: false});

it('verifies the same document on Didit\'s page in the browser', async () => {
  (createAdditionalDocumentBrowserSession as jest.Mock).mockResolvedValue(
    {sessionId: 'sess', sessionUrl: 'https://verify.didit.me/session/sess'});
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AdditionalDocumentScreen />); });
  expect(browserButton(tree)).toHaveLength(1);
  await act(async () => { await browserButton(tree)[0].props.onPress(); });
  expect(createAdditionalDocumentBrowserSession).toHaveBeenCalledWith('COL', ['P']);
  expect(open).toHaveBeenCalledWith('https://verify.didit.me/session/sess');
  await act(async () => tree.unmount());
  open.mockRestore();
});

it('never opens a link that is not Didit\'s', async () => {
  (createAdditionalDocumentBrowserSession as jest.Mock).mockResolvedValue(
    {sessionId: 'sess', sessionUrl: 'https://evil.example/session/sess'});
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AdditionalDocumentScreen />); });
  await act(async () => { await browserButton(tree)[0].props.onPress(); });
  expect(open).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
  open.mockRestore();
});

it('never shows a raw transport error', async () => {
  (createAdditionalDocumentBrowserSession as jest.Mock).mockRejectedValue(
    Object.assign(new Error('Response not successful: Received status code 400'), {networkError: {statusCode: 400}}));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AdditionalDocumentScreen />); });
  await act(async () => { await browserButton(tree)[0].props.onPress(); });
  const texts = tree.root.findAllByType(Text).map(t => String(t.props.children));
  expect(texts.some(t => t.includes('status code'))).toBe(false);
  expect(texts).toContain('No se pudo abrir la verificación en el navegador.');
  await act(async () => tree.unmount());
});
