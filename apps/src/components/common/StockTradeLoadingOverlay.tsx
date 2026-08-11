import React from 'react';

import { LoadingOverlay } from '../LoadingOverlay';

type Props = {
  visible: boolean;
  side: 'buy' | 'sell';
  ticker: string;
};

/** Keeps buy and sell settlement feedback on the app-wide loading modal. */
export const StockTradeLoadingOverlay: React.FC<Props> = ({ visible, side, ticker }) => (
  <LoadingOverlay
    visible={visible}
    message={`${side === 'buy' ? 'Comprando' : 'Vendiendo'} ${ticker}…`}
  />
);
