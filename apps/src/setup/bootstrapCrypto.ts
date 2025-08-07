// bootstrapCrypto.ts - Robust WebCrypto setup that can't be overwritten
import 'react-native-get-random-values';
import webcrypto from 'react-native-webcrypto';

// Ensure window/self exist in React Native
(global as any).window = (global as any).window || global;
(global as any).self = (global as any).self || global;

// Store the original webcrypto references
const originalWebcrypto = webcrypto;
const originalSubtle = webcrypto.subtle || (webcrypto as any).crypto?.subtle;

console.log('[bootstrapCrypto] Original subtle:', typeof originalSubtle);
console.log('[bootstrapCrypto] Starting crypto setup...');

// Patch importKey on the original subtle to handle ArrayBufferView
if (originalSubtle && typeof originalSubtle.importKey === 'function') {
  const realImportKey = originalSubtle.importKey.bind(originalSubtle);
  (originalSubtle as any).importKey = async function(
    format: any, 
    keyData: any, 
    algorithm: any, 
    extractable: any, 
    keyUsages: any
  ) {
    console.log('[bootstrapCrypto] importKey wrapper called, keyData type:', keyData?.constructor?.name);
    
    // Store original keyData for HMAC operations
    let originalKeyData = keyData;
    
    // Convert Uint8Array or other ArrayBufferView to ArrayBuffer
    if (keyData && ArrayBuffer.isView(keyData)) {
      const view = new Uint8Array(keyData.buffer, keyData.byteOffset, keyData.byteLength);
      originalKeyData = new Uint8Array(view); // Store a copy
      keyData = view.slice().buffer;
      console.log('[bootstrapCrypto] Converted ArrayBufferView to ArrayBuffer');
    }
    
    // Handle string keys (defensive)
    if (typeof keyData === 'string') {
      originalKeyData = new TextEncoder().encode(keyData);
      keyData = originalKeyData.buffer;
      console.log('[bootstrapCrypto] Converted string to ArrayBuffer');
    }
    
    // If keyData is already ArrayBuffer, create Uint8Array view
    if (keyData instanceof ArrayBuffer && !(originalKeyData instanceof Uint8Array)) {
      originalKeyData = new Uint8Array(keyData);
    }
    
    const key = await realImportKey(format, keyData, algorithm, extractable, keyUsages);
    
    // Store key data on the CryptoKey for HMAC operations
    if (algorithm.name === 'HMAC' && originalKeyData) {
      (key as any)._keyData = originalKeyData;
    }
    
    return key;
  };
  console.log('[bootstrapCrypto] importKey wrapper installed');
}

// Add missing digest method if needed
if (originalSubtle && !originalSubtle.digest) {
  console.log('[bootstrapCrypto] Adding digest fallback');
  const { sha256 } = require('@noble/hashes/sha256');
  const { sha512 } = require('@noble/hashes/sha512');
  
  (originalSubtle as any).digest = async function(algorithm: any, data: any) {
    const algo = typeof algorithm === 'string' ? algorithm : algorithm.name;
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
  };
}

// Add sign method if missing
if (originalSubtle && !originalSubtle.sign) {
  console.log('[bootstrapCrypto] Adding sign fallback');
  const { hmac } = require('@noble/hashes/hmac');
  const { sha256 } = require('@noble/hashes/sha256');
  const { sha512 } = require('@noble/hashes/sha512');
  
  (originalSubtle as any).sign = async function(algorithm: any, key: any, data: any) {
    // For HMAC operations which Web3Auth needs
    if (algorithm.name === 'HMAC' || (typeof algorithm === 'string' && algorithm === 'HMAC')) {
      // Get the key data from the CryptoKey
      if (!key._keyData) {
        throw new Error('Invalid key - missing key data');
      }
      
      let dataBytes;
      if (data instanceof ArrayBuffer) {
        dataBytes = new Uint8Array(data);
      } else if (data instanceof Uint8Array) {
        dataBytes = data;
      } else {
        throw new Error('Data must be ArrayBuffer or Uint8Array');
      }
      
      // Determine hash function based on key algorithm
      const hashFunc = key.algorithm?.hash?.name === 'SHA-512' ? sha512 : sha256;
      
      // Compute HMAC
      const signature = hmac(hashFunc, key._keyData, dataBytes);
      return signature.buffer;
    }
    throw new Error(`Unsupported sign algorithm: ${algorithm.name || algorithm}`);
  };
}

