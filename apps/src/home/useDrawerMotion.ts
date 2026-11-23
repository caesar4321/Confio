// How the menu moves: it slides with ☰, and it follows the finger. Drag
// right on the conversation to pull it open; drag left on the open menu (or
// its scrim) to push it away. Let go and it settles to whichever side the
// drag was heading for.
//
// The opening drag starts anywhere on the conversation, not at the screen's
// edge: on Android the first few points of the edge belong to the system's
// back gesture, and a menu that only answered there would be fighting it.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, Keyboard, PanResponder, type GestureResponderHandlers, type ViewProps } from 'react-native';
import { useReduceMotion } from './useReduceMotion';

export function drawerWidth(screenWidth: number) {
  return Math.min(Math.round(screenWidth * 0.86), 340);
}

// A drag counts once it is clearly sideways: a vertical scroll that wanders
// a little must stay a scroll.
const START_DX = 12;
const SIDEWAYS_RATIO = 1.5;

export function isSidewaysDrag(dx: number, dy: number, direction: 'right' | 'left') {
  const along = direction === 'right' ? dx : -dx;
  return along > START_DX && Math.abs(dx) > Math.abs(dy) * SIDEWAYS_RATIO;
}

/** Where a released drag settles: past a third of the way, or a flick. */
export function settlesOpen({ dx, vx, width, wasOpen }: { dx: number; vx: number; width: number; wasOpen: boolean }) {
  if (wasOpen) {
    return !(dx < -width * 0.3 || vx < -0.4);
  }
  return dx > width * 0.35 || vx > 0.4;
}

const clamp = (value: number) => Math.min(Math.max(value, 0), 1);

export function useDrawerMotion(isOpen: boolean, setIsOpen: (open: boolean) => void, width: number) {
  // 0 = away, 1 = open. The panel's slide and the scrim's fade both read it.
  const progress = useRef(new Animated.Value(0)).current;
  // Drawn at all: open, being dragged, or still sliding away.
  const [mounted, setMounted] = useState(false);
  const reduceMotion = useReduceMotion();
  const dragging = useRef(false);
  // A finger that went down on something that scrolls sideways inside the
  // menu (the wallet strip): that drag is the strip's, never the menu's.
  const sideways = useRef(false);
  const openRef = useRef(isOpen);
  openRef.current = isOpen;
  const widthRef = useRef(width);
  widthRef.current = width;

  const slide = useCallback((to: 0 | 1) => {
    Animated.timing(progress, {
      toValue: to,
      duration: reduceMotion.current ? 0 : to ? 220 : 180,
      easing: to ? Easing.out(Easing.cubic) : Easing.in(Easing.cubic),
      useNativeDriver: true,
    }).start(({ finished }) => {
      // Still closed and not picked up again: it can stop being drawn.
      if (finished && to === 0 && !openRef.current && !dragging.current) {
        setMounted(false);
      }
    });
  }, [progress, reduceMotion]);

  // ☰, a row, the back button: slide from wherever it is.
  useEffect(() => {
    if (isOpen) {
      // The menu covers the conversation: its keyboard goes with it.
      Keyboard.dismiss();
      setMounted(true);
    }
    slide(isOpen ? 1 : 0);
  }, [isOpen, slide]);

  const settle = useCallback((open: boolean) => {
    dragging.current = false;
    if (open !== openRef.current) {
      setIsOpen(open); // the effect above slides it the rest of the way
    } else {
      slide(open ? 1 : 0);
    }
  }, [setIsOpen, slide]);

  const openGesture = useMemo<GestureResponderHandlers>(() => PanResponder.create({
    onMoveShouldSetPanResponder: (_e, g) => !openRef.current && isSidewaysDrag(g.dx, g.dy, 'right'),
    onPanResponderGrant: () => {
      dragging.current = true;
      Keyboard.dismiss();
      progress.stopAnimation();
      progress.setValue(0);
      setMounted(true);
    },
    onPanResponderMove: (_e, g) => progress.setValue(clamp(g.dx / widthRef.current)),
    onPanResponderRelease: (_e, g) => settle(settlesOpen({ dx: g.dx, vx: g.vx, width: widthRef.current, wasOpen: false })),
    onPanResponderTerminate: () => settle(false),
  }).panHandlers, [progress, settle]);

  const closeGesture = useMemo<ViewProps>(() => ({
    // Every touch starts as the menu's; the strip claims its own below
    // (capture runs before the strip's own onTouchStart).
    onTouchStartCapture: () => { sideways.current = false; },
    ...PanResponder.create({
    onMoveShouldSetPanResponder: (_e, g) => openRef.current && !sideways.current && isSidewaysDrag(g.dx, g.dy, 'left'),
    onPanResponderGrant: () => {
      dragging.current = true;
      progress.stopAnimation();
    },
    onPanResponderMove: (_e, g) => progress.setValue(clamp(1 + g.dx / widthRef.current)),
    onPanResponderRelease: (_e, g) => settle(settlesOpen({ dx: g.dx, vx: g.vx, width: widthRef.current, wasOpen: true })),
    onPanResponderTerminate: () => settle(true),
  }).panHandlers,
  }), [progress, settle]);

  // For a sideways scroller inside the menu: spread on its wrapper.
  const sidewaysScroller = useMemo<ViewProps>(() => ({
    onTouchStart: () => { sideways.current = true; },
    onTouchEnd: () => { sideways.current = false; },
    onTouchCancel: () => { sideways.current = false; },
  }), []);

  return { progress, mounted, openGesture, closeGesture, sidewaysScroller };
}
