import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Image, Text } from 'react-native';

import { VenueAttribution } from '../VenueAttribution';

const render = (el: React.ReactElement) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(el); });
  return tree;
};
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(Text).map((t) => [].concat(t.props.children).join(''));

describe('VenueAttribution', () => {
  it('names the venue with its logo, never as a partner', () => {
    const tree = render(<VenueAttribution venue="hyperliquid" />);
    const all = texts(tree).join(' | ');
    expect(all).toContain('Se opera en');
    expect(all).toContain('Hyperliquid');
    expect(all).toContain('Exchange descentralizado de terceros, independiente de Confío');
    expect(all).not.toContain('alianza');
    expect(tree.root.findAllByType(Image)).toHaveLength(1);
  });

  it('compact keeps the independence note for screen readers', () => {
    const tree = render(<VenueAttribution venue="pancakeswap" compact testID="v" />);
    expect(texts(tree).join(' | ')).not.toContain('independiente');
    const wrap = tree.root.find((n) => n.props.testID === 'v' && typeof n.type === 'string');
    expect(wrap.props.accessibilityLabel).toBe(
      'Se opera en PancakeSwap. Exchange descentralizado de terceros, independiente de Confío.');
  });
});
