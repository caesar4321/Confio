import React from 'react';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

// The Inversiones wallet mark (Home): one row for stocks, gold and bitcoin.
//
// A category mark like StocksMark, on its own deep-emerald disc: three
// rising bars (holdings that grow) and a gold coin (the metal and coins
// that now sit next to the stocks). Never a single asset's logo.
const DISC = '#065F46';
const BAR = '#6EE7B7';
const COIN = '#FBBF24';

interface InvestMarkProps {
  size?: number;
}

const InvestMark: React.FC<InvestMarkProps> = ({ size = 44 }) => (
  <Svg width={size} height={size} viewBox="0 0 100 100">
    <Circle cx={50} cy={50} r={50} fill={DISC} />
    <Rect x={22} y={56} width={13} height={22} rx={3} fill={BAR} />
    <Rect x={41} y={44} width={13} height={34} rx={3} fill={BAR} />
    <Rect x={60} y={32} width={13} height={46} rx={3} fill={BAR} />
    <Circle cx={72} cy={27} r={11} fill={COIN} />
    <Path d="M72 21 V33" stroke={DISC} strokeWidth={3.5} strokeLinecap="round" />
  </Svg>
);

export default InvestMark;
