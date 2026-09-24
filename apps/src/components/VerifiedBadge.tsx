import React from 'react';
import Svg, { Path } from 'react-native-svg';
import { colors } from '../config/theme';

const LOBES = 10;
const CENTER = 12;
const PEAK = 11.5; // how far the scallops reach
const VALLEY = 9.9; // how deep they dip

/**
 * Scalloped rosette outline on a 24×24 grid. Each lobe is one quadratic
 * curve from valley to valley; the control point sits where the curve's
 * midpoint lands exactly on PEAK.
 */
function rosettePath(): string {
  const step = (2 * Math.PI) / LOBES;
  const point = (radius: number, angle: number) =>
    `${(CENTER + radius * Math.sin(angle)).toFixed(3)} ${(CENTER - radius * Math.cos(angle)).toFixed(3)}`;
  const control = 2 * PEAK - VALLEY * Math.cos(step / 2);
  let d = `M ${point(VALLEY, 0)}`;
  for (let i = 0; i < LOBES; i += 1) {
    const start = i * step;
    d += ` Q ${point(control, start + step / 2)} ${point(VALLEY, start + step)}`;
  }
  return `${d} Z`;
}

const ROSETTE = rosettePath();
const CHECK = 'M7.6 12.3 L10.6 15.2 L16.4 9.2';

type Props = {
  size?: number;
  /** Rosette fill. */
  color?: string;
  /** Check mark stroke. */
  checkColor?: string;
};

/** The Oficial mark: a filled scalloped badge with a check, as on social networks. */
export function VerifiedBadge({ size = 16, color = colors.primaryDark, checkColor = '#FFFFFF' }: Props) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" accessibilityElementsHidden importantForAccessibility="no">
      <Path d={ROSETTE} fill={color} />
      <Path d={CHECK} fill="none" stroke={checkColor} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
    </Svg>
  );
}
