import React from 'react';
import Svg, { Path, Rect } from 'react-native-svg';

/**
 * The Pagar tab glyph: a QR code inside a scanner frame.
 *
 * Feather has no QR icon, and the `maximize` frame the tab used alone read as
 * "expand" — nothing on it said "scan a QR to pay". The frame says scan, the
 * three finder squares say QR; together they match the Pix / Transferencias
 * 3.0 stickers users see at the counter.
 */
export const QrPayIcon = ({ size = 30, color = '#fff' }: { size?: number; color?: string }) => (
  <Svg width={size} height={size} viewBox="0 0 32 32" fill="none">
    {/* scanner corners */}
    <Path
      d="M2 9V5a3 3 0 0 1 3-3h4M23 2h4a3 3 0 0 1 3 3v4M30 23v4a3 3 0 0 1-3 3h-4M9 30H5a3 3 0 0 1-3-3v-4"
      stroke={color}
      strokeWidth={2.4}
      strokeLinecap="round"
    />
    {/* finder patterns */}
    <Rect x={8} y={8} width={6} height={6} rx={1} stroke={color} strokeWidth={2} />
    <Rect x={18} y={8} width={6} height={6} rx={1} stroke={color} strokeWidth={2} />
    <Rect x={8} y={18} width={6} height={6} rx={1} stroke={color} strokeWidth={2} />
    {/* data modules */}
    <Rect x={18} y={18} width={2.6} height={2.6} fill={color} />
    <Rect x={21.4} y={21.4} width={2.6} height={2.6} fill={color} />
    <Rect x={18} y={21.4} width={2.6} height={2.6} fill={color} />
  </Svg>
);
