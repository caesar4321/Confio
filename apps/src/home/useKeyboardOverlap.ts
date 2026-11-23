// Android: how much of a view the keyboard covers, so the view can step out
// of its way.
//
// On Android 15+ the app draws edge to edge and the system no longer shrinks
// the window for the keyboard ("adjustResize" then only reports it): the
// conversation's composer stayed under the keys. Older Androids still resize
// the window themselves. So the answer is measured, not assumed: where the
// view's bottom really is against where the keyboard's top is, checked again
// whenever either moves. Where the system already made room the overlap is
// zero and nothing is added twice. iOS uses KeyboardAvoidingView and gets 0.
import { useCallback, useEffect, useRef, useState } from 'react';
import { Keyboard, Platform, type View } from 'react-native';

/** The overlap for a view whose bottom is at `bottom` when the keyboard's top is at `keyboardTop` (null: hidden).
 * Never more than the keyboard itself is tall. */
export function overlapOf(bottom: number, keyboardTop: number | null, keyboardHeight = Infinity): number {
  if (keyboardTop === null || !Number.isFinite(bottom) || !Number.isFinite(keyboardTop)) {
    return 0;
  }
  return Math.max(0, Math.min(Math.round(bottom - keyboardTop), Math.round(keyboardHeight)));
}

export function useKeyboardOverlap() {
  const ref = useRef<View>(null);
  const keyboardTop = useRef<number | null>(null);
  const keyboardHeight = useRef(Infinity);
  const [overlap, setOverlap] = useState(0);

  const measure = useCallback(() => {
    const top = keyboardTop.current;
    const view = ref.current;
    if (top === null || !view) {
      setOverlap(0);
      return;
    }
    // The view's own box: padding added inside it does not move its bottom,
    // so the measure does not chase itself. Measured from the top of the
    // screen (pageY), as the keyboard's top is: measureInWindow leaves the
    // status bar out, and the composer stayed that much under the keys.
    view.measure((_x, _y, _width, height, _pageX, pageY) => (
      setOverlap(overlapOf(pageY + height, top, keyboardHeight.current))));
  }, []);

  useEffect(() => {
    if (Platform.OS !== 'android') {
      return undefined;
    }
    const show = Keyboard.addListener('keyboardDidShow', (e) => {
      keyboardTop.current = e.endCoordinates.screenY;
      keyboardHeight.current = e.endCoordinates.height > 0 ? e.endCoordinates.height : Infinity;
      measure();
    });
    const hide = Keyboard.addListener('keyboardDidHide', () => {
      keyboardTop.current = null;
      setOverlap(0);
    });
    return () => {
      show.remove();
      hide.remove();
    };
  }, [measure]);

  return {
    ref,
    /** The view was laid out again (a window the system resized, a rotation): measured again. */
    onLayout: Platform.OS === 'android' ? measure : undefined,
    overlap: Platform.OS === 'android' ? overlap : 0,
  };
}
