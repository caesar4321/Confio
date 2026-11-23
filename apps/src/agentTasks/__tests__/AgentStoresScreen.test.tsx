// Stores that keep the person's sign-in: forgetting one never locks the list.
import React from 'react';
import { Alert } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockForget = jest.fn();
const mockRefetch = jest.fn(async () => ({}));
let mockStores: string[] | null = ['mercadolivre.com.br', 'mercadolibre.com.mx'];

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../navigation/Header', () => ({ Header: () => null }));
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: jest.fn() }) }));
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useQuery: () => ({ data: { agentStores: mockStores }, loading: false, refetch: mockRefetch }),
  useMutation: () => [mockForget],
}));

import { AgentStoresScreen } from '../AgentStoresScreen';

const appButtons = (tree: renderer.ReactTestRenderer, title: string) =>
  tree.root.findAll((n) => n.props.title === title && typeof n.props.onPress === 'function'
    && n.props.loading !== undefined);

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockStores = ['mercadolivre.com.br', 'mercadolibre.com.mx'];
});
afterEach(() => jest.useRealTimers());

it('a "Cerrar sesión" that never answers stops holding the list after a while', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  mockForget.mockReturnValueOnce(new Promise(() => undefined));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AgentStoresScreen />); });
  await act(async () => { appButtons(tree, 'Cerrar sesión')[0].props.onPress(); });
  const confirm = (alert.mock.calls[0][2] as any[]).find((b) => b.style === 'destructive');
  act(() => { confirm.onPress(); });
  expect(appButtons(tree, 'Cerrar sesión')[1].props.disabled).toBe(true);
  await act(async () => { jest.advanceTimersByTime(30_000); });
  expect(appButtons(tree, 'Cerrar sesión')[1].props.disabled).toBe(false);
  expect(mockRefetch).toHaveBeenCalled();
});

it('outside the personal account it says where the stores are', async () => {
  mockStores = null;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AgentStoresScreen />); });
  const words = tree.root.findAllByType(require('react-native').Text).map((n) => [n.props.children].flat().join(''));
  expect(words.some((w) => w.includes('cuenta personal'))).toBe(true);
});
