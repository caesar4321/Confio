/** Only an explicit local-transfer identity may open this receipt. */
export function localTransferRoute(value: unknown) {
  if (typeof value !== 'string') return null;
  const id = value.replace(/^confio:\/\/local-transfer\//, '');
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) return null;
  return {screen: 'LocalTransferStatus' as const, params: {journeyId: id}};
}
