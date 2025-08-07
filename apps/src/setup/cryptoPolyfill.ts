// cryptoPolyfill.ts - Fixes crypto module issues for Web3Auth on Android
import { Platform } from 'react-native';

console.log('[cryptoPolyfill] Setting up crypto module shim...');

// Create a crypto shim that Web3Auth can use
const cryptoShim = {
  webcrypto: global.crypto,
  getRandomValues: global.crypto?.getRandomValues?.bind(global.crypto),
  subtle: global.crypto?.subtle,
  // Add other crypto methods if needed
};

// Make crypto available for require('crypto')
if (Platform.OS === 'android') {
  // Override Module._load to intercept require('crypto')
  try {
    const Module = (global as any).Module || {};
    const originalLoad = Module._load;
    
    if (originalLoad) {
      Module._load = function(request: string, parent: any, isMain: boolean) {
        if (request === 'crypto') {
          console.log('[cryptoPolyfill] Intercepted require("crypto"), returning shim');
          return cryptoShim;
        }
        return originalLoad.apply(this, arguments);
      };
    }
    
    // Also set it on global for direct access
    (global as any).crypto_node = cryptoShim;
    
    console.log('[cryptoPolyfill] Android crypto module shim installed');
  } catch (error) {
    console.warn('[cryptoPolyfill] Could not override Module._load:', error);
    
    // Fallback: Try to override require directly
    const originalRequire = (global as any).require;
    if (originalRequire && typeof originalRequire === 'function') {
      (global as any).require = function(moduleName: string) {
        if (moduleName === 'crypto') {
          console.log('[cryptoPolyfill] Intercepted require("crypto") via fallback');
          return cryptoShim;
        }
        try {
          return originalRequire.call(this, moduleName);
        } catch (e) {
          // If the module doesn't exist, return undefined
          if (moduleName === 'crypto') {
            return cryptoShim;
          }
          throw e;
        }
      };
      console.log('[cryptoPolyfill] Android crypto require override installed (fallback)');
    }
  }
}

// Ensure webcrypto property exists
if (global.crypto && !global.crypto.webcrypto) {
  (global.crypto as any).webcrypto = global.crypto;
  console.log('[cryptoPolyfill] Added webcrypto property to global.crypto');
}

export default cryptoShim;