import React from 'react';
import renderer, {act} from 'react-test-renderer';

const mockAcknowledge = jest.fn();
jest.mock('@apollo/client', () => ({
  useMutation: () => [mockAcknowledge, {loading: false}],
  gql: () => 'GQL',
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../hooks/useGmMarket', () => ({ACKNOWLEDGE_GM_COMPLEX_PRODUCTS: 'ACK'}));

import {StockRiskSheet} from '../StockRiskSheet';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(n => typeof n.props.children === 'string').map(n => n.props.children as string);

const pressByText = async (tree: renderer.ReactTestRenderer, label: string) => {
  const target = tree.root.findAll(n => n.props.accessibilityRole === 'button'
    && n.findAll(c => c.props.children === label).length > 0)[0];
  await act(async () => { await target.props.onPress(); });
};

const setup = (overrides: Partial<React.ComponentProps<typeof StockRiskSheet>> = {}) => {
  const props = {
    visible: true,
    title: 'Antes de tu primer fondo apalancado o inverso',
    points: ['Se reajustan cada día.', 'Puedes perder gran parte.'],
    version: 1,
    onAccepted: jest.fn(),
    onClose: jest.fn(),
    onRefresh: jest.fn(() => Promise.resolve()),
    ...overrides,
  };
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<StockRiskSheet {...props} />); });
  return {tree, props};
};

beforeEach(() => mockAcknowledge.mockReset());

it('shows the served disclosure and confirms the version it showed', async () => {
  mockAcknowledge.mockResolvedValue({data: {acknowledgeGmComplexProducts: {success: true}}});
  const {tree, props} = setup();
  expect(texts(tree)).toEqual(expect.arrayContaining(['Se reajustan cada día.', 'Puedes perder gran parte.']));
  await pressByText(tree, 'Entiendo los riesgos');
  expect(mockAcknowledge).toHaveBeenCalledWith({variables: {version: 1}});
  expect(props.onAccepted).toHaveBeenCalled();
});

it('hands back the token taken when the person tapped, not when the save landed', async () => {
  let resolve!: (v: unknown) => void;
  mockAcknowledge.mockReturnValue(new Promise(r => { resolve = r; }));
  let flow = 1;
  const {tree, props} = setup({beginAccept: () => flow});
  const pending = pressByText(tree, 'Entiendo los riesgos');
  flow = 2; // dismissed, edited and reopened while saving
  resolve({data: {acknowledgeGmComplexProducts: {success: true}}});
  await pending;
  expect(props.onAccepted).toHaveBeenCalledWith(1);
});

it('reloads the text instead of passing when the disclosure changed', async () => {
  mockAcknowledge.mockResolvedValue({data: {acknowledgeGmComplexProducts: {success: false, error: 'OUTDATED_DISCLOSURE'}}});
  const {tree, props} = setup();
  await pressByText(tree, 'Entiendo los riesgos');
  expect(props.onAccepted).not.toHaveBeenCalled();
  expect(props.onRefresh).toHaveBeenCalled();
  expect(texts(tree)).toContain('El texto cambió. Léelo de nuevo antes de confirmar.');
});

it('cannot be confirmed before the disclosure has loaded', async () => {
  const {tree, props} = setup({points: [], version: null});
  await pressByText(tree, 'Entiendo los riesgos');
  expect(mockAcknowledge).not.toHaveBeenCalled();
  expect(props.onAccepted).not.toHaveBeenCalled();
});
