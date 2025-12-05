// Lightweight replacement for Sui's generateRandomness using built-in crypto
export function generateRandomness(byteLength = 64): Uint8Array {
  const bytes = new Uint8Array(byteLength);
  const cryptoRef = globalThis.crypto as Crypto | undefined;

  if (cryptoRef?.getRandomValues) {
    cryptoRef.getRandomValues(bytes);
    return bytes;
  }

  try {
    // Fallback for environments without window.crypto (should rarely run in RN)
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { randomFillSync } = require('crypto');
    return randomFillSync(bytes);
  } catch {
    throw new Error('No secure random source available');
  }
}
