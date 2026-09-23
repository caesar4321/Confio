import { modelsv2 } from 'algosdk';
import { inspectLegacyWalletBalance } from '../legacyWalletBalance';
import { decideWalletReenrollmentAfterRestore } from '../walletReenrollmentDecision';

const ids = ['3351104258', '3198568509', '3198259450', '31566704'];
const account = (amount: number | bigint, minBalance: number | bigint, assets: modelsv2.AssetHolding[] = []) =>
  new modelsv2.Account({ address: 'TEST', amount, minBalance, assets,
    amountWithoutPendingRewards: amount, pendingRewards: 0, rewards: 0, round: 1,
    status: 'Offline', totalAppsOptedIn: 0, totalAssetsOptedIn: assets.length,
    totalCreatedApps: 0, totalCreatedAssets: 0 });

describe('legacy balance inspection using real SDK models', () => {
  it.each([[300000, 300000, 0], [568000, 557000, 11000]])(
    'excludes the locked minimum (%i total, %i locked)', (amount, minimum, spendable) => {
      const result = inspectLegacyWalletBalance(account(amount, minimum), ids);
      expect(result.spendableAlgo).toBe(BigInt(spendable));
      expect(result.hasMaterialValue).toBe(false);
      expect(decideWalletReenrollmentAfterRestore({ serverAlgorandAddress: 'SERVER',
        restoredAlgorandAddress: 'LEGACY', legacyAddressWithValue: result.hasMaterialValue ? 'LEGACY' : null,
        reenrollmentOffered: true })).toBe('repair_collision');
    });

  it.each(ids)('detects positive token holdings for %s', id => {
    const result = inspectLegacyWalletBalance(account(100000, 100000, [
      new modelsv2.AssetHolding({ assetId: BigInt(id), amount: 1, isFrozen: false }),
    ]), ids);
    expect(result.hasMaterialValue).toBe(true);
    expect(result.relevantAssets[0].assetId).toBe(id);
  });

  it.each([[199999, false], [200000, true], [200001, true]])('checks the spendable threshold at %i', (amount, expected) => {
    expect(inspectLegacyWalletBalance(account(amount as number, 100000), ids).hasMaterialValue).toBe(expected);
  });

  it('retains empty opt-ins for migration without treating them as funds', () => {
    const result = inspectLegacyWalletBalance(account(300000, 300000, [
      new modelsv2.AssetHolding({ assetId: 3198259450, amount: 0, isFrozen: false }),
      new modelsv2.AssetHolding({ assetId: 999, amount: 123, isFrozen: false }),
    ]), ids);
    expect(result.relevantAssets).toHaveLength(1);
    expect(result.hasMaterialValue).toBe(false);
  });

  it('subtracts large balances exactly without floating-point rounding', () => {
    const minimum = BigInt(Number.MAX_SAFE_INTEGER) + BigInt(100);
    expect(inspectLegacyWalletBalance(account(minimum + BigInt(99999), minimum), ids).hasMaterialValue).toBe(false);
    expect(inspectLegacyWalletBalance(account(minimum + BigInt(100000), minimum), ids).hasMaterialValue).toBe(true);
  });

  it.each([undefined, null, NaN, -1, 1.5, '100000', Number.MAX_SAFE_INTEGER + 1])(
    'rejects malformed balances instead of declaring the wallet empty (%s)', bad => {
      expect(() => inspectLegacyWalletBalance({ amount: BigInt(100000), minBalance: bad } as any, ids)).toThrow();
      expect(() => inspectLegacyWalletBalance({ amount: bad, minBalance: BigInt(100000) } as any, ids)).toThrow();
    });

  it('rejects malformed holdings rather than silently ignoring tokens', () => {
    expect(() => inspectLegacyWalletBalance({ amount: BigInt(0), minBalance: BigInt(0),
      assets: [{ 'asset-id': 31566704, amount: BigInt(1) }] } as any, ids)).toThrow();
  });

  it('clamps an underfunded account to zero spendable ALGO', () => {
    expect(inspectLegacyWalletBalance(account(0, 100000), ids).spendableAlgo).toBe(BigInt(0));
  });
});
