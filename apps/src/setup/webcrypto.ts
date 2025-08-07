// WebCrypto setup - MUST be imported before any Web3Auth modules
import 'react-native-get-random-values';
import webcrypto from 'react-native-webcrypto';

// Some libs expect `self` and `window` to exist (web-like env)
(global as any).self = global;
(global as any).window = global;

// Debug what webcrypto provides
console.log('[webcrypto setup] webcrypto keys:', Object.keys(webcrypto || {}));
console.log('[webcrypto setup] webcrypto.subtle:', typeof webcrypto?.subtle);

// Set up crypto once - do NOT wrap or mutate
if (!(global as any).crypto) {
  // The webcrypto module is the crypto object itself
  (global as any).crypto = webcrypto;
}

// If subtle is not available directly, check if it's on the webcrypto object
if (!(global as any).crypto.subtle && webcrypto.subtle) {
  (global as any).crypto.subtle = webcrypto.subtle;
}

// Freeze to prevent later overrides
Object.freeze((global as any).crypto.subtle);

// Verify WebCrypto is available
console.log('[webcrypto setup] has crypto:', !!global.crypto);
console.log('[webcrypto setup] has subtle:', !!global.crypto?.subtle);
console.log('[webcrypto setup] subtle.digest type:', typeof global.crypto?.subtle?.digest);

// Test WebCrypto functionality
(async () => {
  try {
    const testData = new Uint8Array([1, 2, 3]);
    const out = await global.crypto?.subtle?.digest('SHA-512', testData);
    console.log('[webcrypto setup] SHA-512 works:', out instanceof ArrayBuffer);
  } catch (e) {
    console.log('[webcrypto setup] SHA-512 failed:', e);
  }
})();