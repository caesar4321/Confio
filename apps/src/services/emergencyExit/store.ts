// Keychain-backed KV adapter for the emergency exit's persisted state
// (outage window start, cooloff request times, per-chain checkpoints).
//
// Kept in its own file so every other emergencyExit module stays free of
// react-native imports and jest-testable. Values are small strings; they
// ride the existing credentialStorage (react-native-keychain) rather than
// any new storage dependency (house rule: keychain, never AsyncStorage).

import { credentialStorage } from '../credentialStorage';
import type { KVStore } from './reachability';

const enc = new TextEncoder();
const dec = new TextDecoder();

export const emergencyStore: KVStore = {
  async get(key: string): Promise<string | null> {
    try {
      const bytes = await credentialStorage.retrieveSecret(key);
      return bytes ? dec.decode(bytes) : null;
    } catch {
      return null;
    }
  },
  async set(key: string, value: string): Promise<void> {
    await credentialStorage.storeSecret(key, enc.encode(value));
  },
  async del(key: string): Promise<void> {
    try {
      await credentialStorage.deleteSecret(key);
    } catch { /* absent is fine */ }
  },
};
