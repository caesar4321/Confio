export function isOlderWalletAnchorsSchemaError(error: any): boolean {
  const messages = [
    error?.message,
    ...(Array.isArray(error?.graphQLErrors)
      ? error.graphQLErrors.map((item: any) => item?.message)
      : []),
  ]
    .filter(Boolean)
    .join(' ');

  return /Cannot query field ["'](?:myWalletAnchors|solanaAddress)["']/i.test(messages);
}

export async function fetchCompatibleWalletAnchors(
  query: (document: any) => Promise<any>,
  currentDocument: any,
  legacyDocument: any,
): Promise<any | null> {
  try {
    const result = await query(currentDocument);
    return result?.data?.myWalletAnchors || null;
  } catch (error) {
    if (!isOlderWalletAnchorsSchemaError(error)) throw error;
  }
  try {
    const result = await query(legacyDocument);
    return result?.data?.myWalletAnchors || null;
  } catch (error) {
    if (!isOlderWalletAnchorsSchemaError(error)) throw error;
    return null;
  }
}
