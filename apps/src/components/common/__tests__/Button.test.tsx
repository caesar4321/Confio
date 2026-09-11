/**
 * The label sits in a row container, where React Native text never wraps
 * unless it may shrink; without that, long labels at large accessibility font
 * sizes run past the button and get clipped.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { StyleSheet, Text } from 'react-native';
import { Button } from '../Button';

const labelStyle = (element: React.ReactElement) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(element);
  });
  return StyleSheet.flatten(tree.root.findByType(Text).props.style);
};

describe('Button', () => {
  it('lets long labels wrap instead of overflowing the button', () => {
    expect(labelStyle(<Button title="Confirmar cambio" onPress={() => {}} />))
      .toMatchObject({ flexShrink: 1, textAlign: 'center' });
  });

  it('keeps wrapping when a caller overrides the text style', () => {
    expect(labelStyle(<Button title="Cancelar" variant="ghost" onPress={() => {}} textStyle={{ color: 'red' }} />))
      .toMatchObject({ flexShrink: 1, textAlign: 'center', color: 'red' });
  });
});
