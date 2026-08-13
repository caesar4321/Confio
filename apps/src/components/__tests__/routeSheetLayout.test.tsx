import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { ScrollView, StyleSheet } from 'react-native';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../hooks/useAppSafeArea', () => ({
  useAppSafeArea: () => ({ top: 44, bottom: 34, headerHeight: 88 }),
}));

// A small phone — the device the clipping was reported on.
const WINDOW_HEIGHT = 640;
jest.mock('react-native/Libraries/Utilities/useWindowDimensions', () => ({
  __esModule: true,
  default: () => ({ width: 360, height: 640, scale: 2, fontScale: 1 }),
}));

import { RouteSheet, RouteOption } from '../RouteSheet';

const makeOptions = (count: number): RouteOption[] =>
  Array.from({ length: count }, (_, index) => ({
    id: `rail_${index}`,
    icon: 'clock',
    // Deliberately identical titles: six real rails are called "Cuenta
    // bancaria", so the component must key off `id`, not the title.
    title: 'Cuenta bancaria',
    subtitle: 'Transferencia local',
    note: 'Próximamente · Toca para recibir un aviso',
    onPress: jest.fn(),
  }));

const render = (options: RouteOption[]) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(
      <RouteSheet visible title="¿A dónde quieres enviar?" options={options} onClose={jest.fn()} />,
    );
  });
  return tree;
};

describe('RouteSheet layout', () => {
  // The rail list grows every time a corridor opens, so the sheet has to cope
  // with a list taller than the screen.
  //
  // The bug this pins: with only a percentage maxHeight on the SHEET, the
  // ScrollView still measured at full content height, so it had nothing to
  // scroll within — rows past the cap were painted outside the sheet and lost.
  // A viewport smaller than the content is the only state a ScrollView
  // actually scrolls in, so the cap has to land on the list in real pixels.
  it('bounds the list in pixels so it can actually scroll', () => {
    const scroll = render(makeOptions(12)).root.findByType(ScrollView);
    const style = StyleSheet.flatten(scroll.props.style);
    expect(typeof style.maxHeight).toBe('number');
    expect(style.maxHeight).toBeLessThan(WINDOW_HEIGHT);
    expect(style.maxHeight).toBeGreaterThan(0);
  });

  it('leaves backdrop visible above the sheet so it still reads as dismissable', () => {
    const scroll = render(makeOptions(12)).root.findByType(ScrollView);
    const style = StyleSheet.flatten(scroll.props.style);
    // Handle + title + inset live above/below the list inside the same sheet.
    expect(style.maxHeight).toBeLessThanOrEqual(Math.round(WINDOW_HEIGHT * 0.7));
  });

  it('does not wrap the scrolling list in a touchable that competes for gestures', () => {
    const tree = render(makeOptions(12));
    const scroll = tree.root.findByType(ScrollView);
    const touchableAncestors: string[] = [];
    let node: any = scroll.parent;
    while (node) {
      const name = typeof node.type === 'function' ? node.type.displayName || node.type.name : '';
      if (name === 'TouchableOpacity') touchableAncestors.push(name);
      node = node.parent;
    }
    // Only the backdrop may be a touchable; the sheet itself must not be.
    expect(touchableAncestors.length).toBeLessThanOrEqual(1);
  });

  it('keeps the whole list mounted, including the last row', () => {
    const options = makeOptions(12);
    const tree = render(options);
    const rows = tree.root.findAll(
      node => typeof node.type !== 'string' && node.props?.accessible === true,
      { deep: true },
    );
    // Every option renders; nothing is dropped before it reaches layout.
    expect(rows.length).toBeGreaterThanOrEqual(options.length);
  });

  it('reserves room below the last row for the home indicator', () => {
    const scroll = render(makeOptions(12)).root.findByType(ScrollView);
    const content = StyleSheet.flatten(scroll.props.contentContainerStyle);
    // Mocked bottom inset is 34; the floor of 24 covers devices reporting 0.
    expect(content.paddingBottom).toBe(34);
  });

  it('renders duplicate-titled rows without colliding keys', () => {
    // Would warn "Encountered two children with the same key" if the component
    // keyed on title — the state of one row would then leak into another.
    const warn = jest.spyOn(console, 'error').mockImplementation(() => {});
    render(makeOptions(6));
    expect(warn).not.toHaveBeenCalledWith(
      expect.stringContaining('same key'),
      expect.anything(),
      expect.anything(),
    );
    warn.mockRestore();
  });
});
