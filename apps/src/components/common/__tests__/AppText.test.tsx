import React, { createRef } from 'react';
import { Text as RNText, TextInput as RNTextInput } from 'react-native';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { Text, TextInput, familyForWeight, resolveFontStyle } from '../AppText';
import { fontFamily } from '../../../config/theme';

describe('AppText weight mapping', () => {
  it.each([
    [undefined, fontFamily.regular],
    ['normal', fontFamily.regular],
    ['400', fontFamily.regular],
    [400, fontFamily.regular],
    ['300', fontFamily.regular],
    ['500', fontFamily.medium],
    ['600', fontFamily.semibold],
    ['bold', fontFamily.bold],
    ['700', fontFamily.bold],
    // Instrument Sans stops at 700: heavier weights render Bold, never synthesized.
    ['800', fontFamily.bold],
    ['900', fontFamily.bold],
  ])('weight %p -> %s', (weight, family) => {
    expect(familyForWeight(weight as any)).toBe(family);
  });

  it('drops fontWeight so neither platform fakes a bold on top of the family', () => {
    expect(resolveFontStyle({ fontWeight: '700', fontSize: 16 })).toEqual({
      fontFamily: fontFamily.bold,
      fontSize: 16,
    });
  });

  it('keeps an explicit fontFamily (e.g. monospace addresses) untouched', () => {
    const style = { fontFamily: 'monospace', fontWeight: '600' as const };
    expect(resolveFontStyle(style)).toEqual(style);
  });

  it('flattens style arrays and later entries win', () => {
    expect(resolveFontStyle([{ fontWeight: '400', color: 'red' }, { fontWeight: '600' }])).toEqual({
      color: 'red',
      fontFamily: fontFamily.semibold,
    });
  });
});

describe('AppText components', () => {
  it('Text renders react-native Text with the resolved family and passes props through', () => {
    let view!: ReactTestRenderer;
    act(() => {
      view = create(
        <Text style={{ fontWeight: '700' }} numberOfLines={1}>
          Hola
        </Text>,
      );
    });
    const native = view.root.findByType(RNText);
    expect(native.props.children).toBe('Hola');
    expect(native.props.numberOfLines).toBe(1);
    expect(native.props.style).toEqual({ fontFamily: fontFamily.bold });
    act(() => view.unmount());
  });

  it('TextInput forwards refs to the react-native TextInput instance', () => {
    const ref = createRef<TextInput>();
    let view!: ReactTestRenderer;
    act(() => {
      view = create(<TextInput ref={ref} placeholder="Monto" />);
    });
    const native = view.root.findByType(RNTextInput);
    expect(native.props.placeholder).toBe('Monto');
    expect(native.props.style).toEqual({ fontFamily: fontFamily.regular });
    expect(ref.current).not.toBeNull();
    act(() => view.unmount());
  });
});
