import type { ApolloError } from '@apollo/client';

/**
 * True only when the server rejected the query's shape — it predates a field,
 * argument or value this build sends. A timeout or a 500 says nothing about
 * the schema and must not strand a user on a legacy fallback. Graphene answers
 * a validation failure with HTTP 400, so the message sits on the network
 * error's parsed body, not on graphQLErrors. `extra` names server-specific
 * rejections that also mean "older server" (e.g. an unknown enum-like value).
 */
export const isSchemaMismatch = (error?: ApolloError, extra?: RegExp) => {
  if (!error) return false;
  const bodyErrors = (error.networkError as { result?: { errors?: Array<{ message?: string }> } } | null)
    ?.result?.errors ?? [];
  const text = [error.message, ...(error.graphQLErrors ?? []).map((e) => e.message), ...bodyErrors.map((e) => e.message)]
    .join(' ');
  return /Cannot query field|Unknown (field|argument|type)/i.test(text) || Boolean(extra?.test(text));
};
