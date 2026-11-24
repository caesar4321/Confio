import React from 'react';
import Svg, { Path, Polygon } from 'react-native-svg';

/** Gmail's mark, for the "connect Gmail" card. */
export default function GmailLogo({ size = 24 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="3 6 42 36">
      <Path fill="#4CAF50" d="M45,16.2l-5,2.75l-5,4.75L35,40h7c1.657,0,3-1.343,3-3V16.2z" />
      <Path fill="#1E88E5" d="M3,16.2l3.614,1.71L13,23.7V40H6c-1.657,0-3-1.343-3-3V16.2z" />
      <Polygon fill="#E53935" points="35,11.2 24,19.45 13,11.2 12,17 13,23.7 24,31.95 35,23.7 36,17" />
      <Path fill="#C62828" d="M3,12.298V16.2l10,7.5V11.2L9.876,8.859C9.132,8.301,8.228,8,7.298,8h0C4.924,8,3,9.924,3,12.298z" />
      <Path fill="#FBC02D" d="M45,12.298V16.2l-10,7.5V11.2l3.124-2.341C38.868,8.301,39.772,8,40.702,8h0C43.076,8,45,9.924,45,12.298z" />
    </Svg>
  );
}
