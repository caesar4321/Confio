import React, { useEffect, useRef } from 'react';
import { Animated, Easing, ViewStyle } from 'react-native';

type Props = {
  children: React.ReactNode;
  delay?: number;
  style?: ViewStyle | ViewStyle[];
};

export const RampReveal = ({ children, delay = 0, style }: Props) => {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(10)).current;
  const revealAnimRef = useRef<Animated.CompositeAnimation | null>(null);

  useEffect(() => {
    revealAnimRef.current?.stop();
    revealAnimRef.current = Animated.parallel([
      Animated.timing(opacity, {
        toValue: 1,
        duration: 260,
        delay,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(translateY, {
        toValue: 0,
        duration: 320,
        delay,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
    ]);
    revealAnimRef.current.start();
    return () => {
      revealAnimRef.current?.stop();
    };
  }, [delay, opacity, translateY]);

  useEffect(() => {
    return () => {
      revealAnimRef.current?.stop();
      opacity.stopAnimation();
      translateY.stopAnimation();
    };
  }, [opacity, translateY]);

  return (
    <Animated.View style={[style, { opacity, transform: [{ translateY }] }]}>
      {children}
    </Animated.View>
  );
};
