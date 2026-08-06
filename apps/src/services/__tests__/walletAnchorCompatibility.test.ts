import {
  fetchCompatibleWalletAnchors,
  isOlderWalletAnchorsSchemaError,
} from '../walletAnchorCompatibility';

describe('isOlderWalletAnchorsSchemaError', () => {
  it('accepts an older server without myWalletAnchors', () => {
    expect(isOlderWalletAnchorsSchemaError({
      graphQLErrors: [{ message: 'Cannot query field "myWalletAnchors" on type "Query".' }],
    })).toBe(true);
  });

  it('accepts the intermediate schema without solanaAddress', () => {
    expect(isOlderWalletAnchorsSchemaError(
      new Error('Cannot query field "solanaAddress" on type "WalletAnchorsType".'),
    )).toBe(true);
  });

  it('does not downgrade network, authentication, or database failures', () => {
    expect(isOlderWalletAnchorsSchemaError(new Error('Network request failed'))).toBe(false);
    expect(isOlderWalletAnchorsSchemaError(new Error('relation users_account does not exist'))).toBe(false);
    expect(isOlderWalletAnchorsSchemaError(new Error('Authentication required'))).toBe(false);
  });

  it('retries the legacy anchor document and preserves the BSC anchor', async () => {
    const query = jest.fn()
      .mockRejectedValueOnce(new Error('Cannot query field "solanaAddress" on type "WalletAnchorsType".'))
      .mockResolvedValueOnce({ data: { myWalletAnchors: { algorandAddress: null, bscAddress: '0xabc' } } });
    await expect(fetchCompatibleWalletAnchors(query, 'v2', 'v1')).resolves.toEqual({
      algorandAddress: null,
      bscAddress: '0xabc',
    });
    expect(query).toHaveBeenNthCalledWith(1, 'v2');
    expect(query).toHaveBeenNthCalledWith(2, 'v1');
  });

  it('fails closed instead of retrying on transport errors', async () => {
    const query = jest.fn().mockRejectedValue(new Error('Network request failed'));
    await expect(fetchCompatibleWalletAnchors(query, 'v2', 'v1')).rejects.toThrow(/Network/);
    expect(query).toHaveBeenCalledTimes(1);
  });
});
