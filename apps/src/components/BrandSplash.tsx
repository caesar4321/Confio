import React, { useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo,
  Animated,
  Dimensions,
  Easing,
  Image,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { colors } from '../config/theme';

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

// Coin ring drawn around the logo: r=70 in a 160-viewport.
const RING_R = 70;
const RING_DASH = 2 * Math.PI * RING_R;

/**
 * Brand motion splash (~1.8s) — stage two after the static native splash
 * (LaunchScreen.storyboard / SplashTheme windowBackground).
 *
 * Frame 1 is the same splash artwork the native side shows, so the handoff
 * is continuous. The artwork then dissolves while the coin mark takes over:
 * an emerald ring draws itself around the logo (the same coin-ring motif as
 * the Auth brand field), the wordmark rises, and the overlay lifts away.
 *
 * Plays on cold start only: the JS root mounts once per cold start.
 */
export function BrandSplash({ onDone }: { onDone: () => void }) {
  // svg props can't use the native driver; plain views below can
  const art = useRef(new Animated.Value(1)).current;   // artwork dissolve
  const mark = useRef(new Animated.Value(0)).current;  // JS logo crossfade
  const ring = useRef(new Animated.Value(0)).current;  // coin ring draw
  const words = useRef(new Animated.Value(0)).current; // wordmark + eyebrow
  const out = useRef(new Animated.Value(1)).current;   // final lift
  const [running, setRunning] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const finish = () => {
      if (cancelled) {
        return;
      }
      Animated.timing(out, {
        toValue: 0,
        duration: 320,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }).start(() => {
        if (!cancelled) {
          setRunning(false);
          onDone();
        }
      });
    };

    AccessibilityInfo.isReduceMotionEnabled().then((reduced) => {
      if (cancelled) {
        return;
      }
      if (reduced) {
        // No choreography — show the finished mark briefly, then hand off.
        art.setValue(0);
        [mark, ring, words].forEach((v) => v.setValue(1));
        timer = setTimeout(finish, 700);
        return;
      }

      Animated.parallel([
        // Artwork dissolves while the JS logo crossfades in at the same spot.
        Animated.timing(art, { toValue: 0, duration: 450, delay: 250, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
        Animated.timing(mark, { toValue: 1, duration: 450, delay: 250, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
        // Coin ring draws itself around the mark.
        Animated.timing(ring, { toValue: 1, duration: 750, delay: 450, easing: Easing.out(Easing.cubic), useNativeDriver: false }),
        // Wordmark settles under the mark, echoing the Auth brand field.
        Animated.timing(words, { toValue: 1, duration: 500, delay: 900, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
      ]).start(() => {
        if (!cancelled) {
          timer = setTimeout(finish, 300);
        }
      });
    });

    return () => {
      cancelled = true;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, [art, mark, ring, words, out, onDone]);

  if (!running) {
    return null;
  }

  return (
    <Animated.View style={[styles.root, { opacity: out }]} pointerEvents="auto">
      {/* Same artwork as the native splash → continuous handoff */}
      <Animated.Image
        source={require('../assets/png/splashscreen.png')}
        style={[styles.art, { opacity: art }]}
        resizeMode="cover"
      />

      {/* The coin icon sits at (50%w, 45%h) in the cover-scaled artwork;
          the JS mark crossfades in at the same spot, so nothing jumps. */}
      <View style={styles.markAnchor} pointerEvents="none">
        <View style={styles.markWrap}>
          <Svg width={160} height={160} viewBox="0 0 160 160">
            <AnimatedCircle
              cx={80}
              cy={80}
              r={RING_R}
              fill="none"
              stroke={colors.primary}
              strokeWidth={5}
              strokeLinecap="round"
              strokeDasharray={`${RING_DASH}`}
              strokeDashoffset={ring.interpolate({ inputRange: [0, 1], outputRange: [RING_DASH, 0] })}
              // start the draw at 12 o'clock
              transform="rotate(-90 80 80)"
            />
          </Svg>
          <Animated.View style={[StyleSheet.absoluteFill, styles.markCenter, { opacity: mark }]}>
            <Image
              source={require('../assets/png/CONFIO.png')}
              style={styles.logo}
            />
          </Animated.View>
        </View>

        <Animated.View
          style={[
            styles.words,
            { opacity: words, transform: [{ translateY: words.interpolate({ inputRange: [0, 1], outputRange: [10, 0] }) }] },
          ]}
        >
          <Text style={styles.wordmark}>Confío</Text>
          <Text style={styles.eyebrow}>DÓLARES DIGITALES</Text>
        </Animated.View>
      </View>
    </Animated.View>
  );
}

const { height: SCREEN_H } = Dimensions.get('window');

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.background,
    zIndex: 100,
    elevation: 100,
  },
  art: {
    ...StyleSheet.absoluteFillObject,
    width: '100%',
    height: '100%',
  },
  // Anchor the mark where the artwork places the coin icon (~45% height).
  markAnchor: {
    position: 'absolute',
    top: SCREEN_H * 0.45,
    left: 0,
    right: 0,
    alignItems: 'center',
    transform: [{ translateY: -80 }],
  },
  markWrap: {
    width: 160,
    height: 160,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markCenter: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  logo: {
    width: 96,
    height: 96,
    resizeMode: 'contain',
  },
  words: {
    alignItems: 'center',
    marginTop: 20,
  },
  wordmark: {
    fontSize: 30,
    fontWeight: '800',
    color: colors.dark,
    letterSpacing: -0.5,
  },
  eyebrow: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 2.5,
    color: colors.primaryDark,
    marginTop: 6,
  },
});
