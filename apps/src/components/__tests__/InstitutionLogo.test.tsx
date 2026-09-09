import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Image, Text } from 'react-native';

jest.mock('../../config/theme', () => ({
  colors: { primaryDark: '#10B981', white: '#FFFFFF' },
}));

import { InstitutionLogo, institutionMonogram } from '../InstitutionLogo';

describe('institution monogram', () => {
  it('skips Spanish connectives so the colegio reads as members name it', () => {
    expect(institutionMonogram('Colegio de Ingenieros del Perú')).toBe('CIP');
  });

  it('caps at three letters rather than spelling the whole name', () => {
    expect(institutionMonogram('Colegio Nacional de Abogados y Notarios')).toBe('CNA');
  });

  it('handles accents and a single word', () => {
    expect(institutionMonogram('Ávila')).toBe('Á');
  });

  it('degrades to a dash instead of crashing on an empty name', () => {
    expect(institutionMonogram('')).toBe('—');
    expect(institutionMonogram('   ')).toBe('—');
  });
});

describe('InstitutionLogo', () => {
  it('renders the monogram when no logo is configured', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => {
      tree = renderer.create(<InstitutionLogo name="Colegio de Ingenieros del Perú" />);
    });
    expect(tree.root.findAllByType(Image)).toHaveLength(0);
    expect(tree.root.findByType(Text).props.children).toBe('CIP');
    await act(async () => { tree.unmount(); });
  });

  it('prefers a configured logo over the monogram', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => {
      tree = renderer.create(
        <InstitutionLogo name="Colegio de Ingenieros del Perú" logoUrl="https://x.test/cip.png" />,
      );
    });
    expect(tree.root.findByType(Image).props.source).toEqual({ uri: 'https://x.test/cip.png' });
    expect(tree.root.findAllByType(Text)).toHaveLength(0);
    await act(async () => { tree.unmount(); });
  });

  it('falls back to the monogram when the image fails, never a broken glyph', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => {
      tree = renderer.create(
        <InstitutionLogo name="Colegio de Ingenieros del Perú" logoUrl="https://x.test/gone.png" />,
      );
    });
    await act(async () => { tree.root.findByType(Image).props.onError(); });
    expect(tree.root.findAllByType(Image)).toHaveLength(0);
    expect(tree.root.findByType(Text).props.children).toBe('CIP');
    await act(async () => { tree.unmount(); });
  });
});