// Add verify method if missing
if (originalSubtle && !originalSubtle.verify) {
  console.log('[bootstrapCrypto] Adding verify fallback');
  const { hmac } = require('@noble/hashes/hmac');
  const { sha256 } = require('@noble/hashes/sha256');
  const { sha512 } = require('@noble/hashes/sha512');
  
  (originalSubtle as any).verify = async function(algorithm: any, key: any, signature: any, data: any) {
    // For HMAC operations
    if (algorithm.name === 'HMAC' || (typeof algorithm === 'string' && algorithm === 'HMAC')) {
      // Get the key data from the CryptoKey
      if (!key._keyData) {
        throw new Error('Invalid key - missing key data');
      }
      
      let dataBytes;
      if (data instanceof ArrayBuffer) {
        dataBytes = new Uint8Array(data);
      } else if (data instanceof Uint8Array) {
        dataBytes = data;
      } else {
        throw new Error('Data must be ArrayBuffer or Uint8Array');
      }
      
      let sigBytes;
      if (signature instanceof ArrayBuffer) {
        sigBytes = new Uint8Array(signature);
      } else if (signature instanceof Uint8Array) {
        sigBytes = signature;
      } else {
        throw new Error('Signature must be ArrayBuffer or Uint8Array');
      }
      
      // Determine hash function based on key algorithm
      const hashFunc = key.algorithm?.hash?.name === 'SHA-512' ? sha512 : sha256;
      
      // Compute HMAC and compare
      const expectedSig = hmac(hashFunc, key._keyData, dataBytes);
      
      // Constant-time comparison
      if (sigBytes.length !== expectedSig.length) return false;
      let equal = true;
      for (let i = 0; i < sigBytes.length; i++) {
        equal = equal && sigBytes[i] === expectedSig[i];
      }
      return equal;
    }
    throw new Error(`Unsupported verify algorithm: ${algorithm.name || algorithm}`);
  };
}

// Create a subtle proxy with visible tracing (or a stub if originalSubtle doesn't exist)
const subtleProxy = originalSubtle ? new Proxy(originalSubtle, {
  get(target, prop, receiver) {
    const value = Reflect.get(target, prop, receiver);
    if (typeof value === 'function') {
      return (...args: any[]) => {
        if (__DEV__ && (prop === 'importKey' || prop === 'digest' || prop === 'sign' || prop === 'verify')) {
          console.log(`[bootstrapCrypto] subtle.${String(prop)} called`);
        }
        return value.apply(target, args);
      };
    }
    return value;
  },
}) : {
  // Create a minimal stub if originalSubtle doesn't exist
  digest: async (algorithm: any, data: any) => {
    console.warn('[bootstrapCrypto] Using fallback digest (no native subtle)');
    const { sha256 } = require('@noble/hashes/sha256');
    const { sha512 } = require('@noble/hashes/sha512');
    const algo = typeof algorithm === 'string' ? algorithm : algorithm.name;
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
    console.warn('[bootstrapCrypto] Using fallback importKey (no native subtle)');
    // Return a mock CryptoKey
    return {
      type: 'secret',
      extractable,
      algorithm,
      usages: keyUsages,
      _keyData: keyData instanceof ArrayBuffer ? new Uint8Array(keyData) : keyData
    };
  },
  sign: async (algorithm: any, key: any, data: any) => {
    console.warn('[bootstrapCrypto] Using fallback sign (no native subtle)');
    throw new Error('Sign not implemented in fallback');
  },
  verify: async (algorithm: any, key: any, signature: any, data: any) => {
    console.warn('[bootstrapCrypto] Using fallback verify (no native subtle)');
    throw new Error('Verify not implemented in fallback');
  }
};

