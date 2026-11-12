// A real module object (not auto-mocked functions on a frozen namespace), so
// the observer patches it the way it patches the library in the app.
jest.mock('react-native-keychain', () => {
  const disk: { value: null | { username: string; password: string } } = { value: null };
  const lib: Record<string, any> = {
    __esModule: true,
    __disk: disk,
    getGenericPassword: jest.fn(async () => (disk.value ? { ...disk.value, storage: 'KeystoreAESGCM_NoAuth' } : false)),
    setGenericPassword: jest.fn(async (username: string, password: string) => {
      disk.value = { username, password };
      return true;
    }),
    resetGenericPassword: jest.fn(async () => {
      disk.value = null;
      return true;
    }),
  };
  lib.default = {
    getGenericPassword: lib.getGenericPassword,
    setGenericPassword: lib.setGenericPassword,
    resetGenericPassword: lib.resetGenericPassword,
  };
  return lib;
});

const SESSION = { service: 'com.confio.auth', username: 'auth_tokens' };
const tokens = (access: string) => JSON.stringify({ accessToken: access, refreshToken: 'refresh' });

type Store = typeof import('../sessionStore');
let store: Store;
let Keychain: Record<string, any>;
let rawGet: jest.Mock;
let rawSet: jest.Mock;
let rawReset: jest.Mock;

const load = (install: boolean) => {
  jest.resetModules();
  Keychain = require('react-native-keychain');
  rawGet = Keychain.getGenericPassword;
  rawSet = Keychain.setGenericPassword;
  rawReset = Keychain.resetGenericPassword;
  store = require('../sessionStore');
  if (install) store.installSessionObserver();
};

