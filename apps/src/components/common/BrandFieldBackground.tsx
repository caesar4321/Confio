import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Defs, Stop, LinearGradient as SvgLinearGradient, Rect, Circle } from 'react-native-svg';

import { colors } from '../../config/theme';

type Props = {
  /** Unique gradient id — RNSVG brushes collide across mounted instances. */
  id: string;
  fromColor?: string;
  toColor?: string;
  ringCx?: string;
  ringCy?: string;
  ringR?: number;
  ringWidth?: number;
};

/**
 * The brand-field backdrop: vertical gradient + cropped coin ring, rendered
 * as an absolute fill behind a header/hero. It measures itself and passes
 * explicit dimensions to the Svg (keyed remount per size) because an
 * absoluteFill Svg with percentage sizes does NOT repaint when its parent
 * grows — async content (balances, badges, ticker lines) otherwise leaves a
 * stale gradient with a flat band where the view grew.
 *
 * Layout rule: the parent field must carry NO padding (Yoga insets absolute
 * children by parent padding) — put padding on an inner wrapper.
 */
export const BrandFieldBackground = ({
  id,
  fromColor = colors.primary,
  toColor = colors.primaryDark,
  ringCx = '105%',
  ringCy = '30%',
  ringR = 90,
  ringWidth = 22,
}: Props) => {
  const [size, setSize] = useState({ width: 0, height: 0 });

  return (
    <View
      style={StyleSheet.absoluteFill}
      pointerEvents="none"
      onLayout={(e) => {
        const { width, height } = e.nativeEvent.layout;
        setSize((prev) =>
          prev.width === width && prev.height === height ? prev : { width, height }
        );
      }}
    >
      <Svg
        key={`${id}-${size.width}x${size.height}`}
        width={size.width || '100%'}
        height={size.height || '100%'}
      >
        <Defs>
          <SvgLinearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={fromColor} />
            <Stop offset="1" stopColor={toColor} />
          </SvgLinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill={`url(#${id})`} />
        <Circle
          cx={ringCx}
          cy={ringCy}
          r={ringR}
          stroke={colors.white}
          strokeWidth={ringWidth}
          strokeOpacity="0.10"
          fill="none"
        />
      </Svg>
    </View>
  );
};
