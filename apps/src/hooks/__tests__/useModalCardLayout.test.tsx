/**
 * Modal cards must fit short windows (Android landscape, split-screen, large
 * text): no minimum height beyond the safe window, and a footer that would
 * squeeze the body must scroll with it instead of clipping.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import type { LayoutChangeEvent } from 'react-native';

jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 40, bottom: 10, left: 0, right: 0 }),
}));
jest.mock('react-native/Libraries/Utilities/useWindowDimensions', () => ({
  __esModule: true,
  default: () => ({ width: 640, height: 300, scale: 2, fontScale: 2 }),
}));

import { useModalCardLayout } from '../useModalCardLayout';

const mount = () => {
  let api!: ReturnType<typeof useModalCardLayout>;
  const Probe = () => {
    api = useModalCardLayout();
    return null;
  };
  act(() => {
    renderer.create(<Probe />);
  });
  return () => api;
};

const footerLayout = (height: number) =>
  ({ nativeEvent: { layout: { x: 0, y: 0, width: 300, height } } }) as LayoutChangeEvent;

describe('useModalCardLayout', () => {
  it('caps the card to the safe window with no minimum height', () => {
    const layout = mount();
    // 300pt window - 40pt top inset - 16pt minimum bottom padding.
    expect(layout()).toMatchObject({ paddingTop: 40, paddingBottom: 16, maxHeight: 244, inlineFooter: false });
  });

  it('keeps the footer pinned while the body keeps enough room', () => {
    const layout = mount();
    act(() => layout().onFooterLayout(footerLayout(84)));
    expect(layout().inlineFooter).toBe(false);
  });

  it('moves the footer into the scroll when the body would be squeezed', () => {
    const layout = mount();
    act(() => layout().onFooterLayout(footerLayout(85)));
    expect(layout().inlineFooter).toBe(true);
  });
});
