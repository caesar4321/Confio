import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Image } from 'react-native';

import { TickerLogo } from '../TickerLogo';

describe('TickerLogo share-card callbacks', () => {
  it('marks its url pending on mount, settled on load', () => {
    const pending = jest.fn(); const settled = jest.fn();
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<TickerLogo ticker="TSLA" color="#000" logoUrl="u1" onPending={pending} onSettled={settled} />); });
    expect(pending).toHaveBeenCalledWith('u1');
    act(() => { tree.root.findByType(Image).props.onLoad(); });
    expect(settled).toHaveBeenCalledWith('u1');
  });

  it('a failure belongs to its url: the next url gets an image again', () => {
    const pending = jest.fn(); const settled = jest.fn();
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<TickerLogo ticker="TSLA" color="#000" logoUrl="bad" onPending={pending} onSettled={settled} />); });
    act(() => { tree.root.findByType(Image).props.onError(); });
    expect(settled).toHaveBeenCalledWith('bad');
    expect(tree.root.findAllByType(Image)).toHaveLength(0);
    act(() => { tree.update(<TickerLogo ticker="TSLA" color="#000" logoUrl="good" onPending={pending} onSettled={settled} />); });
    expect(tree.root.findAllByType(Image)).toHaveLength(1);
    expect(pending).toHaveBeenLastCalledWith('good');
  });

  it('a share card logo never fades in (it is captured right after onLoad)', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<TickerLogo ticker="TSLA" color="#000" logoUrl="u" onSettled={() => {}} />); });
    expect(tree.root.findByType(Image).props.fadeDuration).toBe(0);
    act(() => { tree.update(<TickerLogo ticker="TSLA" color="#000" logoUrl="u" />); });
    expect(tree.root.findByType(Image).props.fadeDuration).toBeUndefined();
  });
});
