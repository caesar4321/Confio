import { useState } from 'react';
import { LayoutChangeEvent, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

// With less room than this left for a card's scrolling body, its footer joins
// the scrolling content instead of squeezing (and clipping) everything else.
const MIN_BODY_HEIGHT = 160;

/**
 * Sizing for centered modal cards with a scrolling body and a pinned footer.
 * The card never exceeds the safe window (short Android landscape and
 * split-screen windows included), and when the pinned footer would leave too
 * little room for the body, the footer scrolls with the content instead.
 */
export function useModalCardLayout() {
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  const [footerHeight, setFooterHeight] = useState(0);
  const paddingTop = Math.max(insets.top, 16);
  const paddingBottom = Math.max(insets.bottom, 16);
  const maxHeight = Math.max(0, height - paddingTop - paddingBottom);
  return {
    paddingTop,
    paddingBottom,
    maxHeight,
    inlineFooter: footerHeight > 0 && maxHeight - footerHeight < MIN_BODY_HEIGHT,
    onFooterLayout: (event: LayoutChangeEvent) => setFooterHeight(event.nativeEvent.layout.height),
  };
}
