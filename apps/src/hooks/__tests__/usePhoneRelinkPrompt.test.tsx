/**
 * The relink prompt approves moving a phone number between accounts, so every
 * answer must reach only the question it was rendered for, and any question
 * left open (close, unmount, replacement) must fail closed.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { usePhoneRelinkPrompt } from '../usePhoneRelinkPrompt';

const A = { token: 'token-a', accounts: [{ email: 'a@example.com', username: 'a' }] };
const B = { token: 'token-b', accounts: [{ email: 'b@example.com', username: 'b' }] };

const mount = () => {
  let api!: ReturnType<typeof usePhoneRelinkPrompt>;
  const Probe = () => {
    api = usePhoneRelinkPrompt();
    return null;
  };
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(<Probe />);
  });
  return { hook: () => api, tree };
};

const track = (promise: Promise<boolean>) => {
  const state: { settled: boolean; value?: boolean } = { settled: false };
  promise.then(value => {
    state.settled = true;
    state.value = value;
  });
  return state;
};

const flush = () => act(async () => {});

describe('usePhoneRelinkPrompt', () => {
  it('keeps the prompt presented while an approved change is confirmed', async () => {
    const { hook } = mount();
    let answer!: Promise<boolean>;
    act(() => { answer = hook().ask(A); });
    expect(hook().prompt).toMatchObject({ confirmation: A, phase: 'ask', replaced: false });

    act(() => hook().answer(hook().prompt!.id, true));
    await expect(answer).resolves.toBe(true);
    expect(hook().prompt).toMatchObject({ confirmation: A, phase: 'confirming' });
  });

  it('cancel closes the prompt and never approves', async () => {
    const { hook } = mount();
    let answer!: Promise<boolean>;
    act(() => { answer = hook().ask(A); });
    act(() => hook().answer(hook().prompt!.id, false));
    await expect(answer).resolves.toBe(false);
    expect(hook().prompt).toBeNull();
  });

  it('a stale answer for an earlier prompt cannot approve a replacement', async () => {
    const { hook } = mount();
    let first!: Promise<boolean>;
    act(() => { first = hook().ask(A); });
    const staleId = hook().prompt!.id;
    act(() => hook().answer(staleId, true));
    await first;

    let second!: Promise<boolean>;
    act(() => { second = hook().ask(B); });
    const state = track(second);
    expect(hook().prompt).toMatchObject({ confirmation: B, phase: 'ask', replaced: true });

    act(() => hook().answer(staleId, true));
    await flush();
    expect(state.settled).toBe(false);
    expect(hook().prompt).toMatchObject({ confirmation: B, phase: 'ask' });

    act(() => hook().answer(hook().prompt!.id, false));
    await expect(second).resolves.toBe(false);
  });

  it('answering the same prompt twice only counts once', async () => {
    const { hook } = mount();
    let answer!: Promise<boolean>;
    act(() => { answer = hook().ask(A); });
    const id = hook().prompt!.id;
    act(() => hook().answer(id, true));
    act(() => hook().answer(id, false));
    await expect(answer).resolves.toBe(true);
    expect(hook().prompt?.phase).toBe('confirming');
  });

  it('retry swaps the open prompt into a retry state in place', async () => {
    const { hook } = mount();
    let approved!: Promise<boolean>;
    act(() => { approved = hook().ask(A); });
    act(() => hook().answer(hook().prompt!.id, true));
    await approved;

    let retry!: Promise<boolean>;
    act(() => { retry = hook().retry(A); });
    expect(hook().prompt).toMatchObject({ confirmation: A, phase: 'retry', replaced: false });
    act(() => hook().answer(hook().prompt!.id, true));
    await expect(retry).resolves.toBe(true);
    expect(hook().prompt?.phase).toBe('confirming');
  });

  it('retry shows the pending confirmation even when no prompt was open', async () => {
    const { hook } = mount();
    let retry!: Promise<boolean>;
    act(() => { retry = hook().retry(A); });
    expect(hook().prompt).toMatchObject({ confirmation: A, phase: 'retry' });
    act(() => hook().answer(hook().prompt!.id, false));
    await expect(retry).resolves.toBe(false);
    expect(hook().prompt).toBeNull();
  });

  it('close fails an open question closed', async () => {
    const { hook } = mount();
    let answer!: Promise<boolean>;
    act(() => { answer = hook().ask(A); });
    act(() => hook().close());
    await expect(answer).resolves.toBe(false);
    expect(hook().prompt).toBeNull();
  });

  it('unmount fails an open question closed', async () => {
    const { hook, tree } = mount();
    let answer!: Promise<boolean>;
    act(() => { answer = hook().ask(A); });
    act(() => tree.unmount());
    await expect(answer).resolves.toBe(false);
  });
});
