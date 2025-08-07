// polyfills.ts - Must be imported before anything else
// Order matters!

console.log('[polyfills] Starting polyfills setup...');

// FIRST: URL polyfill for algosdk compatibility
import 'react-native-url-polyfill/auto';

// Add missing URL parsing utilities that algosdk expects
if (!(global as any).TextDecoder) {
  (global as any).TextDecoder = class TextDecoder {
    decode(bytes: any) {
      if (!bytes) return '';
      return String.fromCharCode.apply(null, new Uint8Array(bytes));
    }
  };
}

if (!(global as any).TextEncoder) {
  (global as any).TextEncoder = class TextEncoder {
    encode(str: string) {
      const buf = new Uint8Array(str.length);
      for (let i = 0; i < str.length; i++) {
        buf[i] = str.charCodeAt(i);
      }
      return buf;
    }
  };
}

console.log('[polyfills] URL polyfill and TextDecoder/TextEncoder loaded');

import { Buffer } from 'buffer';
global.Buffer = global.Buffer ?? Buffer;
console.log('[polyfills] Buffer setup complete');

// Full WebCrypto (has AES-GCM & HMAC) from react-native-quick-crypto
console.log('[polyfills] Installing react-native-quick-crypto...');
import { install } from 'react-native-quick-crypto';
try {
  install();
  console.log('[polyfills] react-native-quick-crypto installed successfully');
} catch (error) {
  console.error('[polyfills] Failed to install react-native-quick-crypto:', error);
  // Fall back to previous crypto setup
  console.log('[polyfills] Falling back to manual crypto setup...');
}

// Hermes <0.72 lacks TypedArray.slice
if (!Uint8Array.prototype.slice) {
  // eslint-disable-next-line no-extend-native
  Uint8Array.prototype.slice = function (start?: number, end?: number) {
    const len = this.length;
    const s = start == null ? 0 : (start < 0 ? Math.max(len + start, 0) : Math.min(start, len));
    const e = end   == null ? len : (end   < 0 ? Math.max(len + end,   0) : Math.min(end, len));
    const out = new Uint8Array(Math.max(e - s, 0));
    for (let i = 0; i < out.length; i++) out[i] = this[s + i];
    return out;
  };
}

// Also add ArrayBuffer.prototype.slice if missing (needed by algosdk)
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
}

// Setup globals for libraries that expect browser/Node environment
(global as any).window = (global as any).window || global;
(global as any).self = (global as any).self || global;

// Process shim for Node libraries
if (!(global as any).process) {
  (global as any).process = {
    env: {},
    version: 'v16.0.0',
    browser: false
  };
}

// Import other required polyfills (URL already imported above)
import 'text-encoding-polyfill';
import { encode as btoa, decode as atob } from 'base-64';

if (!(global as any).btoa) (global as any).btoa = btoa;
if (!(global as any).atob) (global as any).atob = atob;

// Sanity check and punycode compatibility fix
try {
  const punycode = require('punycode');
  console.log('[polyfills] punycode loaded with keys:', Object.keys(punycode));
  
  // Fix punycode compatibility - react-native-url-polyfill expects punycode.ucs2.decode
  // but the actual module has ucs2decode as a direct function
  if (!punycode.ucs2 && punycode.ucs2decode) {
    punycode.ucs2 = {
      decode: punycode.ucs2decode,
      encode: punycode.ucs2encode
    };
    console.log('[polyfills] Fixed punycode.ucs2 compatibility');
  }
  
  console.log('[polyfills] puny?', typeof punycode?.ucs2?.decode); // Should now be 'function'
  
  if (punycode?.ucs2?.decode) {
    console.log('[polyfills] URL ok?', new URL('https://a.com').hostname); // Should be 'a.com'
    
    console.log(
      '[polyfills ready]',
      'URL→', new URL('https://a.com').hostname,
      'slice→', typeof Uint8Array.prototype.slice,
      'decrypt→', typeof global.crypto?.subtle?.decrypt,
    );
  } else {
    console.error('[polyfills] punycode.ucs2.decode still not available after fix');
  }
} catch (error) {
  console.error('[polyfills] Sanity check failed:', error);
}

export {};