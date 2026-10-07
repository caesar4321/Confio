import React from 'react';
import Svg, { Circle, Path } from 'react-native-svg';

// The Acciones de EE.UU. wallet mark.
//
// A category mark, not a coin: the slot holds 400+ tickers. It keeps the
// trend-arrow glyph people already know, on its own navy disc (design review
// decision 12, S1, 2026-10-07): each category mark has its own color (mint
// coins, emerald Cuenta inteligente bulb, navy stocks), so the rows read as
// different kinds of wallet at a glance.
const NAVY = '#1E3A8A';
const TREND = '#34D399';

interface StocksMarkProps {
  size?: number;
}

const StocksMark: React.FC<StocksMarkProps> = ({ size = 44 }) => (
  <Svg width={size} height={size} viewBox="0 0 100 100">
    <Circle cx={50} cy={50} r={50} fill={NAVY} />
    <Path
      d="M17 71 L39 49 L53 61 L78 34"
      fill="none"
      stroke={TREND}
      strokeWidth={12.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <Path
      d="M60 32 H80 V52"
      fill="none"
      stroke={TREND}
      strokeWidth={12.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default StocksMark;
