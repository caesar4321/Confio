// A pencil that circles the real button, like a teacher marking a page. It
// never takes a touch: the person taps the button underneath.
import React, { useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, View, useWindowDimensions } from 'react-native';
import Svg, { Path } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';
import { colors } from '../config/theme';
import { measureGuideAnchor, useGuidePointer, type GuideRect } from './guidePointer';

const AnimatedPath = Animated.createAnimatedComponent(Path);
const PADDING = 10;
const DRAW_MS = 900;
const MEASURE_EVERY_MS = 400;
const PENCIL_SIZE = 28;
const INK = colors.secondaryDark;

// One hand-drawn loop that overshoots its start. `x` and `y` are the box corner.
function loopPath(width: number, height: number) {
  const w = width;
  const h = height;
  return `M ${w * 0.12} ${h * 0.14} C ${w * 0.4} ${-h * 0.02}, ${w * 0.92} ${-h * 0.04}, ${w * 0.98} ${h * 0.3} `
    + `C ${w * 1.03} ${h * 0.62}, ${w * 0.86} ${h * 0.98}, ${w * 0.5} ${h * 0.98} `
    + `C ${w * 0.16} ${h * 1.02}, ${-w * 0.02} ${h * 0.74}, ${w * 0.01} ${h * 0.44} `
    + `C ${w * 0.02} ${h * 0.2}, ${w * 0.16} ${h * 0.08}, ${w * 0.34} ${h * 0.05}`;
}

export function loopLength(width: number, height: number) {
  const a = width / 2;
  const b = height / 2;
  return 2 * Math.PI * Math.sqrt((a * a + b * b) / 2) * 1.2;
}

export default function GuidePencil() {
  const pointer = useGuidePointer();
  const { width: screenWidth } = useWindowDimensions();
  const [rect, setRect] = useState<GuideRect | null>(null);
  const draw = useRef(new Animated.Value(0)).current;
  const bob = useRef(new Animated.Value(0)).current;
  const id = pointer?.id;

  useEffect(() => {
    if (!id) {
      setRect(null);
      return undefined;
    }
    let alive = true;
    const measure = () => measureGuideAnchor(id).then((next) => {
      if (alive) {
        setRect((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
      }
    });
    measure();
    const timer = setInterval(measure, MEASURE_EVERY_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id]);

  const visible = !!rect;
  useEffect(() => {
    if (!visible) {
      return undefined;
    }
    draw.setValue(0);
    Animated.timing(draw, { toValue: 1, duration: DRAW_MS, easing: Easing.inOut(Easing.quad), useNativeDriver: false }).start();
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(bob, { toValue: 1, duration: 500, useNativeDriver: true }),
      Animated.timing(bob, { toValue: 0, duration: 500, useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [visible, id, draw, bob]);

  if (!rect) {
    return null;
  }
  const box = {
    left: rect.x - PADDING,
    top: rect.y - PADDING,
    width: rect.width + PADDING * 2,
    height: rect.height + PADDING * 2,
  };
  const length = loopLength(box.width, box.height);
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Svg style={[styles.loop, box]} width={box.width} height={box.height} viewBox={`0 0 ${box.width} ${box.height}`}>
        <AnimatedPath
          d={loopPath(box.width, box.height)}
          fill="none"
          stroke={INK}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeDasharray={length}
          strokeDashoffset={draw.interpolate({ inputRange: [0, 1], outputRange: [length, 0] })}
        />
      </Svg>
      <Animated.View
        style={[styles.pencil, {
          left: Math.min(box.left + box.width - PENCIL_SIZE, screenWidth - PENCIL_SIZE - 4),
          top: box.top + box.height - PENCIL_SIZE / 2,
          transform: [{ translateY: bob.interpolate({ inputRange: [0, 1], outputRange: [0, 5] }) }],
        }]}
      >
        <Icon name="edit-2" size={PENCIL_SIZE - 4} color={INK} />
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  loop: { position: 'absolute' },
  pencil: { position: 'absolute', width: PENCIL_SIZE, height: PENCIL_SIZE, alignItems: 'center', justifyContent: 'center' },
});