// Create a crypto proxy that:
// - always returns a live subtle (can't be nulled out)
// - exposes crypto.webcrypto for Node-style callers
// - ignores attempts to assign crypto.subtle = ...
const cryptoProxy: any = new Proxy(
  {},
  {
    get(_target, prop) {
      if (prop === 'subtle') return subtleProxy;
      if (prop === 'getRandomValues') {
        // Try multiple sources for getRandomValues
        const getRandomValues = originalWebcrypto?.getRandomValues?.bind(originalWebcrypto) || 
                                require('react-native-get-random-values').getRandomValues ||
                                global.crypto?.getRandomValues;
        if (!getRandomValues) {
          console.error('[bootstrapCrypto] getRandomValues not found!');
        }
        return getRandomValues;
      }
      if (prop === 'webcrypto') return cryptoProxy; // Node-style: require('crypto').webcrypto
      return (originalWebcrypto as any)[prop];
    },
    set(_target, prop, _value) {
      if (prop === 'subtle' || prop === 'webcrypto') {
        if (__DEV__) console.warn(`[bootstrapCrypto] Ignored attempt to set crypto.${String(prop)}`);
        return true;
      }
      return true;
    },
  }
);

// Function to lock crypto on a target object
const lockCrypto = (target: any) => {
  try {
    Object.defineProperty(target, 'crypto', {
      configurable: true,
      enumerable: true,
      get: () => cryptoProxy,
      set: () => {
        if (__DEV__) {
          console.warn('[bootstrapCrypto] Ignored attempt to overwrite global.crypto');
        }
      },
    });
    console.log(`[bootstrapCrypto] Locked crypto on`, target.constructor?.name || target);
  } catch (e) {
    // If we can't lock it, at least set it
    target.crypto = cryptoProxy;
    console.log(`[bootstrapCrypto] Set crypto on`, target.constructor?.name || target);
  }
};

// Lock crypto on all global entry points
lockCrypto(globalThis);
lockCrypto(global);
if ((global as any).window) {
  lockCrypto((global as any).window);
}
if ((global as any).self) {
  lockCrypto((global as any).self);
}

// Final verification
console.log('[bootstrapCrypto] Setup complete:');
console.log('[bootstrapCrypto] - global.crypto exists:', !!global.crypto);
console.log('[bootstrapCrypto] - global.crypto.subtle exists:', !!global.crypto?.subtle);
console.log('[bootstrapCrypto] - global.crypto.getRandomValues exists:', !!global.crypto?.getRandomValues);
console.log('[bootstrapCrypto] - globalThis.crypto.getRandomValues exists:', !!globalThis.crypto?.getRandomValues);
console.log('[bootstrapCrypto] - crypto.subtle.digest type:', typeof global.crypto?.subtle?.digest);
console.log('[bootstrapCrypto] - crypto.subtle.importKey type:', typeof global.crypto?.subtle?.importKey);
console.log('[bootstrapCrypto] - crypto.webcrypto exists:', !!global.crypto?.webcrypto);
console.log('[bootstrapCrypto] - crypto.webcrypto.subtle exists:', !!global.crypto?.webcrypto?.subtle);

// Check Node-style path (may fail in React Native)
try {
  const nodeCrypto = require('crypto');
  console.log('[bootstrapCrypto] - require("crypto").webcrypto exists:', !!nodeCrypto.webcrypto);
  console.log('[bootstrapCrypto] - require("crypto").webcrypto.subtle exists:', !!nodeCrypto.webcrypto?.subtle);
} catch (e) {
  // This is expected in React Native
  console.log('[bootstrapCrypto] - require("crypto") not available (expected in React Native)');
}

// Ensure getRandomValues is available as a direct function if needed
if (!globalThis.crypto?.getRandomValues) {
  console.log('[bootstrapCrypto] Adding getRandomValues to globalThis.crypto');
  try {
    const { getRandomValues } = require('react-native-get-random-values');
    if (globalThis.crypto) {
      (globalThis.crypto as any).getRandomValues = getRandomValues;
    }
  } catch (e) {
    console.error('[bootstrapCrypto] Failed to add getRandomValues:', e);
  }
}

// Export for debugging
export { originalSubtle, cryptoProxy };