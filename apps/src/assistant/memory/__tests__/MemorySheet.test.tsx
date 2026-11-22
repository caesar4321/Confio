import React from 'react';
import { Alert, Switch } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockClient = { query: jest.fn(), mutate: jest.fn() };
jest.mock('@apollo/client', () => ({ gql: (parts: string[]) => parts.join(''), useApolloClient: () => mockClient }));
jest.mock('react-native-safe-area-context', () => ({
  SafeAreaProvider: ({ children }: any) => children,
  SafeAreaView: ({ children }: any) => children,
}));
jest.mock('react-native-vector-icons/Feather', () => () => null);
jest.mock('../../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../../../contexts/AccountContext', () => ({
  useAccount: () => { throw new Error('read with the flag off'); },
}));

import { ASSISTANT_MEMORY_ENABLED } from '../flag';
import MemoryEntry from '../MemoryEntry';
import MemorySheet from '../MemorySheet';

const state = {
  openedFor: 'screen-1',
  available: true, canRemember: true, canRecall: true, factsEnabled: false, recallEnabled: true,
  facts: [{ id: '4', text: 'Responderte en portugués' }],
  quotes: [{ id: '9', text: 'quiero aprender a cocinar', saidAt: '2026-11-01T12:00:00Z' }],
};
let tree: renderer.ReactTestRenderer;
const flush = () => new Promise<void>((resolve) => { setImmediate(() => resolve()); });
const press = async (label: string) => {
  await act(async () => {
    tree.root.findAll((node) => node.props.accessibilityLabel === label && node.props.onPress)[0].props.onPress();
    await flush();
  });
};

beforeEach(async () => {
  jest.clearAllMocks();
  mockClient.query.mockResolvedValue({ data: { assistantMemory: state } });
  mockClient.mutate.mockResolvedValue({ data: {} });
  await act(async () => {
    tree = renderer.create(<MemorySheet onClose={jest.fn()} />);
    await flush();
  });
});
afterEach(async () => { await act(async () => { tree.unmount(); }); });

it('ships off and then reads nothing', async () => {
  expect(ASSISTANT_MEMORY_ENABLED).toBe(false);
  let entry: renderer.ReactTestRenderer;
  await act(async () => { entry = renderer.create(<MemoryEntry />); });
  expect(entry!.toJSON()).toBeNull();
});

it('reads without caching', () => {
  expect(mockClient.query.mock.calls[0][0].fetchPolicy).toBe('no-cache');
});

it('deletes one preference and one quote, naming no account', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  await press('Borrar: Responderte en portugués');
  expect(mockClient.mutate).not.toHaveBeenCalled();
  await act(async () => { (alert.mock.calls[0][2] as any[])[1].onPress(); await flush(); });
  alert.mockRestore();
  expect(mockClient.mutate.mock.calls[0][0].variables).toEqual({ factId: '4' });
  await press('Borrar: «quiero aprender a cocinar»');
  expect(mockClient.mutate.mock.calls[1][0].variables).toEqual({ quoteId: '9' });
});

it('switches each on and off', async () => {
  const [facts, recall] = tree.root.findAllByType(Switch);
  await act(async () => { facts.props.onValueChange(true); await flush(); });
  await act(async () => { recall.props.onValueChange(false); await flush(); });
  expect(mockClient.mutate.mock.calls.map(([call]) => call.variables))
    .toEqual([{ openedFor: 'screen-1', factsEnabled: true }, { openedFor: 'screen-1', recallEnabled: false }]);
});

it('shows what the server answers', async () => {
  mockClient.mutate.mockResolvedValue({
    data: { forgetAssistantMemory: { success: true, memory: { ...state, quotes: [] } } },
  });
  await press('Borrar: «quiero aprender a cocinar»');
  expect(JSON.stringify(tree.toJSON())).not.toContain('quiero aprender a cocinar');
});

it('does nothing from an alert left open after the sheet closed', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  await press('Borrar: Responderte en portugués');
  await act(async () => { tree.unmount(); });
  await act(async () => { (alert.mock.calls[0][2] as any[])[1].onPress(); await flush(); });
  alert.mockRestore();
  expect(mockClient.mutate).not.toHaveBeenCalled();
});

it('wipes only after confirming', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  const button = tree.root.findAll((node) => node.props.onPress && !node.props.accessibilityLabel
    && JSON.stringify(node.findAll((n) => typeof n.props.children === 'string').map((n) => n.props.children))
      .includes('Borrar toda mi memoria'))[0];
  await act(async () => { button.props.onPress(); });
  expect(mockClient.mutate).not.toHaveBeenCalled();
  await act(async () => { (alert.mock.calls[0][2] as any[])[1].onPress(); await flush(); });
  expect(mockClient.mutate.mock.calls[0][0].variables).toEqual({ openedFor: 'screen-1' });
});
