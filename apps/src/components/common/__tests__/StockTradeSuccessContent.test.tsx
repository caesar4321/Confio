import React from 'react';
import { ScrollView, StyleSheet, Text } from 'react-native';
import renderer, { act, ReactTestRenderer } from 'react-test-renderer';

import { StockTradeSuccessContent } from '../StockTradeSuccessContent';

describe('StockTradeSuccessContent', () => {
  it('renders stock settlement content in a vertically scrollable container', () => {
    let tree!: ReactTestRenderer;
    act(() => {
      tree = renderer.create(
        <StockTradeSuccessContent>
          <Text>Ver mi posición</Text>
        </StockTradeSuccessContent>,
      );
    });

    const scroll = tree.root.findByType(ScrollView);
    expect(scroll.props.testID).toBe('stock-trade-success-scroll');
    expect(scroll.props.showsVerticalScrollIndicator).toBe(false);
    expect(StyleSheet.flatten(scroll.props.style)).toMatchObject({ flex: 1 });
    expect(StyleSheet.flatten(scroll.props.contentContainerStyle)).toMatchObject({
      flexGrow: 1,
      alignItems: 'center',
      paddingBottom: 32,
    });
  });
});
