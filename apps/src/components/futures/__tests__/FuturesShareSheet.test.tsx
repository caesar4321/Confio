import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockShare = jest.fn(async (_opts: any) => ({}));
let releaseCapture: (uri: string) => void = () => {};
const mockSave = jest.fn(async (_uri: string, _opts: any) => 'ph://1');
jest.mock('@react-native-camera-roll/camera-roll', () => ({ CameraRoll: { save: (u: string, o: any) => mockSave(u, o) } }));
jest.mock('react-native-share', () => ({ __esModule: true, default: { open: (o: any) => mockShare(o) } }));
jest.mock('react-native-view-shot', () => {
  const R = require('react');
  return {
    __esModule: true,
    default: R.forwardRef(({ children }: any, ref: any) => {
      R.useImperativeHandle(ref, () => ({
        capture: () => new Promise<string>((resolve) => { releaseCapture = resolve; }),
      }));
      return children;
    }),
  };
});
jest.mock('react-native-svg', () => {
  const R = require('react');
  const Stub = ({ children }: any) => R.createElement(R.Fragment, null, children);
  return { __esModule: true, default: Stub, Defs: Stub, LinearGradient: Stub, Rect: Stub, Stop: Stub };
});
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../PerpMarketMark', () => ({ PerpMarketMark: () => null }));

import { FuturesShareSheet } from '../FuturesShareSheet';

const position: any = {
  id: '7', coin: 'xyz:TSLA', ticker: 'TSLA', name: 'Tesla', side: 'long', leverage: 5, marginUsd: 10, state: 'open',
  size: 0.1, entryPx: 400, markPx: 410, unrealizedPnlUsd: 1, returnOnEquity: 0.1, marginUsedUsd: 10,
  liquidation: null, resultUsd: null, putInUsd: 10,
};

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll((n) => typeof n.props.children === 'string').map((n) => n.props.children).join(' | ');

describe('FuturesShareSheet', () => {
  beforeAll(() => { (globalThis as any).requestAnimationFrame = (cb: any) => setTimeout(cb, 0); });

  it('shares the card frozen at the press, even if the price moves while it is captured', async () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<FuturesShareSheet visible onClose={() => {}} position={position} kind="position" liveMid={420} />);
    });
    expect(texts(tree)).toMatch(/\+20[.,]00%/);
    const go = tree.root.findByProps({ testID: 'futures-share-go' });
    let pending!: Promise<void>;
    await act(async () => {
      pending = go.props.onPress() ?? Promise.resolve();
      await new Promise((r) => setTimeout(r, 5));
    });
    // A price tick arrives mid-capture: the card keeps showing what is being shared.
    act(() => {
      tree.update(<FuturesShareSheet visible onClose={() => {}} position={position} kind="position" liveMid={380} />);
    });
    expect(texts(tree)).toMatch(/\+20[.,]00%/);
    expect(tree.root.findByProps({ testID: 'futures-share-usd' }).props.disabled).toBe(true);
    await act(async () => { releaseCapture('file:///card.png'); await pending; await new Promise((r) => setTimeout(r, 5)); });
    expect(mockShare).toHaveBeenCalledTimes(1);
    const sent = mockShare.mock.calls[0][0];
    expect(sent.url).toBe('file:///card.png');
    expect(sent.message).toMatch(/\+20[.,]00%/);
    expect(sent.message).not.toMatch(/US\$/);
    // Done: the card follows the live price again.
    expect(texts(tree)).toMatch(/−20[.,]00%/);
  });

  it('saves the frozen card to the gallery and says so', async () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<FuturesShareSheet visible onClose={() => {}} position={position} kind="position" liveMid={420} />);
    });
    const save = tree.root.findByProps({ testID: 'futures-share-save' });
    await act(async () => {
      save.props.onPress();
      await new Promise((r) => setTimeout(r, 5));
    });
    expect(texts(tree)).toMatch(/Guardando…/);
    expect(tree.root.findByProps({ testID: 'futures-share-go' }).props.disabled).toBe(true);
    await act(async () => { releaseCapture('file:///saved.png'); await new Promise((r) => setTimeout(r, 5)); });
    expect(mockSave).toHaveBeenCalledWith('file:///saved.png', { type: 'photo' });
    expect(texts(tree)).toMatch(/Guardada/);
    // Turning dollars on makes a different card: it is not saved yet.
    act(() => { tree.root.findByProps({ testID: 'futures-share-usd' }).props.onValueChange(true); });
    expect(texts(tree)).toMatch(/Guardar imagen/);
  });

  it('closing the sheet mid-capture voids it: no share sheet opens later', async () => {
    mockShare.mockClear();
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<FuturesShareSheet visible onClose={() => {}} position={position} kind="position" liveMid={420} />);
    });
    await act(async () => {
      tree.root.findByProps({ testID: 'futures-share-go' }).props.onPress();
      await new Promise((r) => setTimeout(r, 5));
    });
    act(() => {
      tree.update(<FuturesShareSheet visible={false} onClose={() => {}} position={position} kind="position" liveMid={420} />);
    });
    await act(async () => { releaseCapture('file:///late.png'); await new Promise((r) => setTimeout(r, 5)); });
    expect(mockShare).not.toHaveBeenCalled();
  });

  it('"Guardada" lasts only while the card on screen is the one saved', async () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<FuturesShareSheet visible onClose={() => {}} position={position} kind="position" liveMid={420} />);
    });
    await act(async () => {
      tree.root.findByProps({ testID: 'futures-share-save' }).props.onPress();
      await new Promise((r) => setTimeout(r, 5));
    });
    await act(async () => { releaseCapture('file:///s.png'); await new Promise((r) => setTimeout(r, 5)); });
    expect(texts(tree)).toMatch(/Guardada/);
    act(() => {
      tree.update(<FuturesShareSheet visible onClose={() => {}} position={position} kind="position" liveMid={430} />);
    });
    expect(texts(tree)).toMatch(/Guardar imagen/);
  });
});
