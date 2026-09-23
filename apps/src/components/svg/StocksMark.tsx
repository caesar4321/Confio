import React from 'react';
import Svg, { Circle, Path } from 'react-native-svg';

// The Acciones de EE.UU. wallet mark.
//
// It sits in a column of coin logos (cUSD+, cUSD, CONFIO) that are flat brand
// marks: a mint disc with a heavy off-white glyph filling it. A thin Feather
// arrow on a darker emerald disc read as a UI button among them. This draws the
// category in the coins' own language — same fill, same glyph weight as the $ —
// while the glyph itself (a trend, not a currency sign, and no bite out of the
// disc) keeps it from reading as one more Confío coin.
//
// Colors are sampled from cUSD.png / CONFIO.png; no theme token matches them.
const MINT = '#72D9BC';
const OFF_WHITE = '#F9F7F4';

interface StocksMarkProps {
  size?: number;
}

const StocksMark: React.FC<StocksMarkProps> = ({ size = 44 }) => (
  <Svg width={size} height={size} viewBox="0 0 100 100">
    <Circle cx={50} cy={50} r={50} fill={MINT} />
    <Path
      d="M17 71 L39 49 L53 61 L78 34"
      fill="none"
      stroke={OFF_WHITE}
      strokeWidth={12.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <Path
      d="M60 32 H80 V52"
      fill="none"
      stroke={OFF_WHITE}
      strokeWidth={12.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </Svg>
);

export default StocksMark;
