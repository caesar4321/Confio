import React from 'react';
import { Text, View } from 'react-native';
import renderer, { act, ReactTestRenderer } from 'react-test-renderer';

import {
  ContactSyncProgress,
  formatContactCount,
  getContactSyncDetail,
  getContactSyncRatio,
} from '../ContactSyncProgress';
import type { ContactSyncProgress as ContactSyncProgressState } from '../../../services/contactService';

const render = (progress: ContactSyncProgressState | null, fallbackLabel = 'Cargando contactos...') => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = renderer.create(
      <ContactSyncProgress progress={progress} fallbackLabel={fallbackLabel} />,
    );
  });
  return tree;
};

const texts = (tree: ReactTestRenderer) =>
  tree.root.findAllByType(Text).map(node => node.props.children).filter(Boolean);

const fillWidth = (tree: ReactTestRenderer) => {
  const fills = tree.root.findAll(
    node => node.type === View && node.props.testID === 'contact-sync-progress-fill',
  );
  if (fills.length === 0) return null;
  const style = Array.isArray(fills[0].props.style) ? fills[0].props.style : [fills[0].props.style];
  return style.reduce((width: string | null, entry: any) => entry?.width ?? width, null);
};

describe('ContactSyncProgress', () => {
  it('shows how many contacts are done so a large address book reads as moving', () => {
    const tree = render({ phase: 'normalizing', processed: 1240, total: 3500 });

    expect(texts(tree)).toEqual(['Revisando tus contactos', '1.240 de 3.500 contactos']);
    expect(fillWidth(tree)).toBe('35%');
  });

  it('counts phone numbers, not contacts, while matching against Confío', () => {
    const tree = render({ phase: 'matching', processed: 50, total: 200 });

    expect(texts(tree)).toEqual(['Buscando a tus amigos en Confío', '50 de 200 números']);
    expect(fillWidth(tree)).toBe('25%');
  });

  it('stays indeterminate for steps with no measurable total', () => {
    const tree = render({ phase: 'reading', processed: 0, total: 0 });

    expect(texts(tree)).toEqual(['Leyendo tu agenda...']);
    expect(fillWidth(tree)).toBeNull();
  });

  it('falls back to the caller label before the first report', () => {
    const tree = render(null, 'Sincronizando contactos...');

    expect(texts(tree)).toEqual(['Sincronizando contactos...']);
    expect(fillWidth(tree)).toBeNull();
  });

  it('announces progress to screen readers', () => {
    const tree = render({ phase: 'normalizing', processed: 700, total: 1000 });
    const bar = tree.root.findAll(node => node.props?.accessibilityRole === 'progressbar')[0];

    expect(bar.props.accessibilityLabel).toBe('Revisando tus contactos. 700 de 1.000 contactos');
    expect(bar.props.accessibilityValue).toEqual({ min: 0, max: 100, now: 70 });
  });

  it('clamps a report that overshoots its total', () => {
    const progress: ContactSyncProgressState = { phase: 'matching', processed: 250, total: 200 };

    expect(getContactSyncDetail(progress)).toBe('200 de 200 números');
    expect(getContactSyncRatio(progress)).toBe(1);
  });

  it('groups thousands the way LATAM Spanish reads them', () => {
    expect(formatContactCount(999)).toBe('999');
    expect(formatContactCount(1000)).toBe('1.000');
    expect(formatContactCount(1234567)).toBe('1.234.567');
  });
});