describe('sessionStore', () => {
  beforeEach(() => load(true));

  it('reads the keychain once, then answers from memory', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    const first = await store.getSessionCredentials();
    const second = await store.getSessionCredentials();
    expect(first && first.password).toBe(tokens('a1'));
    expect(second && second.password).toBe(tokens('a1'));
    expect(rawGet).toHaveBeenCalledTimes(1);
  });

  it('shares one keychain read between concurrent callers', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await Promise.all([store.getSessionCredentials(), store.getSessionCredentials(), store.getSessionCredentials()]);
    expect(rawGet).toHaveBeenCalledTimes(1);
  });

  it('a write through the library replaces the copy without another read', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    await Keychain.setGenericPassword('auth_tokens', tokens('a2'), SESSION);
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('a2'));
    expect(rawGet).toHaveBeenCalledTimes(1);
  });

  it('a write through the default export is observed too', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    await Keychain.default.setGenericPassword('auth_tokens', tokens('a3'), SESSION);
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('a3'));
  });

  it('a write to another service leaves the session copy alone', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    await Keychain.setGenericPassword('x', 'y', { service: 'com.confio.other' });
    // The fake disk holds one entry; what matters is the copy was not touched.
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('a1'));
    expect(rawGet).toHaveBeenCalledTimes(1);
  });

  it('a reset signs the copy out and tells listeners', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    const listener = jest.fn();
    const unsubscribe = store.onSessionReset(listener);
    await Keychain.resetGenericPassword({ service: 'com.confio.auth' });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(await store.getSessionCredentials()).toBe(false);
    expect(rawGet).toHaveBeenCalledTimes(1);
    unsubscribe();
    await Keychain.resetGenericPassword({ service: 'com.confio.auth' });
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it('a reset through the default export signs the copy out too', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    await Keychain.default.resetGenericPassword({ service: 'com.confio.auth' });
    expect(await store.getSessionCredentials()).toBe(false);
  });

  it('a reset overtaken by a newer write does not publish signed out', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    let releaseReset: (value: unknown) => void = () => {};
    rawReset.mockImplementationOnce(async () => {
      await new Promise((resolve) => { releaseReset = resolve; });
      return true;
    });
    const seen: unknown[] = [];
    store.onSessionReset(() => { seen.push(store.getSessionCredentials()); });
    const reset = Keychain.resetGenericPassword({ service: 'com.confio.auth' });
    await Keychain.setGenericPassword('auth_tokens', tokens('next'), SESSION);
    releaseReset(undefined);
    await reset;
    const [atReset] = await Promise.all(seen);
    expect(atReset && (atReset as any).password).toBe(tokens('next'));
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('next'));
  });

  it('a write that reports failure is not remembered', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    rawSet.mockImplementationOnce(async () => false);
    await Keychain.setGenericPassword('auth_tokens', tokens('a2'), SESSION);
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('a1'));
    expect(rawGet).toHaveBeenCalledTimes(2);
  });

  it('a reset that fails still tells listeners, who re-read the keychain', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    const listener = jest.fn();
    store.onSessionReset(listener);
    rawReset.mockImplementationOnce(async () => { throw new Error('keystore busy'); });
    await expect(Keychain.resetGenericPassword({ service: 'com.confio.auth' })).rejects.toThrow('keystore busy');
    rawReset.mockImplementationOnce(async () => false);
    await Keychain.resetGenericPassword({ service: 'com.confio.auth' });
    expect(listener).toHaveBeenCalledTimes(2);
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('a1'));
    expect(rawGet).toHaveBeenCalledTimes(2);
  });

  it('overlapping writes are not remembered: the next read asks the keychain which one landed', async () => {
    let releaseFirst: (value: unknown) => void = () => {};
    rawSet.mockImplementationOnce(async (username: string, password: string) => {
      await new Promise((resolve) => { releaseFirst = resolve; });
      Keychain.__disk.value = { username, password };
      return true;
    });
    const first = Keychain.setGenericPassword('auth_tokens', tokens('first'), SESSION);
    await Keychain.setGenericPassword('auth_tokens', tokens('second'), SESSION);
    releaseFirst(undefined);
    await first;
    // The slower first write landed on the fake disk last. Memory cannot
    // know that, so it holds neither and the keychain answers.
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('first'));
    expect(rawGet).toHaveBeenCalledTimes(1);
    // Once things are quiet again a write is remembered as usual.
    await Keychain.setGenericPassword('auth_tokens', tokens('third'), SESSION);
    const settled = await store.getSessionCredentials();
    expect(settled && settled.password).toBe(tokens('third'));
    expect(rawGet).toHaveBeenCalledTimes(1);
  });

  it('a read that overlapped a write does not publish the older value', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('old') };
    let releaseRead: (value: unknown) => void = () => {};
    rawGet.mockImplementationOnce(() => new Promise((resolve) => { releaseRead = resolve; }));
    const slowRead = store.getSessionCredentials();
    await Keychain.setGenericPassword('auth_tokens', tokens('new'), SESSION);
    releaseRead({ username: 'auth_tokens', password: tokens('old') });
    await slowRead;
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('new'));
  });

  it('a caller arriving during a write does not get a read that began before it', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('old') };
    let releaseRead: (value: unknown) => void = () => {};
    rawGet.mockImplementationOnce(() => new Promise((resolve) => { releaseRead = resolve; }));
    const staleRead = store.getSessionCredentials();
    let releaseWrite: (value: unknown) => void = () => {};
    rawSet.mockImplementationOnce(async (username: string, password: string) => {
      await new Promise((resolve) => { releaseWrite = resolve; });
      Keychain.__disk.value = { username, password };
      return true;
    });
    const write = Keychain.setGenericPassword('auth_tokens', tokens('new'), SESSION);
    const during = store.getSessionCredentials();
    expect(rawGet).toHaveBeenCalledTimes(2);
    releaseRead({ username: 'auth_tokens', password: tokens('old') });
    releaseWrite(undefined);
    await Promise.all([staleRead, write, during]);
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('new'));
  });

  // protects=the account the person switched to; fails_when=a read that ran during overlapping writes is kept as the session; no_claim=native call ordering
  it('a read that finished in the middle of overlapping writes is not kept', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('personal') };
    let releaseRefresh: (value: unknown) => void = () => {};
    let releaseSwitch: (value: unknown) => void = () => {};
    rawSet.mockImplementationOnce(async (username: string, password: string) => {
      await new Promise((resolve) => { releaseRefresh = resolve; });
      Keychain.__disk.value = { username, password };
      return true;
    });
    rawSet.mockImplementationOnce(async (username: string, password: string) => {
      await new Promise((resolve) => { releaseSwitch = resolve; });
      Keychain.__disk.value = { username, password };
      return true;
    });
    const refresh = Keychain.setGenericPassword('auth_tokens', tokens('personal-refreshed'), SESSION);
    const accountSwitch = Keychain.setGenericPassword('auth_tokens', tokens('business'), SESSION);
    // A request reads now and the keychain answers before either write lands.
    const during = await store.getSessionCredentials();
    expect(during && during.password).toBe(tokens('personal'));
    releaseRefresh(undefined);
    releaseSwitch(undefined);
    await Promise.all([refresh, accountSwitch]);
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('business'));
  });

  it('a read that finished in the middle of a single write is replaced by that write', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('old') };
    let releaseWrite: (value: unknown) => void = () => {};
    rawSet.mockImplementationOnce(async (username: string, password: string) => {
      await new Promise((resolve) => { releaseWrite = resolve; });
      Keychain.__disk.value = { username, password };
      return true;
    });
    const write = Keychain.setGenericPassword('auth_tokens', tokens('new'), SESSION);
    await store.getSessionCredentials();
    releaseWrite(undefined);
    await write;
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('new'));
  });

  it('a read during a write that then fails is not kept either', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('old') };
    let failWrite: (error: Error) => void = () => {};
    rawSet.mockImplementationOnce(() => new Promise((_, reject) => { failWrite = reject; }));
    const write = Keychain.setGenericPassword('auth_tokens', tokens('new'), SESSION);
    await store.getSessionCredentials();
    const readsSoFar = rawGet.mock.calls.length;
    failWrite(new Error('keystore busy'));
    await expect(write).rejects.toThrow('keystore busy');
    await store.getSessionCredentials();
    expect(rawGet.mock.calls.length).toBe(readsSoFar + 1);
  });

  // protects=a sign-in the keychain did not really store is not treated as a session; fails_when=memory keeps a write the read-back check rejected; no_claim=why the keychain dropped it
  it('forgets the copy when a caller finds the keychain does not hold it', async () => {
    rawSet.mockImplementationOnce(async () => true);
    await Keychain.setGenericPassword('auth_tokens', tokens('never-stored'), SESSION);
    store.invalidateSessionCache();
    expect(await store.getSessionCredentials()).toBe(false);
    expect(rawGet).toHaveBeenCalledTimes(1);
  });

  it('counts the time a keychain read took to fail', async () => {
    const { getKeychainDiagnostic } = require('../keychainDiagnostic');
    rawGet.mockImplementationOnce(async () => { throw new Error('E_CRYPTO_FAILED'); });
    await expect(store.getSessionCredentials()).rejects.toThrow('E_CRYPTO_FAILED');
    expect(getKeychainDiagnostic()).toMatch(/^first=\d+;max=\d+;n=1;c=1;st=error$/);
  });

  it('a failed write leaves the copy unknown, so the next read asks the keychain', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    rawSet.mockImplementationOnce(async () => { throw new Error('keystore busy'); });
    await expect(Keychain.setGenericPassword('auth_tokens', tokens('a2'), SESSION)).rejects.toThrow('keystore busy');
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('a1'));
    expect(rawGet).toHaveBeenCalledTimes(2);
  });

  it('a write that fails after removing the old entry is announced, and a good write is not', async () => {
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    const listener = jest.fn();
    store.onSessionReset(listener);
    await Keychain.setGenericPassword('auth_tokens', tokens('a2'), SESSION);
    expect(listener).not.toHaveBeenCalled();
    // iOS replaces by delete-then-insert: the insert fails, the entry is gone.
    rawSet.mockImplementationOnce(async () => {
      Keychain.__disk.value = null;
      throw new Error('insert failed');
    });
    await expect(Keychain.setGenericPassword('auth_tokens', tokens('a3'), SESSION)).rejects.toThrow('insert failed');
    expect(listener).toHaveBeenCalledTimes(1);
    expect(await store.getSessionCredentials()).toBe(false);
  });

  it('an empty read is not remembered as signed out', async () => {
    expect(await store.getSessionCredentials()).toBe(false);
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('late') };
    const retry = await store.getSessionCredentials();
    expect(retry && retry.password).toBe(tokens('late'));
    expect(rawGet).toHaveBeenCalledTimes(2);
  });

  it('a keychain error propagates and is not cached', async () => {
    rawGet.mockImplementationOnce(async () => { throw new Error('locked'); });
    await expect(store.getSessionCredentials()).rejects.toThrow('locked');
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    const after = await store.getSessionCredentials();
    expect(after && after.password).toBe(tokens('a1'));
  });

  it('reports keystore timing only after a read, without secrets', async () => {
    const { getKeychainDiagnostic } = require('../keychainDiagnostic');
    expect(getKeychainDiagnostic()).toBeNull();
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    expect(getKeychainDiagnostic()).toMatch(/^first=\d+;max=\d+;n=1;c=1;st=KeystoreAESGCM_NoAuth$/);
  });

  it('without the observer every read goes to the keychain', async () => {
    load(false);
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    await store.getSessionCredentials();
    expect(rawGet).toHaveBeenCalledTimes(2);
  });

  it('stays off when the library cannot be observed', async () => {
    jest.resetModules();
    Keychain = require('react-native-keychain');
    rawGet = Keychain.getGenericPassword;
    Object.defineProperty(Keychain.default, 'setGenericPassword', { value: Keychain.default.setGenericPassword, writable: false });
    store = require('../sessionStore');
    store.installSessionObserver();
    Keychain.__disk.value = { username: 'auth_tokens', password: tokens('a1') };
    await store.getSessionCredentials();
    await store.getSessionCredentials();
    expect(rawGet).toHaveBeenCalledTimes(2);
  });
});
