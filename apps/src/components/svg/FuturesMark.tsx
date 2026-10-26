import React from 'react';
import Svg, { Circle, Path } from 'react-native-svg';

// The Futuros category mark: two opposing arrows on an ink disc — a price
// can be followed up (largo, emerald) or down (corto, sky blue). Like the
// navy stocks disc and the gold coin, its own color so the Invertir cards
// read as different kinds of instrument at a glance.
const INK = '#0F172A';
const LONG = '#34D399';
const SHORT = '#60A5FA';

const FuturesMark: React.FC<{ size?: number }> = ({ size = 44 }) => (
  <Svg width={size} height={size} viewBox="0 0 100 100">
    <Circle cx={50} cy={50} r={50} fill={INK} />
    {/* up arrow, left */}
    <Path d="M36 70 V32" stroke={LONG} strokeWidth={10} strokeLinecap="round" />
    <Path d="M24 44 L36 31 L48 44" fill="none" stroke={LONG} strokeWidth={10} strokeLinecap="round"
      strokeLinejoin="round" />
    {/* down arrow, right */}
    <Path d="M64 30 V68" stroke={SHORT} strokeWidth={10} strokeLinecap="round" />
    <Path d="M52 56 L64 69 L76 56" fill="none" stroke={SHORT} strokeWidth={10} strokeLinecap="round"
      strokeLinejoin="round" />
  </Svg>
);

export default FuturesMark;
