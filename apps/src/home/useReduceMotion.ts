// "Reduce motion", kept current in a ref: the menu reads it at the moment it
// opens or closes, so both directions honour it without waiting on a promise.
import { useEffect, useRef } from 'react';
import { AccessibilityInfo } from 'react-native';

export function useReduceMotion() {
  const reduce = useRef(false);
  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (mounted) reduce.current = enabled;
      })
      .catch(() => undefined);
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', (enabled) => {
      reduce.current = enabled;
    });
    return () => {
      mounted = false;
      sub.remove();
    };
  }, []);
  return reduce;
}
