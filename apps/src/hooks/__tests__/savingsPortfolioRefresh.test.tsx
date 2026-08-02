/**
 * Why the account-switch hooks must never call apolloClient.stop().
 *
 * They used to run: stop() -> cache.reset() -> reFetchObservableQueries().
 * stop() unregisters every ObservableQuery from the QueryManager, so the
 * refetch that follows iterates an empty map: no network call, no polling,
 * and every mounted screen keeps rendering the account the user just left.
 * Home's Confío Dollar / Confío Dollar+ row is one of those screens.
 *
 * These cases pin the mechanism on a mounted useQuery — the shape every
 * balance/eligibility row on Home has — so the sequence can't drift back.
 */
import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';
import { ApolloClient, ApolloLink, ApolloProvider, InMemoryCache, Observable, gql, useQuery } from '@apollo/client';
import { Text } from 'react-native';

const Q = gql`query AhorroPortfolio { cusdPlusSummary { savingsEnabled balanceUsd } }`;

const flush = async (ms = 20) => {
  await act(async () => { await new Promise((r) => setTimeout(r, ms)); });
};

const makeClient = (state: { account: string; calls: number }) => {
  const link = new ApolloLink(() => new Observable<any>((obs) => {
    state.calls++;
    const acct = state.account;
    setTimeout(() => {
      obs.next({ data: { cusdPlusSummary: {
        __typename: 'CusdPlusSummaryType',
        savingsEnabled: acct === 'personal',
        balanceUsd: acct === 'personal' ? 42 : 7,
      } } });
      obs.complete();
    }, 5);
  }));
  return new ApolloClient({
    link,
    cache: new InMemoryCache({ typePolicies: { Query: { fields: { cusdPlusSummary: { merge: true } } } } }),
  });
};

const Row: React.FC<{ authReady: boolean }> = ({ authReady }) => {
  const { data } = useQuery(Q, {
    fetchPolicy: 'cache-and-network',
    pollInterval: 200,
    skip: !authReady,
  });
  const enabled = data?.cusdPlusSummary?.savingsEnabled ?? true;
  return <Text>{enabled ? 'Confío Dollar+' : 'Confío Dollar'}</Text>;
};

const label = (r: TestRenderer.ReactTestRenderer) => r.root.findByType(Text).props.children;

describe('Home eligibility row across auth-ready and account switch', () => {
  it('fetches once auth becomes ready (cold start)', async () => {
    const state = { account: 'business', calls: 0 };
    const client = makeClient(state);
    let renderer!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      renderer = TestRenderer.create(
        <ApolloProvider client={client}><Row authReady={false} /></ApolloProvider>,
      );
    });
    expect(state.calls).toBe(0);
    expect(label(renderer)).toBe('Confío Dollar+'); // fail-open default while gated

    await act(async () => {
      renderer.update(<ApolloProvider client={client}><Row authReady /></ApolloProvider>);
    });
    await flush(40);
    expect(state.calls).toBe(1);
    expect(label(renderer)).toBe('Confío Dollar'); // server answer wins
  });

  it('strands mounted queries on the OLD account when the switch calls stop()', async () => {
    const state = { account: 'business', calls: 0 };
    const client = makeClient(state);
    let renderer!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      renderer = TestRenderer.create(
        <ApolloProvider client={client}><Row authReady /></ApolloProvider>,
      );
    });
    await flush(40);
    expect(label(renderer)).toBe('Confío Dollar');

    // ---- exactly what useAtomicAccountSwitch does ----
    await act(async () => {
      client.stop();
      await client.cache.reset();
      state.account = 'personal';
      await new Promise((r) => setTimeout(r, 300)); // token round-trip + hook's delay
      await client.reFetchObservableQueries();
    });
    await flush(60);

    // The switch issued no network call for this query...
    expect(state.calls).toBe(1);
    // ...so the row still shows the business account's answer.
    expect(label(renderer)).toBe('Confío Dollar');

    // ...and polling is dead too: 3 poll windows pass with no fetch.
    await flush(700);
    expect(state.calls).toBe(1);
  });

  it('picks up the new account with the clearStore sequence the hooks now use', async () => {
    const state = { account: 'business', calls: 0 };
    const client = makeClient(state);
    let renderer!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      renderer = TestRenderer.create(
        <ApolloProvider client={client}><Row authReady /></ApolloProvider>,
      );
    });
    await flush(40);
    expect(label(renderer)).toBe('Confío Dollar');

    // clearStore() alone: cancels in-flight fetches and empties the cache,
    // but leaves mounted observers registered with the QueryManager.
    await act(async () => {
      await client.clearStore();
      state.account = 'personal';
      await new Promise((r) => setTimeout(r, 300));
      await client.reFetchObservableQueries();
    });
    await flush(60);

    expect(state.calls).toBeGreaterThan(1);
    expect(label(renderer)).toBe('Confío Dollar+');

    // ...and polling survives the switch.
    const before = state.calls;
    await flush(700);
    expect(state.calls).toBeGreaterThan(before);
  });
});
