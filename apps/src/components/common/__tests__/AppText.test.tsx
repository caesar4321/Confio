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
    expect(resolveFontStyle({ fontWeight: '700', fontSize: 16 }).style).toEqual({
      fontFamily: fontFamily.bold,
      fontSize: 16,
    });
  });

  it('keeps an explicit fontFamily (e.g. monospace addresses) untouched', () => {
    const style = { fontFamily: 'monospace', fontWeight: '600' as const };
    expect(resolveFontStyle(style).style).toEqual(style);
  });

  it('flattens style arrays and later entries win', () => {
    expect(resolveFontStyle([{ fontWeight: '400', color: 'red' }, { fontWeight: '600' }]).style).toEqual({
      color: 'red',
      fontFamily: fontFamily.semibold,
    });
  });

  it('italic picks the italic file for each weight and drops fontStyle', () => {
    expect(resolveFontStyle({ fontStyle: 'italic' }).style).toEqual({ fontFamily: fontFamily.italic });
    expect(resolveFontStyle({ fontStyle: 'italic', fontWeight: '600' }).style).toEqual({
      fontFamily: fontFamily.semiboldItalic,
    });
    expect(resolveFontStyle({ fontStyle: 'italic', fontWeight: '800' }).style).toEqual({
      fontFamily: fontFamily.boldItalic,
    });
    expect(resolveFontStyle({ fontStyle: 'normal', fontWeight: '500' }).style).toEqual({
      fontFamily: fontFamily.medium,
    });
  });

  it('nested text inherits the parent weight/italic unless it overrides them', () => {
    const parent = resolveFontStyle({ fontWeight: '700' }).typography;
    expect(resolveFontStyle(undefined, parent).style).toEqual({ fontFamily: fontFamily.bold });
    expect(resolveFontStyle({ fontStyle: 'italic' }, parent).style).toEqual({ fontFamily: fontFamily.boldItalic });
    expect(resolveFontStyle({ fontWeight: '400' }, parent).style).toEqual({ fontFamily: fontFamily.regular });
  });

  it('an explicit-family child inside a bold italic parent keeps the inherited weight and slant', () => {
    const parent = resolveFontStyle({ fontWeight: '700', fontStyle: 'italic' }).typography;
    expect(resolveFontStyle({ fontFamily: 'System' }, parent).style).toEqual({
      fontFamily: 'System',
      fontWeight: '700',
      fontStyle: 'italic',
    });
    // its own overrides still win
    expect(resolveFontStyle({ fontFamily: 'System', fontWeight: '400', fontStyle: 'normal' }, parent).style).toEqual({
      fontFamily: 'System',
      fontWeight: '400',
      fontStyle: 'normal',
    });
  });

  it('nested text inside an explicit-family parent keeps inheriting that family', () => {
    const parent = resolveFontStyle({ fontFamily: 'monospace' }).typography;
    expect(resolveFontStyle({ fontWeight: '700' }, parent).style).toEqual({ fontWeight: '700' });
  });

  it('weight and slant survive any depth of explicit-family nesting', () => {
    const root = resolveFontStyle({ fontWeight: '700', fontStyle: 'italic' }).typography;
    const child = resolveFontStyle({ fontFamily: 'monospace' }, root);
    expect(child.style).toEqual({ fontFamily: 'monospace', fontWeight: '700', fontStyle: 'italic' });
    const grandchild = resolveFontStyle({ fontFamily: 'serif' }, child.typography);
    expect(grandchild.style).toEqual({ fontFamily: 'serif', fontWeight: '700', fontStyle: 'italic' });
    const plainInMono = resolveFontStyle(undefined, child.typography);
    expect(plainInMono.style).toEqual({ fontWeight: '700', fontStyle: 'italic' });
  });

  it('restated weights are Android-safe: named aliases become numbers, numbers stay', () => {
    const heavy = resolveFontStyle({ fontWeight: 'heavy' as any }).typography;
    expect(resolveFontStyle({ fontFamily: 'monospace' }, heavy).style).toEqual({
      fontFamily: 'monospace',
      fontWeight: '700',
    });
    const w800 = resolveFontStyle({ fontWeight: '800' }).typography;
    expect(resolveFontStyle({ fontFamily: 'monospace' }, w800).style).toEqual({
      fontFamily: 'monospace',
      fontWeight: '800',
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

  it('a plain nested Text inside a bold Text stays bold', () => {
    let view!: ReactTestRenderer;
    act(() => {
      view = create(
        <Text style={{ fontWeight: '700' }}>
          Título <Text>destacado</Text>
        </Text>,
      );
    });
    const natives = view.root.findAllByType(RNText);
    expect(natives).toHaveLength(2);
    expect(natives[1].props.style).toEqual({ fontFamily: fontFamily.bold });
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
