// Solana wallet — a V2 sibling of the Algorand and EVM wallets.
//
// The 32-byte Ed25519 seed is derived directly from the wallet master secret
// with a Solana-specific HKDF domain. No mnemonic or additional secret is
// introduced, so restoring the existing master secret restores this address.

import { hkdf } from '@noble/hashes/hkdf';
import { sha256 } from '@noble/hashes/sha256';
import { utf8ToBytes, bytesToHex } from '@noble/hashes/utils';
import * as nacl from 'tweetnacl';

const MASTER_SECRET_BYTES = 32;
const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

export interface DerivedSolanaWallet {
  address: string;
  seedHex: string;
  publicKey: Uint8Array;
}

/** Encode bytes using Bitcoin/Solana base58 without relying on Node Buffer. */
export function base58Encode(bytes: Uint8Array): string {
  if (bytes.length === 0) return '';

  const digits: number[] = [0];
  for (const byte of bytes) {
    let carry = byte;
    for (let i = 0; i < digits.length; i++) {
      carry += digits[i] << 8;
      digits[i] = carry % 58;
      carry = Math.floor(carry / 58);
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = Math.floor(carry / 58);
    }
  }

  let out = '';
  for (let i = 0; i < bytes.length - 1 && bytes[i] === 0; i++) {
    out += BASE58_ALPHABET[0];
  }
  for (let i = digits.length - 1; i >= 0; i--) {
    out += BASE58_ALPHABET[digits[i]];
  }
  return out;
}

/** Strict inverse used to bind prepared sponsor and blockhash values. */
export function base58Decode(value: string): Uint8Array {
  if (!value) return new Uint8Array();
  const bytes: number[] = [0];
  for (const char of value) {
    const digit = BASE58_ALPHABET.indexOf(char);
    if (digit < 0) throw new Error('[Solana] Invalid base58 value.');
    let carry = digit;
    for (let i = 0; i < bytes.length; i++) {
      carry += bytes[i] * 58;
      bytes[i] = carry & 0xff;
      carry = Math.floor(carry / 256);
    }
    while (carry > 0) {
      bytes.push(carry & 0xff);
      carry = Math.floor(carry / 256);
    }
  }
  let leadingZeroes = 0;
  while (leadingZeroes < value.length - 1 && value[leadingZeroes] === '1') {
    leadingZeroes++;
  }
  const out = new Uint8Array(leadingZeroes + bytes.length);
  for (let i = 0; i < bytes.length; i++) {
    out[out.length - 1 - i] = bytes[i];
  }
  return out;
}

/**
 * Derive the Solana Ed25519 wallet for an account context from the V2 master
 * secret. The account salt grammar intentionally matches the existing
 * Algorand/EVM siblings; the info domain makes the resulting key independent.
 */
export function deriveSolanaKeyFromMasterSecret(
  masterSecret: Uint8Array,
  opts: { accountType: string; accountIndex: number; businessId?: string },
): DerivedSolanaWallet {
  if (masterSecret?.length !== MASTER_SECRET_BYTES) {
    throw new Error(
      `[Solana] Refusing to derive from a ${masterSecret?.length ?? 'missing'}-byte secret; expected ${MASTER_SECRET_BYTES}.`,
    );
  }

  const saltInput = opts.businessId
    ? `confio_v2_salt_${opts.accountType}_${opts.businessId}_${opts.accountIndex}`
    : `confio_v2_salt_${opts.accountType}_${opts.accountIndex}`;
  const salt = sha256(utf8ToBytes(saltInput));
  const info = utf8ToBytes(`confio|v2|solana|${saltInput}`);
  const seed = hkdf(sha256, masterSecret, salt, info, 32);
  const keyPair = nacl.sign.keyPair.fromSeed(seed);

  return {
    address: base58Encode(keyPair.publicKey),
    seedHex: bytesToHex(seed),
    publicKey: keyPair.publicKey,
  };
}
