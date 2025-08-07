/**
 * Crypto shim for React Native - provides Node-style crypto.webcrypto
 * This ensures libraries that do require('crypto').webcrypto get our polyfill
 */

// Get the global crypto that bootstrapCrypto.ts sets up
const globalCrypto = global.crypto || globalThis.crypto;

// Also support the traditional crypto-browserify methods
const cryptoBrowserify = require('crypto-browserify');

// Create a module that combines both WebCrypto and Node crypto
const crypto = Object.assign({}, cryptoBrowserify, {
  // Expose webcrypto property for Node-style access (require('crypto').webcrypto)
  webcrypto: globalCrypto,
  
  // Also expose subtle directly for compatibility
  subtle: globalCrypto?.subtle,
  
  // Expose getRandomValues
  getRandomValues: globalCrypto?.getRandomValues
});

// Debug logging
if (__DEV__) {
  console.log('[crypto-shim] webcrypto available:', !!crypto.webcrypto);
  console.log('[crypto-shim] webcrypto.subtle available:', !!crypto.webcrypto?.subtle);
  console.log('[crypto-shim] subtle.importKey type:', typeof crypto.webcrypto?.subtle?.importKey);
}

module.exports = crypto;