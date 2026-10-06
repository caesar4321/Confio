// Tu mes entrance motion (founder 2026-10-05, extends design review 19A):
// the result tick-settles, the in/out bar grows, then the cards rise in one
// after another and their bars grow. Plays on MOUNT only — once per month
// view (a refresh never replays it) — and not at all with Reduce Motion.
// Transforms and opacity only: layout never moves (8A).
import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, type StyleProp, type ViewStyle } from 'react-native';

export const RISE_MS = 280;
export const RISE_STAGGER_MS = 70;
export const RISE_DISTANCE = 12;
export const GROW_MS = 450;

/** null until known; then whether the user asked for reduced motion. */
function useReduceMotion(): boolean | null {
  const [reduce, setReduce] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((r) => { if (alive) setReduce(r); })
      .catch(() => { if (alive) setReduce(true); });
    return () => { alive = false; };
  }, []);
  return reduce;
}

function useOnce(delay: number, duration: number) {
  const reduce = useReduceMotion();
  const value = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduce === null) return;
    if (reduce) {
      value.setValue(1);
      return;
    }
    const anim = Animated.timing(value, {
      toValue: 1, duration, delay, easing: Easing.out(Easing.cubic), useNativeDriver: true,
    });
    anim.start();
    return () => anim.stop();
  }, [reduce, value, delay, duration]);
  return value;
}

/** A card rising into place: fade + 12pt lift, staggered by `index`. */
export function Rise({ index = 0, children, style, testID }: {
  index?: number; children: React.ReactNode; style?: StyleProp<ViewStyle>; testID?: string;
}) {
  const v = useOnce(index * RISE_STAGGER_MS, RISE_MS);
  return (
    <Animated.View testID={testID} style={[style, {
      opacity: v,
      transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [RISE_DISTANCE, 0] }) }],
    }]}>
      {children}
    </Animated.View>
  );
}

/** A bar growing from its start edge (left) or from the bottom. */
export function Grow({ delay = 0, axis = 'x', children, style }: {
  delay?: number; axis?: 'x' | 'y'; children: React.ReactNode; style?: StyleProp<ViewStyle>;
}) {
  const v = useOnce(delay, GROW_MS);
  return (
    <Animated.View style={[style, axis === 'x'
      ? { transformOrigin: 'left', transform: [{ scaleX: v }] }
      : { transformOrigin: 'bottom', transform: [{ scaleY: v }] }]}>
      {children}
    </Animated.View>
  );
}
