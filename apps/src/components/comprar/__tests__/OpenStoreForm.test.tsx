import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Keyboard } from 'react-native';

jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../../contexts/CountryContext', () => ({ useCountry: () => ({ userCountry: null }) }));
jest.mock('../../common/BrandFieldBackground', () => ({ BrandFieldBackground: 'BrandField' }));

import { OpenStoreForm } from '../OpenStoreForm';

const render = (props: Partial<React.ComponentProps<typeof OpenStoreForm>> = {}) => {
  const onSubmit = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(
      <OpenStoreForm feeBps={800} city="La Paz" accountLabel="tu cuenta personal" submitting={false}
        error={null} onBack={jest.fn()} onPickCity={jest.fn()} onSubmit={onSubmit} {...props} />,
    );
  });
  return { tree, onSubmit };
};

const button = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll((n) => n.props.testID === 'open-store-submit')[0];
// The name and description inputs, by their placeholders (first match each).
const fields = (tree: renderer.ReactTestRenderer) => [
  tree.root.findAll((n) => n.props.placeholder === 'Ej.: Tejidos Doña Ana')[0],
  tree.root.findAll((n) => String(n.props.placeholder || '').startsWith('Ej.: chompas y chalinas'))[0],
];

it('shows the fee from the server, never a hardcoded number', () => {
  // A comma-decimal country (Bolivia): 7,5%.
  require('../../../utils/numberLocale').setNumberLocaleCountry('BO');
  const { tree } = render({ feeBps: 750 });
  const text = JSON.stringify(tree.toJSON());
  expect(text).toContain('Pagas 7,5% solo cuando vendes.');
  const noFee = render({ feeBps: null });
  expect(JSON.stringify(noFee.tree.toJSON())).toContain('Pagas solo cuando vendes.');
});

it('enables the button only with a name and a city, and submits trimmed values', () => {
  const dismiss = jest.spyOn(Keyboard, 'dismiss').mockImplementation(() => {});
  const { tree, onSubmit } = render();
  expect(button(tree).props.disabled).toBe(true);
  const [name, description] = fields(tree);
  act(() => { name.props.onChangeText('  Tejidos Ana  '); });
  act(() => { description.props.onChangeText(' Chompas de alpaca '); });
  expect(button(tree).props.disabled).toBe(false);
  act(() => { button(tree).props.onPress(); });
  expect(dismiss).toHaveBeenCalled();
  expect(onSubmit).toHaveBeenCalledWith({ name: 'Tejidos Ana', description: 'Chompas de alpaca', shipsOutsideCity: false });
  dismiss.mockRestore();
});

it('cannot submit without a city', () => {
  const { tree } = render({ city: '' });
  const [name] = fields(tree);
  act(() => { name.props.onChangeText('Tejidos Ana'); });
  expect(button(tree).props.disabled).toBe(true);
});

it('the keyboard has a way out: Siguiente moves on, the scroll view dismisses it', () => {
  const { tree } = render();
  const [name, description] = fields(tree);
  expect(name.props.returnKeyType).toBe('next');
  expect(description.props.blurOnSubmit).toBe(true);
  const scroll = tree.root.find((n) => n.props.keyboardShouldPersistTaps === 'handled');
  expect(['interactive', 'on-drag']).toContain(scroll.props.keyboardDismissMode);
});
