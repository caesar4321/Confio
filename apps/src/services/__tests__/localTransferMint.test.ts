const mockQuery = jest.fn();
const mockMint = jest.fn();
jest.mock('../../apollo/client', () => ({apolloClient: {query: (...args: unknown[]) => mockQuery(...args), mutate: jest.fn()}}));
jest.mock('../cusdPlusVault', () => ({
  INTERNAL_CUSD_MIN_WRAP_WEI: 1000001000000000000n,
  mintUsdtToCusd: (...args: unknown[]) => mockMint(...args),
  subscribeUsdtToSavings: (...args: unknown[]) => mockMint(...args),
  unwrapAllSavingsToCusd: jest.fn(), wrapAllCusdToSavings: jest.fn(),
}));
import {resumeSavingsMints} from '../savingsLegC';

const id = 'f311c949-8876-4b53-b3f6-0d5faaf7a97a';
beforeEach(() => {
  mockQuery.mockReset(); mockMint.mockReset();
  mockMint.mockResolvedValue({mintTx: '0x123'});
  mockQuery.mockImplementation(async ({query}: any) => {
    const name = query.definitions[0].name.value;
    if (name === 'LocalTransferMints') return {data: {localTransferMints: [{internalId: id, walletMintUnits: '1982000000000000000'}]}};
    if (name === 'CusdPlusConversionsInFlight') return {data: {cusdPlusConversionsInFlight: []}};
    return {data: {cusdPlusSummary: {savingsEnabled: false, sweepableUsdtWei: '0', balanceUsd: 0, cusdBalanceWei: '0'}}};
  });
});
it('uses the exact arrival and stable signed identity, not a generic sweep', async () => {
  await resumeSavingsMints('vault', 'cusd');
  expect(mockMint).toHaveBeenCalledTimes(1);
  expect(mockMint).toHaveBeenCalledWith({cusdAddress: 'cusd', usdtWei: 1982000000000000000n, requestId: `local-mint-${id}`});
});
it('reuses the identity after a transport failure', async () => {
  mockMint.mockRejectedValueOnce(new Error('transport'));
  await resumeSavingsMints('vault', 'cusd');
  await resumeSavingsMints('vault', 'cusd');
  expect(mockMint.mock.calls[0][0].requestId).toBe(mockMint.mock.calls[1][0].requestId);
});
it('does not sweep unclassified funds when the local query fails', async () => {
  mockQuery.mockRejectedValue(new Error('offline'));
  await resumeSavingsMints('vault', 'cusd');
  expect(mockMint).not.toHaveBeenCalled();
});
it('finishes small local receipts as cUSD even for savings-eligible users', async () => {
  mockQuery.mockImplementation(async ({query}: any) => {
    const name = query.definitions[0].name.value;
    if (name === 'LocalTransferMints') return {data: {localTransferMints: [{internalId: id, walletMintUnits: '500000000000000000'}]}};
    if (name === 'CusdPlusConversionsInFlight') return {data: {cusdPlusConversionsInFlight: []}};
    return {data: {cusdPlusSummary: {savingsEnabled: true, sweepableUsdtWei: '0', balanceUsd: 0, cusdBalanceWei: '0'}}};
  });
  await resumeSavingsMints('vault', 'cusd');
  expect(mockMint).toHaveBeenCalledWith({cusdAddress: 'cusd', usdtWei: 500000000000000000n, requestId: `local-mint-${id}`});
});

it('binds the collector fee to the exact local mint even with savings enabled', async () => {
  mockQuery.mockImplementation(async ({query}: any) => {
    const name = query.definitions[0].name.value;
    if (name === 'LocalTransferMints') return {data: {localTransferMints: [{internalId: id,
      walletMintUnits: '5000000000000000000', walletMintRequestId: `local-mint-${id}`,
      walletFeeUnits: '1250000000000000000', walletFeeCollector: '0x'+'12'.repeat(20),
      walletFeeMinimumNetUnits: '3000000000000000000'}]}};
    if (name === 'CusdPlusConversionsInFlight') return {data: {cusdPlusConversionsInFlight: []}};
    return {data: {cusdPlusSummary: {savingsEnabled: true, sweepableUsdtWei: '0', balanceUsd: 0, cusdBalanceWei: '0'}}};
  });
  await resumeSavingsMints('vault', 'cusd');
  expect(mockMint).toHaveBeenCalledWith({cusdAddress: 'cusd', usdtWei: 5000000000000000000n,
    requestId: `local-mint-${id}`, localFee: {collector: '0x'+'12'.repeat(20),
      units: 1250000000000000000n, minimumNetUnits: 3000000000000000000n}});
});

it('does not fall back to a fee-free mint when collector details are missing', async () => {
  mockQuery.mockImplementation(async ({query}: any) => {
    if (query.definitions[0].name.value === 'LocalTransferMints') return {data: {localTransferMints: [{
      internalId: id, walletMintUnits: '5000000000000000000', walletFeeUnits: '1250000000000000000'}]}};
    return {data: {cusdPlusSummary: {savingsEnabled: false, sweepableUsdtWei: '0'}}};
  });
  await resumeSavingsMints('vault', 'cusd');
  expect(mockMint).not.toHaveBeenCalled();
});
