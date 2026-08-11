import React from 'react';
import renderer, { act, ReactTestRenderer } from 'react-test-renderer';

import { LoadingOverlay } from '../../LoadingOverlay';
import { StockTradeLoadingOverlay } from '../StockTradeLoadingOverlay';

const renderOverlay = (side: 'buy' | 'sell', visible = true) => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = renderer.create(
      <StockTradeLoadingOverlay visible={visible} side={side} ticker="TSLA" />,
    );
  });
  return tree.root.findByType(LoadingOverlay).props;
};

describe('StockTradeLoadingOverlay', () => {
  it('uses the shared spinning modal while a stock purchase settles', () => {
    expect(renderOverlay('buy')).toMatchObject({
      visible: true,
      message: 'Comprando TSLA…',
    });
  });

  it('uses the shared spinning modal while a stock sale settles', () => {
    expect(renderOverlay('sell')).toMatchObject({
      visible: true,
      message: 'Vendiendo TSLA…',
    });
  });
});
