import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Image, Pressable, Text } from 'react-native';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import { PostByline, channelInitial } from '../PostByline';
import { ReactionBar } from '../ReactionBar';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(Text).map((node) => [node.props.children].flat().join(''));

const mount = (element: React.ReactElement) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(element);
  });
  return tree;
};

describe('channelInitial', () => {
  it('skips leading emoji and symbols', () => {
    expect(channelInitial('🇰🇷 Julian Moon 🌙')).toBe('J');
    expect(channelInitial('Ñandú Café')).toBe('Ñ');
    expect(channelInitial('🎉')).toBe('·');
  });
});

describe('PostByline', () => {
  it('prefers the uploaded image, then the emoji, then the initial', () => {
    const withImage = mount(<PostByline name="CIP Lima" avatarUrl="https://cdn/cip.png" avatarEmoji="🏛️" />);
    expect(withImage.root.findAllByType(Image)).toHaveLength(1);

    const withEmoji = mount(<PostByline name="CIP Lima" avatarEmoji="🏛️" />);
    expect(withEmoji.root.findAllByType(Image)).toHaveLength(0);
    expect(texts(withEmoji)).toContain('🏛️');

    const bare = mount(<PostByline name="CIP Lima" />);
    expect(texts(bare)).toContain('C');
  });

  it('falls back to the initial when the image fails to load', () => {
    const tree = mount(<PostByline name="CIP Lima" avatarUrl="https://cdn/broken.png" />);
    act(() => tree.root.findByType(Image).props.onError());
    expect(tree.root.findAllByType(Image)).toHaveLength(0);
    expect(texts(tree)).toContain('C');
  });

  it('tries a replaced avatar URL after the previous one failed', () => {
    const tree = mount(<PostByline name="CIP Lima" avatarUrl="https://cdn/broken.png" />);
    act(() => tree.root.findByType(Image).props.onError());
    act(() => tree.update(<PostByline name="CIP Lima" avatarUrl="https://cdn/new-logo.png" />));
    expect(tree.root.findByType(Image).props.source).toEqual({ uri: 'https://cdn/new-logo.png' });
  });
});

describe('ReactionBar', () => {
  it('shows existing reactions, marks the viewer’s, and reacts from the picker', () => {
    const onReact = jest.fn();
    const tree = mount(
      <ReactionBar reactions={[{ emoji: '🔥', count: 4 }, { emoji: '🙌', count: 1 }]} viewerReaction="🙌" onReact={onReact} />,
    );
    const chip = (label: RegExp) => tree.root.find((n) => n.type === Pressable && label.test(n.props.accessibilityLabel || ''));
    expect(chip(/con 🙌, 1 reacción$/).props.accessibilityState).toEqual({ selected: true });
    act(() => chip(/Agregar una reacción/).props.onPress());
    act(() => chip(/^Reaccionar con 😍$/).props.onPress());
    expect(onReact).toHaveBeenCalledWith('😍');
    // Picking closes the picker.
    expect(tree.root.findAll((n) => n.type === Pressable && n.props.accessibilityLabel === 'Reaccionar con 😍')).toHaveLength(0);
  });

  it('renders nothing when there are no reactions and reacting is off', () => {
    const tree = mount(<ReactionBar reactions={[]} canReact={false} onReact={jest.fn()} />);
    expect(tree.toJSON()).toBeNull();
  });
});
