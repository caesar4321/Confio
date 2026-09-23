import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert, Pressable, Text } from 'react-native';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../ResponsiveImage', () => ({ ResponsiveImage: 'ResponsiveImage' }));
jest.mock('../ContentPoll', () => ({ ContentPoll: () => null }));
jest.mock('../EmptyState', () => ({ EmptyState: 'EmptyState' }));

import { DISCOVER_SECTIONS, DiscoverFeed, DiscoverItem } from '../DiscoverFeed';

const item = (overrides: Partial<DiscoverItem>): DiscoverItem => ({
  id: 1, type: 'news', tag: 'Producto', tagColor: '#1DB587', title: 'Hola', body: 'Cuerpo', time: '2h',
  ...overrides,
});

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(Text).map((node) => [node.props.children].flat().join(''));

const render = (props: Partial<React.ComponentProps<typeof DiscoverFeed>>) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(<DiscoverFeed items={[]} refreshing={false} {...props} />);
  });
  return tree;
};

describe('DiscoverFeed sections', () => {
  it('shows the source and the Oficial badge only for verified channels', () => {
    const tree = render({
      items: [
        item({ id: 1, sourceName: 'Confío News', isOfficial: true }),
        item({ id: 2, sourceName: 'Café Juan', isOfficial: false }),
      ],
    });
    const shown = texts(tree);
    expect(shown).toContain('Confío News');
    expect(shown).toContain('Café Juan');
    expect(shown.filter((t) => t === 'Oficial')).toHaveLength(1);
  });

  it('explains what Oficial means when the badge is tapped', () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    const tree = render({ items: [item({ sourceName: 'CIP Lima', isOfficial: true })] });
    const badge = tree.root.find((node) => node.type === Pressable && /Fuente oficial/.test(node.props.accessibilityLabel || ''));
    act(() => badge.props.onPress());
    expect(alert).toHaveBeenCalledWith('Fuente oficial', expect.stringMatching(/canal de Confío o una organización cuya identidad legal/));
    alert.mockRestore();
  });

  it('offers Para ti, Oficial and Comunidad and reports the pick', () => {
    const onSelectSection = jest.fn();
    const tree = render({ sections: DISCOVER_SECTIONS, activeSection: 'official', onSelectSection });
    const chips = tree.root.findAll((node) => node.type === Pressable && node.props.accessibilityRole === 'tab');
    expect(chips.map((chip) => chip.findByType(Text).props.children)).toEqual(['Para ti', 'Oficial', 'Comunidad']);
    expect(chips.map((chip) => chip.props.accessibilityState.selected)).toEqual([false, true, false]);
    act(() => chips[2].props.onPress());
    expect(onSelectSection).toHaveBeenCalledWith('community');
  });

  it('tells Comunidad readers it is coming, not that the app is empty', () => {
    const tree = render({ sections: DISCOVER_SECTIONS, activeSection: 'community' });
    expect(tree.root.findByType('EmptyState' as any).props.title).toBe('Comunidad llega pronto');
  });

  it('says the load failed instead of claiming there is nothing', () => {
    const onRetry = jest.fn();
    const tree = render({ sections: DISCOVER_SECTIONS, activeSection: 'official', loadFailed: true, onRetry });
    const empty = tree.root.findByType('EmptyState' as any);
    expect(empty.props.title).toBe('No pudimos cargar Descubrir');
    empty.props.onAction();
    expect(onRetry).toHaveBeenCalled();
  });

  it('shows no chips on a server without sections', () => {
    const tree = render({ items: [item({})] });
    expect(tree.root.findAll((node) => node.type === Pressable && node.props.accessibilityRole === 'tab')).toHaveLength(0);
  });
});
