import React from 'react';
import renderer, { act } from 'react-test-renderer';

import { CandleChart, axisPrice, offsetOf, priceRange, visibleWindow } from '../CandleChart';

jest.mock('react-native-svg', () => {
  const host = (name: string) => (props: any) => require('react').createElement(name, props, props.children);
  return { __esModule: true, default: host('Svg'), G: host('G'), Line: host('Line'), Rect: host('Rect'), Text: host('SvgText') };
});

const candle = (i: number, close = 100 + i) => ({ time: i * 60_000, open: 100 + i - 0.5, high: close + 1, low: 100 + i - 1, close, volume: i });
const series = (n: number) => Array.from({ length: n }, (_, i) => candle(i));

describe('CandleChart math', () => {
  it('windows the latest candles and clamps panning to the history', () => {
    const all = series(100);
    expect(visibleWindow(all, 30, 0).rows.map((r) => r.time / 60_000)).toEqual(Array.from({ length: 30 }, (_, i) => 70 + i));
    expect(visibleWindow(all, 30, 10).rows[29].time / 60_000).toBe(89);
    expect(visibleWindow(all, 30, 500)).toMatchObject({ offset: 70, maxOffset: 70 });
    expect(visibleWindow(all, 30, -4).offset).toBe(0);
    expect(visibleWindow(series(10), 30, 3).rows).toHaveLength(10);
  });

  it('keeps a panned view on the same candles as new ones arrive', () => {
    const all = series(100);
    const anchor = all[89].time; // looking back 10 candles
    expect(offsetOf(all, anchor)).toBe(10);
    const later = [...all, candle(100), candle(101)];
    expect(visibleWindow(later, 30, offsetOf(later, anchor)).rows[29].time).toBe(anchor);
    expect(offsetOf(all, null)).toBe(0);
  });

  it('widens the price range for a nearby guide but not a far one', () => {
    const rows = series(10);
    const base = priceRange(rows, []);
    expect(priceRange(rows, [103]).lo).toBeCloseTo(base.lo);
    expect(priceRange(rows, [97]).lo).toBeLessThan(base.lo);
    expect(priceRange(rows, [10]).lo).toBeCloseTo(base.lo); // a far liquidation stays off-chart
  });

  it('labels prices with the market precision', () => {
    expect(axisPrice(4063.1)).toMatch(/^4[.,]?063[.,]10$/);
    expect(axisPrice(0.012345)).toMatch(/0[.,]012345$/);
  });
});

describe('CandleChart', () => {
  const render = (candles: any[]) => {
    let tree: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<CandleChart candles={candles} daily={false} emptyText="Cargando velas…" />); });
    const sized = tree!.root.findAll((n) => typeof n.props.onLayout === 'function')[0];
    act(() => { sized.props.onLayout({ nativeEvent: { layout: { width: 358 } } }); });
    return tree!;
  };

  it('draws one candle and one volume bar per row, and the latest close on the axis', () => {
    const tree = render(series(40));
    // 50 candles fit at the default zoom; the 40 there are all drawn.
    expect(tree.root.findAll((n) => n.type === 'Rect' as any)).toHaveLength(40 * 2 + 1);
    // The OHLC row reads the latest candle (close 139) until a finger picks another.
    const ohlc = tree.root.findAll((n) => n.props.testID === 'perps-candle-ohlc')[0];
    const texts = ohlc.findAll((n) => typeof n.props.children === 'string').map((n) => n.props.children);
    expect(texts).toEqual(expect.arrayContaining([axisPrice(138.5), axisPrice(140), axisPrice(138), axisPrice(139)]));
  });

  const rects = (tree: renderer.ReactTestRenderer) => tree.root.findAll((n) => n.type === 'Rect' as any).length;
  const button = (tree: renderer.ReactTestRenderer, id: string) =>
    tree.root.findAll((n) => n.props.testID === id && n.props.onPress)[0];
  const plot = (tree: renderer.ReactTestRenderer) => tree.root.findAll((n) => typeof n.props.onTouchStart === 'function')[0];
  // A touch at (x, y) inside the plot, which sits at the page's top-left here.
  const at = (x: number, y: number, touches = 1) => ({ nativeEvent: { pageX: x, pageY: y, locationX: x, locationY: y,
    touches: Array.from({ length: touches }, () => ({ pageX: x, pageY: y })) } });

  it('zooms between the bounds with the buttons', () => {
    const tree = render(series(200));
    expect(rects(tree)).toBe(50 * 2 + 1);
    act(() => { button(tree, 'perps-candle-zoom-in').props.onPress(); });
    expect(rects(tree)).toBe(33 * 2 + 1);
    act(() => { button(tree, 'perps-candle-zoom-in').props.onPress(); button(tree, 'perps-candle-zoom-in').props.onPress(); });
    expect(rects(tree)).toBe(20 * 2 + 1);
    expect(button(tree, 'perps-candle-zoom-in').props.disabled).toBe(true);
    for (let i = 0; i < 6; i += 1) act(() => { button(tree, 'perps-candle-zoom-out').props.onPress(); });
    expect(rects(tree)).toBe(150 * 2 + 1);
    expect(button(tree, 'perps-candle-zoom-out').props.disabled).toBe(true);
  });

  it('holds for a crosshair that stays after lifting and goes away with a tap', () => {
    jest.useFakeTimers();
    try {
      const tree = render(series(40));
      const crosshair = () => tree.root.findAll((n) => n.props.testID === 'perps-candle-crosshair').length > 0;
      act(() => { plot(tree).props.onTouchStart(at(200, 100)); });
      act(() => { jest.advanceTimersByTime(300); });
      expect(crosshair()).toBe(true);
      // Its price tag: the price at the finger's height, in the market's precision.
      act(() => { plot(tree).props.onTouchEnd({ nativeEvent: { pageX: 200, pageY: 100, touches: [] } }); });
      expect(crosshair()).toBe(true);
      act(() => { plot(tree).props.onTouchStart(at(50, 50)); });
      act(() => { plot(tree).props.onTouchEnd({ nativeEvent: { pageX: 50, pageY: 50, touches: [] } }); });
      expect(crosshair()).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  it('a quick tap never opens a crosshair, and a double tap goes back to the latest', () => {
    jest.useFakeTimers();
    try {
      const tree = render(series(200));
      act(() => { button(tree, 'perps-candle-zoom-in').props.onPress(); });
      expect(rects(tree)).toBe(33 * 2 + 1);
      const tap = () => {
        act(() => { plot(tree).props.onTouchStart(at(100, 100)); });
        act(() => { jest.advanceTimersByTime(80); });
        act(() => { plot(tree).props.onTouchEnd({ nativeEvent: { pageX: 100, pageY: 100, touches: [] } }); });
      };
      tap();
      expect(tree.root.findAll((n) => n.props.testID === 'perps-candle-crosshair')).toHaveLength(0);
      tap();
      expect(rects(tree)).toBe(50 * 2 + 1);
    } finally {
      jest.useRealTimers();
    }
  });

  it('says it is loading until there are candles', () => {
    const tree = render([]);
    expect(tree.root.findAll((n) => n.props.children === 'Cargando velas…').length).toBeGreaterThan(0);
  });
});
