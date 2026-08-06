import {
  PREPARE_SOLANA_SPONSORED_TRANSACTION,
  SPONSOR_SOLANA_TRANSACTION,
} from '../apollo/queries';
import { apolloClient } from '../apollo/client';
import * as nacl from 'tweetnacl';
import { strictBase64ToBytes, bytesToBase64 } from '../utils/encoding';
import { base58Decode } from './solanaWallet';
import { getActiveSolanaWallet } from './secureDeterministicWallet';

export interface SolanaSponsorPreparation {
  sponsorAddress: string;
  blockhash: string;
  lastValidBlockHeight: number;
  maxFeeLamports: number;
}

export interface SolanaSponsoredResult {
  signature: string;
  feeLamports: number;
}

function equalBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}

function isZeroSignature(value: Uint8Array): boolean {
  return value.every(byte => byte === 0);
}

function readShortVec(data: Uint8Array, start: number): { value: number; next: number } {
  let value = 0;
  let shift = 0;
  let cursor = start;
  for (let count = 0; count < 3; count++) {
    if (cursor >= data.length) throw new Error('Truncated Solana shortvec.');
    const byte = data[cursor++];
    value |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) {
      if (value > 0xffff) throw new Error('Solana shortvec overflow.');
      return { value, next: cursor };
    }
    shift += 7;
  }
  throw new Error('Non-canonical Solana shortvec.');
}

function seedFromHex(seedHex: string): Uint8Array {
  if (!/^[0-9a-f]{64}$/i.test(seedHex)) throw new Error('Invalid Solana seed.');
  return new Uint8Array(seedHex.match(/.{2}/g)!.map(byte => parseInt(byte, 16)));
}

/**
 * Add only the active user's signature to an already compiled legacy or v0
 * transaction. Product/Jupiter code owns instruction compilation; this shared
 * layer binds that immutable message to prepare(), preserves other signatures,
 * leaves sponsor slot zero empty, and returns relay-ready wire bytes.
 */
export async function signSolanaTransactionForSponsorship(
  transactionBase64: string,
  preparation: SolanaSponsorPreparation,
  accountContext?: { type: 'personal' | 'business'; index: number; businessId?: string },
): Promise<string> {
  const wire = strictBase64ToBytes(transactionBase64);
  if (wire.length === 0 || wire.length > 1232) throw new Error('Invalid Solana transaction size.');
  const signatureCount = readShortVec(wire, 0);
  const signaturesStart = signatureCount.next;
  const messageStart = signaturesStart + signatureCount.value * 64;
  if (signatureCount.value < 2 || messageStart >= wire.length) {
    throw new Error('Invalid Solana signature envelope.');
  }
  const message = wire.subarray(messageStart);
  const versioned = (message[0] & 0x80) !== 0;
  if (versioned && (message[0] & 0x7f) !== 0) throw new Error('Unsupported Solana message version.');
  const headerStart = versioned ? 1 : 0;
  if (headerStart + 3 >= message.length) throw new Error('Truncated Solana message header.');
  const requiredSignatures = message[headerStart];
  if (requiredSignatures !== signatureCount.value) {
    throw new Error('Solana signature count does not match the message header.');
  }
  const accountCount = readShortVec(message, headerStart + 3);
  const accountKeysStart = accountCount.next;
  const blockhashStart = accountKeysStart + accountCount.value * 32;
  if (requiredSignatures > accountCount.value || blockhashStart + 32 > message.length) {
    throw new Error('Truncated Solana account keys or blockhash.');
  }

  const sponsorKey = base58Decode(preparation.sponsorAddress);
  const preparedBlockhash = base58Decode(preparation.blockhash);
  if (sponsorKey.length !== 32 || preparedBlockhash.length !== 32) {
    throw new Error('Invalid sponsor preparation.');
  }
  if (!equalBytes(message.subarray(accountKeysStart, accountKeysStart + 32), sponsorKey)) {
    throw new Error('Prepared sponsor is not the transaction fee payer.');
  }
  if (!equalBytes(message.subarray(blockhashStart, blockhashStart + 32), preparedBlockhash)) {
    throw new Error('Prepared blockhash is not bound into the transaction.');
  }
  if (!isZeroSignature(wire.subarray(signaturesStart, signaturesStart + 64))) {
    throw new Error('Sponsor signature slot must be empty.');
  }

  const wallet = await getActiveSolanaWallet(accountContext);
  let userIndex = -1;
  for (let index = 1; index < requiredSignatures; index++) {
    const keyStart = accountKeysStart + index * 32;
    if (equalBytes(message.subarray(keyStart, keyStart + 32), wallet.publicKey)) {
      userIndex = index;
      break;
    }
  }
  if (userIndex < 1) throw new Error('Active Solana wallet is not a required signer.');

  for (let index = 1; index < requiredSignatures; index++) {
    if (index === userIndex) continue;
    const signatureStart = signaturesStart + index * 64;
    const signature = wire.subarray(signatureStart, signatureStart + 64);
    const keyStart = accountKeysStart + index * 32;
    if (
      isZeroSignature(signature) ||
      !nacl.sign.detached.verify(
        message,
        signature,
        message.subarray(keyStart, keyStart + 32),
      )
    ) {
      throw new Error('A required co-signer signature is missing or invalid.');
    }
  }

  const keyPair = nacl.sign.keyPair.fromSeed(seedFromHex(wallet.seedHex));
  const userSignature = nacl.sign.detached(message, keyPair.secretKey);
  wire.set(userSignature, signaturesStart + userIndex * 64);
  return bytesToBase64(wire);
}

export async function signAndSponsorSolanaTransaction(
  transactionBase64: string,
  preparation: SolanaSponsorPreparation,
  accountContext?: { type: 'personal' | 'business'; index: number; businessId?: string },
): Promise<SolanaSponsoredResult> {
  const signed = await signSolanaTransactionForSponsorship(
    transactionBase64,
    preparation,
    accountContext,
  );
  return sponsorSolanaTransaction(signed);
}

/** Fetch the generic fee payer and freshness boundary used to compile a tx. */
export async function prepareSolanaSponsoredTransaction(): Promise<SolanaSponsorPreparation> {
  const { data } = await apolloClient.mutate({
    mutation: PREPARE_SOLANA_SPONSORED_TRANSACTION,
  });
  const result = data?.prepareSolanaSponsoredTransaction;
  if (!result?.success) {
    throw new Error(`Solana sponsorship prepare failed: ${result?.error || 'unknown'}`);
  }
  return {
    sponsorAddress: result.sponsorAddress,
    blockhash: result.blockhash,
    lastValidBlockHeight: Number(result.lastValidBlockHeight),
    maxFeeLamports: Number(result.maxFeeLamports),
  };
}

/** Submit one user-partially-signed legacy or v0 transaction to the relay. */
export async function sponsorSolanaTransaction(
  transactionBase64: string,
): Promise<SolanaSponsoredResult> {
  const { data } = await apolloClient.mutate({
    mutation: SPONSOR_SOLANA_TRANSACTION,
    variables: { transaction: transactionBase64 },
  });
  const result = data?.sponsorSolanaTransaction;
  if (!result?.success) {
    throw new Error(`Solana sponsorship rejected: ${result?.error || 'unknown'}`);
  }
  return {
    signature: result.signature,
    feeLamports: Number(result.feeLamports),
  };
}
