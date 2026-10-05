// Minimal async key/value store the emergency-exit modules persist through
// (checkpoints, ban signal, account roster). The app binds it to the keychain
// (store.ts); tests use an in-memory map.

export interface KVStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  del(key: string): Promise<void>;
}
