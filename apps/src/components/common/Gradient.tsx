import React from 'react';
import { View, StyleSheet, ViewProps, DimensionValue, SafeAreaView } from 'react-native';
import Svg, { Defs, Rect, LinearGradient, Stop } from 'react-native-svg';

type GradientProps = {
  fromColor: string;
  toColor: string;
  children?: any;
  height?: DimensionValue;
  opacityColor1?: number;
  opacityColor2?: number;
} & ViewProps;

export function Gradient({
  children,
  fromColor,
  toColor,
  height = '100%',
  opacityColor1 = 1,
  opacityColor2 = 1,
  ...otherViewProps
}: GradientProps) {
  const gradientUniqueId = `grad${fromColor}+${toColor}`.replace(/[^a-zA-Z0-9 ]/g, '');
  
  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={[styles.container, otherViewProps.style]} {...otherViewProps}>
        <View style={[styles.gradient, { height }]}>
          <Svg height="100%" width="100%" style={StyleSheet.absoluteFillObject}>
            <Defs>
              <LinearGradient id={gradientUniqueId} x1="0%" y1="0%" x2="0%" y2="100%">
                <Stop offset="0" stopColor={fromColor} stopOpacity={opacityColor1} />
                <Stop offset="1" stopColor={toColor} stopOpacity={opacityColor2} />
              </LinearGradient>
            </Defs>
            <Rect width="100%" height="100%" fill={`url(#${gradientUniqueId})`} />
          </Svg>
        </View>
        <View style={styles.content}>
          {children}
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  container: {
    flex: 1,
    width: '100%',
    height: '100%',
  },
  gradient: {
    ...StyleSheet.absoluteFillObject,
    zIndex: 0,
  },
  content: {
    flex: 1,
    zIndex: 1,
    width: '100%',
    height: '100%',
  },
}); 