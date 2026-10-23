import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
import { CategoryPicker } from '../CategoryPicker';

const cats = Array.from({ length: 12 }, (_, i) => ({ key: `k${i}`, label: `Cat ${i}`, group: i < 6 ? 'Moda' : 'Hogar' }));
cats.push({ key: 'cafe', label: 'Café y té', group: 'Comida envasada' });

const labels = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());

it('groups under headings and searches without accents', () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<CategoryPicker categories={cats} selected={[]} onToggle={jest.fn()} />); });
  expect(labels(tree)).toContain('Comida envasada');
  const search = tree.root.findAll((n) => n.props.placeholder === 'Buscar categoría')[0];
  act(() => { search.props.onChangeText('cafe'); });
  expect(labels(tree)).toContain('Café y té');
  expect(labels(tree)).not.toContain('Cat 1');
});

it('stops adding at the limit but still lets you unselect', () => {
  const onToggle = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(<CategoryPicker categories={cats} selected={['k0', 'k1']} multiple max={2} onToggle={onToggle} />);
  });
  const chip = (label: string) => tree.root.findAll((n) => n.props.accessibilityRole === 'checkbox'
    && typeof n.props.onPress === 'function'
    && n.findAll((c) => c.props.children === label).length > 0)[0];
  act(() => { chip('Cat 5').props.onPress(); });
  expect(onToggle).not.toHaveBeenCalled();
  act(() => { chip('Cat 0').props.onPress(); });
  expect(onToggle).toHaveBeenCalledWith('k0');
  expect(labels(tree)).toContain('Puedes elegir hasta');
});
