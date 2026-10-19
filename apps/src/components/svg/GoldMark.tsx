import React from 'react';
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from 'react-native-svg';

// Gold (Tether Gold, XAUt): a bar on a warm gold disc. Gradients come from
// react-native-svg (house rule: no linear-gradient library).
const GoldMark: React.FC<{ size?: number }> = ({ size = 44 }) => (
  <Svg width={size} height={size} viewBox="0 0 100 100">
    <Defs>
      <LinearGradient id="goldDisc" x1="0" y1="0" x2="1" y2="1">
        <Stop offset="0" stopColor="#FDE68A" />
        <Stop offset="1" stopColor="#B45309" />
      </LinearGradient>
    </Defs>
    <Circle cx={50} cy={50} r={50} fill="url(#goldDisc)" />
    <Path d="M28 66 L36 42 H64 L72 66 Z" fill="#FFFBEB" />
    <Path d="M36 42 H64 L60 50 H40 Z" fill="#FEF3C7" />
  </Svg>
);

export default GoldMark;
