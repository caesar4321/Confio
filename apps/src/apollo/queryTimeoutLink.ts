import { ApolloLink, Observable } from '@apollo/client';
import { getMainDefinition } from '@apollo/client/utilities';

export const QUERY_TIMEOUT_MS = 20_000;

export class QueryTimeoutError extends Error {
  constructor(operationName: string, ms: number) {
    super(`Request timed out after ${ms / 1000}s (${operationName || 'anonymous'})`);
    this.name = 'QueryTimeoutError';
  }
}

const isQuery = (operation: Parameters<ApolloLink['request']>[0]) => {
  const definition = getMainDefinition(operation.query);
  return definition.kind === 'OperationDefinition' && definition.operation === 'query';
};

/**
 * Ends a read that never answers (a hung connection, a black-holed route) as
 * an error, so screens show their retry state instead of spinning forever.
 * The fetch itself is aborted, not just abandoned.
 *
 * Queries only: a mutation that times out on the phone may still complete on
 * the server, and surfacing it as a failure invites a second send or payment.
 */
export const createQueryTimeoutLink = (ms: number = QUERY_TIMEOUT_MS) =>
  new ApolloLink((operation, forward) => {
    if (!isQuery(operation)) {
      return forward(operation);
    }
    return new Observable((observer) => {
      const controller = new AbortController();
      const { fetchOptions } = operation.getContext();
      operation.setContext({ fetchOptions: { ...fetchOptions, signal: controller.signal } });

      let finished = false;
      let subscription: { unsubscribe: () => void } | undefined;
      // Armed before subscribing: a link below may answer synchronously.
      const timer = setTimeout(() => {
        if (finished) return;
        finished = true;
        subscription?.unsubscribe();
        controller.abort();
        observer.error(new QueryTimeoutError(operation.operationName, ms));
      }, ms);
      subscription = forward(operation).subscribe({
        next: (value) => observer.next(value),
        error: (error) => {
          finished = true;
          clearTimeout(timer);
          observer.error(error);
        },
        complete: () => {
          finished = true;
          clearTimeout(timer);
          observer.complete();
        },
      });

      return () => {
        clearTimeout(timer);
        subscription?.unsubscribe();
        // Unsubscribed before an answer (screen left): cancel the request,
        // as Apollo's own controller would have.
        if (!finished) controller.abort();
      };
    });
  });
