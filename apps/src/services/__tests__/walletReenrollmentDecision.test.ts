import {
  decideWalletReenrollmentAfterRestore,
  selectRestoredAddressForCollision,
  selectLegacyAddressForServer,
} from '../walletReenrollmentDecision';

describe('decideWalletReenrollmentAfterRestore', () => {
  const serverAlgorandAddress = 'SERVER_ALGORAND_ADDRESS';

  it('never reenrolls when normal restoration matches the server address', () => {
    expect(
      decideWalletReenrollmentAfterRestore({
        serverAlgorandAddress,
        restoredAlgorandAddress: serverAlgorandAddress,
        legacyAddressWithValue: null,
        reenrollmentOffered: true,
      }),
    ).toBe('no_collision');
  });

  it('uses the server safety offer only after a real empty-wallet collision', () => {
    expect(
      decideWalletReenrollmentAfterRestore({
        serverAlgorandAddress,
        restoredAlgorandAddress: 'DIFFERENT_LOCAL_ADDRESS',
        legacyAddressWithValue: null,
        reenrollmentOffered: true,
      }),
    ).toBe('repair_collision');
  });

  it('refuses a collision when the server did not authorize repair', () => {
    expect(
      decideWalletReenrollmentAfterRestore({
        serverAlgorandAddress,
        restoredAlgorandAddress: 'DIFFERENT_LOCAL_ADDRESS',
        legacyAddressWithValue: null,
        reenrollmentOffered: false,
      }),
    ).toBe('refuse_collision');
  });

  it('refuses to retire a different derived legacy wallet that still holds value', () => {
    expect(
      decideWalletReenrollmentAfterRestore({
        serverAlgorandAddress,
        restoredAlgorandAddress: 'VALUED_LEGACY_ADDRESS',
        legacyAddressWithValue: 'VALUED_LEGACY_ADDRESS',
        reenrollmentOffered: true,
      }),
    ).toBe('refuse_collision');
  });
});

describe('selectLegacyAddressForServer', () => {
  it('reuses a reproducible server wallet even when it is empty', () => {
    expect(
      selectLegacyAddressForServer(
        'SAME_LEGACY_ADDRESS',
        'SAME_LEGACY_ADDRESS',
        null,
      ),
    ).toBe('SAME_LEGACY_ADDRESS');
  });

  it('does not treat a different empty legacy derivation as the server wallet', () => {
    expect(
      selectLegacyAddressForServer(
        'SERVER_ADDRESS',
        'DIFFERENT_EMPTY_LEGACY_ADDRESS',
        null,
      ),
    ).toBeNull();
  });
});

describe('selectRestoredAddressForCollision', () => {
  it('accepts an existing V2 wallet immediately when it matches the server', () => {
    expect(selectRestoredAddressForCollision({
      serverAlgorandAddress: 'SERVER',
      existingV2Address: 'SERVER',
      selectedLegacyAddress: null,
      derivedLegacyAddress: 'DIFFERENT_V1',
      reenrollmentOffered: false,
    })).toBe('SERVER');
  });

  it('uses an existing mismatching V2 wallet only as an authorized repair candidate', () => {
    expect(selectRestoredAddressForCollision({
      serverAlgorandAddress: 'SERVER_V1',
      existingV2Address: 'LOCAL_V2',
      selectedLegacyAddress: 'SERVER_V1',
      derivedLegacyAddress: 'SERVER_V1',
      reenrollmentOffered: true,
    })).toBe('LOCAL_V2');
  });

  it('keeps a reproducible V1 wallet when V2 replacement is not authorized', () => {
    expect(selectRestoredAddressForCollision({
      serverAlgorandAddress: 'SERVER_V1',
      existingV2Address: 'STRAY_V2',
      selectedLegacyAddress: 'SERVER_V1',
      derivedLegacyAddress: 'SERVER_V1',
      reenrollmentOffered: false,
    })).toBe('SERVER_V1');
  });

  it('reuses the read-only V1 derivation without invoking stateful restoration', () => {
    expect(selectRestoredAddressForCollision({
      serverAlgorandAddress: 'OPAQUE_SERVER',
      existingV2Address: null,
      selectedLegacyAddress: null,
      derivedLegacyAddress: 'EMPTY_DERIVED_V1',
      reenrollmentOffered: true,
    })).toBe('EMPTY_DERIVED_V1');
  });
});
