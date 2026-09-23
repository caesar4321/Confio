import { ApolloLink, Observable, execute, gql } from '@apollo/client';
import { QueryTimeoutError, createQueryTimeoutLink } from '../queryTimeoutLink';

const QUERY = gql`query Slow { ping }`;
const MUTATION = gql`mutation Pay { pay }`;

const hangingLink = (seen: { signal?: AbortSignal }) =>
  new ApolloLink((operation) => {
    seen.signal = operation.getContext().fetchOptions?.signal;
    return new Observable(() => {});
  });

describe('queryTimeoutLink', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('fails a hung query and aborts its fetch', () => {
    const seen: { signal?: AbortSignal } = {};
    const error = jest.fn();
    execute(createQueryTimeoutLink(1000).concat(hangingLink(seen)), { query: QUERY }).subscribe({ error });
    jest.advanceTimersByTime(999);
    expect(error).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(error.mock.calls[0][0]).toBeInstanceOf(QueryTimeoutError);
    expect(seen.signal?.aborted).toBe(true);
  });

  it('never times out a mutation', () => {
    const seen: { signal?: AbortSignal } = {};
    const error = jest.fn();
    execute(createQueryTimeoutLink(1000).concat(hangingLink(seen)), { query: MUTATION }).subscribe({ error });
    jest.advanceTimersByTime(60_000);
    expect(error).not.toHaveBeenCalled();
    expect(seen.signal).toBeUndefined();
  });

  it('leaves an answered query alone, even one answered synchronously', async () => {
    jest.useRealTimers();
    const answer = new ApolloLink(() => new Observable((o) => {
      o.next({ data: { ping: 'pong' } });
      o.complete();
    }));
    const next = jest.fn();
    const error = jest.fn();
    execute(createQueryTimeoutLink(20).concat(answer), { query: QUERY }).subscribe({ next, error });
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(next).toHaveBeenCalledWith({ data: { ping: 'pong' } });
    expect(error).not.toHaveBeenCalled();
  });

  it('cancels the request when the screen unsubscribes first', () => {
    const seen: { signal?: AbortSignal } = {};
    const sub = execute(createQueryTimeoutLink(1000).concat(hangingLink(seen)), { query: QUERY }).subscribe({});
    sub.unsubscribe();
    expect(seen.signal?.aborted).toBe(true);
  });
});
