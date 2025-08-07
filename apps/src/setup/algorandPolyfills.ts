// algorandPolyfills.ts - Polyfills specifically for Algorand SDK compatibility
import 'react-native-get-random-values';
import { Buffer } from 'buffer';

// Set up Buffer globally
global.Buffer = Buffer;
(global as any).process = (global as any).process || {};
(global as any).process.browser = false;
(global as any).process.env = (global as any).process.env || {};
(global as any).process.version = 'v16.0.0'; // Mock Node version

// URL should be available in React Native, but add a basic polyfill if missing
if (typeof URL === 'undefined') {
  try {
    // Try to use React Native's URL if available
    const { URL: RNUrl } = require('react-native-url-polyfill');
    (global as any).URL = RNUrl;
  } catch (e) {
    // Basic URL polyfill for Algorand needs
    (global as any).URL = class URL {
      href: string;
      protocol: string;
      hostname: string;
      port: string;
      pathname: string;
      
      constructor(url: string, base?: string) {
        this.href = base ? base + url : url;
        const match = this.href.match(/^(https?:)\/\/([^:/]+)(:\d+)?(.*)/);
        if (match) {
          this.protocol = match[1];
          this.hostname = match[2];
          this.port = match[3] ? match[3].substring(1) : '';
          this.pathname = match[4] || '/';
        } else {
          this.protocol = 'https:';
          this.hostname = 'localhost';
          this.port = '';
          this.pathname = '/';
        }
      }
      
      toString() {
        return this.href;
      }
    };
    console.log('[algorandPolyfills] Added basic URL polyfill');
  }
}

// Add ArrayBuffer.prototype.slice if missing (needed by algosdk)
if (!ArrayBuffer.prototype.slice) {
  ArrayBuffer.prototype.slice = function(start: number, end?: number) {
    const len = this.byteLength;
    const actualStart = start < 0 ? Math.max(len + start, 0) : Math.min(start, len);
    const actualEnd = end === undefined ? len : (end < 0 ? Math.max(len + end, 0) : Math.min(end, len));
    const actualLength = Math.max(actualEnd - actualStart, 0);
    
    const result = new ArrayBuffer(actualLength);
    const sourceView = new Uint8Array(this, actualStart, actualLength);
    const targetView = new Uint8Array(result);
    targetView.set(sourceView);
    
    return result;
  };
  console.log('[algorandPolyfills] Added ArrayBuffer.prototype.slice polyfill');
}

// Ensure crypto.getRandomValues is available
if (!globalThis.crypto) {
  globalThis.crypto = {} as any;
}

// Force import react-native-get-random-values which patches global.crypto
require('react-native-get-random-values');

// If still not available, manually add it
if (!globalThis.crypto.getRandomValues) {
  const rnGetRandomValues = require('react-native-get-random-values');
  if (rnGetRandomValues.getRandomValues) {
    globalThis.crypto.getRandomValues = rnGetRandomValues.getRandomValues;
    console.log('[algorandPolyfills] Manually added getRandomValues to globalThis.crypto');
  } else if (global.crypto && global.crypto.getRandomValues) {
    // Copy from global.crypto if it exists there
    globalThis.crypto.getRandomValues = global.crypto.getRandomValues;
    console.log('[algorandPolyfills] Copied getRandomValues from global.crypto');
  }
}

// Add subtle crypto if missing
if (!globalThis.crypto.subtle) {
  globalThis.crypto.subtle = {
    digest: async (algorithm: string, data: ArrayBuffer) => {
      const { sha256 } = require('@noble/hashes/sha256');
      const { sha512 } = require('@noble/hashes/sha512');
      
      const algo = typeof algorithm === 'string' ? algorithm : (algorithm as any).name;
      const normalizedAlgo = algo.toLowerCase().replace('-', '');
      
      let dataBytes;
      if (data instanceof ArrayBuffer) {
        dataBytes = new Uint8Array(data);
      } else if (data instanceof Uint8Array) {
        dataBytes = data;
      } else {
        throw new Error('Data must be ArrayBuffer or Uint8Array');
      }
      
      let hash;
      if (normalizedAlgo === 'sha256') {
        hash = sha256(dataBytes);
      } else if (normalizedAlgo === 'sha512') {
        hash = sha512(dataBytes);
      } else {
        throw new Error(`Unsupported algorithm: ${algo}`);
      }
      
      return hash.buffer;
    },
    importKey: async (format: any, keyData: any, algorithm: any, extractable: any, keyUsages: any) => {
      // Return a mock CryptoKey for Algorand
      return {
        type: 'secret',
        extractable,
        algorithm,
        usages: keyUsages,
        _keyData: keyData instanceof ArrayBuffer ? new Uint8Array(keyData) : keyData
      };
    },
    sign: async () => {
      throw new Error('Sign not implemented in polyfill');
    },
    verify: async () => {
      throw new Error('Verify not implemented in polyfill');
    }
  } as any;
  console.log('[algorandPolyfills] Added subtle crypto polyfill');
}

// Add TextEncoder/TextDecoder if missing
if (typeof TextEncoder === 'undefined') {
  (global as any).TextEncoder = class TextEncoder {
    encode(str: string): Uint8Array {
      return Buffer.from(str, 'utf-8');
    }
  };
  console.log('[algorandPolyfills] Added TextEncoder polyfill');
}

if (typeof TextDecoder === 'undefined') {
  (global as any).TextDecoder = class TextDecoder {
    decode(bytes: Uint8Array): string {
      return Buffer.from(bytes).toString('utf-8');
    }
  };
  console.log('[algorandPolyfills] Added TextDecoder polyfill');
}

// Add performance.now if missing (needed by some crypto libraries)
if (typeof performance === 'undefined') {
  (global as any).performance = {
    now: () => Date.now()
  };
}

// Verify setup
console.log('[algorandPolyfills] Setup complete:');
console.log('[algorandPolyfills] - globalThis.crypto exists:', !!globalThis.crypto);
console.log('[algorandPolyfills] - globalThis.crypto.getRandomValues exists:', !!globalThis.crypto.getRandomValues);
console.log('[algorandPolyfills] - globalThis.crypto.subtle exists:', !!globalThis.crypto.subtle);
console.log('[algorandPolyfills] - Buffer exists:', !!global.Buffer);
console.log('[algorandPolyfills] - TextEncoder exists:', typeof TextEncoder !== 'undefined');
console.log('[algorandPolyfills] - TextDecoder exists:', typeof TextDecoder !== 'undefined');

// Test getRandomValues
try {
  const testArray = new Uint8Array(16);
  globalThis.crypto.getRandomValues(testArray);
  console.log('[algorandPolyfills] getRandomValues test: SUCCESS');
} catch (e) {
  console.error('[algorandPolyfills] getRandomValues test: FAILED', e);
}

export {};