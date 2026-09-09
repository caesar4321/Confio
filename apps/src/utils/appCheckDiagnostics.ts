// Deliberately discard native error text: it can contain URLs or identifiers.
export function appCheckDiagnosticCode(value: unknown): string {
  const error = typeof value === 'string' ? value.toLowerCase().slice(0, 512) : '';
  if (!error) return 'unknown';
  const categories: [string, string][] = [
    ['app attestation failed', 'attestation_rejected'],
    ['too many attempts', 'backoff'], ['too_many_requests', 'rate_limited'],
    ['api_not_available', 'api_unavailable'], ['cannot_bind_to_service', 'service_unavailable'],
    ['play_store_not_found', 'play_store_missing'], ['network', 'network_error'],
    ['empty_token', 'empty_token'],
    ['appcheck_fetch_timeout', 'fetch_timeout'],
  ];
  return categories.find(([needle]) => error.includes(needle))?.[1] || 'unknown';
}
