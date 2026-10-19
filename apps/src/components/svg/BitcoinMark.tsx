import React from 'react';
import Svg, { Circle, Text as SvgText } from 'react-native-svg';

// Bitcoin's orange disc with the ₿ glyph — the asset people recognise.
const ORANGE = '#F7931A';

const BitcoinMark: React.FC<{ size?: number }> = ({ size = 44 }) => (
  <Svg width={size} height={size} viewBox="0 0 100 100">
    <Circle cx={50} cy={50} r={50} fill={ORANGE} />
    <SvgText
      x={50}
      y={70}
      fontSize={58}
      fontWeight="bold"
      fill="#FFFFFF"
      textAnchor="middle"
      rotation={-14}
      origin="50, 50"
    >
      ₿
    </SvgText>
  </Svg>
);

export default BitcoinMark;
