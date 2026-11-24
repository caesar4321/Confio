import React from 'react';
import Svg, { Path, Rect, Text as SvgText } from 'react-native-svg';

/** A calendar page with today's day: the phone's calendars (Apple, Google or others), no one brand. */
export default function CalendarMark({ size = 24, day = new Date().getDate() }: { size?: number; day?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 48 48">
      <Rect x="4" y="7" width="40" height="37" rx="7" fill="#FFFFFF" stroke="#E5E7EB" strokeWidth="1.5" />
      <Path d="M11 7h26a7 7 0 0 1 7 7v4H4v-4a7 7 0 0 1 7-7z" fill="#EF4444" />
      <Rect x="13" y="3" width="4" height="9" rx="2" fill="#991B1B" />
      <Rect x="31" y="3" width="4" height="9" rx="2" fill="#991B1B" />
      <SvgText x="24" y="38" fontSize="18" fontWeight="700" fill="#111827" textAnchor="middle">{String(day)}</SvgText>
    </Svg>
  );
}
