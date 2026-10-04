/**
 * DT1 / R18: the brand field defaults to the darker hero tokens, while
 * screens that pass their own colors (the CONFIO violet family) keep them.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { colors } from '../../../config/theme';
import { BrandFieldBackground } from '../BrandFieldBackground';

jest.mock('react-native-svg', () => {
  const R = require('react');
  const el = (name: string) => (props: any) => R.createElement(name, props, props.children);
  return {
    __esModule: true, default: el('Svg'), Defs: el('Defs'), Stop: el('Stop'),
    LinearGradient: el('LinearGradient'), Rect: el('Rect'), Circle: el('Circle'),
  };
});

const stops = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(n => (n.type as unknown) === 'Stop').map(n => n.props.stopColor);

describe('BrandFieldBackground', () => {
  it('defaults to the hero field tokens (#34D399 -> #10B981)', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<BrandFieldBackground id="t" />); });
    expect(stops(tree)).toEqual([colors.heroField, colors.heroFieldDark]);
    expect([colors.heroField, colors.heroFieldDark]).toEqual(['#34D399', '#10B981']);
  });

  it('explicit colors win (CONFIO violet screens unchanged)', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<BrandFieldBackground id="t" fromColor={colors.secondary} toColor={colors.secondaryDark} />);
    });
    expect(stops(tree)).toEqual([colors.secondary, colors.secondaryDark]);
  });

  it.each(['ConfioPresaleScreen', 'ConfioTokenInfoScreen', 'ConfioPresaleParticipateScreen', 'ConfioTokenomicsScreen'])(
    '%s still passes the violet field explicitly',
    (screen) => {
      const fs = jest.requireActual<any>('fs');
      const src: string = fs.readFileSync(`${__dirname}/../../../screens/${screen}.tsx`, 'utf8');
      expect(src).toMatch(/BrandFieldBackground[^>]*fromColor=\{colors\.secondary\}[^>]*toColor=\{colors\.secondaryDark\}/);
    },
  );
});
