import React from 'react';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

// The Cuenta inteligente wallet mark (design review decision 11, B2): a lit
// bulb on the deep emerald of the "Tu mes" hero. Its own color on purpose:
// the category marks don't all have to match the mint coins (StocksMark is
// navy). Never a padlock, sparkle or violet: those read as a locked AI
// feature, which this account is not.
const DISC = '#065F46';
const BULB = '#FCD34D';
const BASE = '#F9F7F4';

interface CuentaInteligenteMarkProps {
  size?: number;
}

const CuentaInteligenteMark: React.FC<CuentaInteligenteMarkProps> = ({ size = 44 }) => (
  <Svg width={size} height={size} viewBox="0 0 100 100">
    <Circle cx={50} cy={50} r={50} fill={DISC} />
    <Path
      d="M50 20 C35 20 26 31 26 43 C26 52 31 57 36 62 C39 65 40 68 40 71 H60 C60 68 61 65 64 62 C69 57 74 52 74 43 C74 31 65 20 50 20 Z"
      fill={BULB}
    />
    <Rect x={40} y={75} width={20} height={6} rx={3} fill={BASE} />
    <Rect x={43} y={83} width={14} height={5} rx={2.5} fill={BASE} />
  </Svg>
);

export default CuentaInteligenteMark;
