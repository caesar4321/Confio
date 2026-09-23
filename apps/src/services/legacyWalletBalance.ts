import type { modelsv2 } from 'algosdk';

function unsignedInteger(value: unknown): bigint {
  if ((typeof value !== 'bigint' && !(typeof value === 'number' && Number.isSafeInteger(value)))
      || value < 0) {
    throw new Error('Invalid legacy wallet balance data');
  }
  return BigInt(value);
}

/** Inspect decoded SDK account models, not the hyphenated REST JSON shape. */
export function inspectLegacyWalletBalance(
  info: Pick<modelsv2.Account, 'amount' | 'minBalance' | 'assets'>,
  relevantAssetIds: readonly (string | number)[],
) {
  const assets = (info.assets || []).map(asset => ({
    assetId: unsignedInteger(asset.assetId).toString(),
    amount: unsignedInteger(asset.amount),
  }));
  const relevantAssets = assets.filter(asset => relevantAssetIds.some(id => String(id) === asset.assetId));
  // Do not default missing balances to zero: invalid data must propagate to
  // the caller's failed-inspection path, never authorize replacement.
  const spendableAlgo = unsignedInteger(info.amount) - unsignedInteger(info.minBalance);
  return {
    assets,
    relevantAssets,
    spendableAlgo: spendableAlgo > BigInt(0) ? spendableAlgo : BigInt(0),
    hasMaterialValue: relevantAssets.some(asset => asset.amount > BigInt(0)) || spendableAlgo >= BigInt(100_000),
  };
}
