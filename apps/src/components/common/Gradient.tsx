import React from 'react';
import { View, StyleSheet, ViewProps, ViewStyle } from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';

interface GradientProps {
  fromColor: string;
  toColor: string;
  children?: React.ReactNode;
  style?: ViewStyle;
}

export function Gradient({
  children,
  fromColor,
  toColor,
  style,
}: GradientProps) {
  return (
    <View style={[styles.container, style]}>
      <Svg height="100%" width="100%" style={StyleSheet.absoluteFill}>
        <Defs>
          <LinearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={fromColor} stopOpacity="1" />
            <Stop offset="1" stopColor={toColor} stopOpacity="1" />
          </LinearGradient>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#grad)" />
      </Svg>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    width: '100%',
    height: '100%',
  },
}); 