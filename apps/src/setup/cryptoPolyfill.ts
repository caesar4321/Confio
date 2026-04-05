// cryptoPolyfill.ts - Fixes crypto module issues for Web3Auth on Android
import { Platform } from 'react-native';

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
          return cryptoShim;
        }
        return originalLoad.apply(this, arguments);
      };
    }
    
    // Also set it on global for direct access
    (global as any).crypto_node = cryptoShim;
  } catch (error) {
    // Fallback: Try to override require directly
    const originalRequire = (global as any).require;
    if (originalRequire && typeof originalRequire === 'function') {
      (global as any).require = function(moduleName: string) {
        if (moduleName === 'crypto') {
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
    }
  }
}

// Ensure webcrypto property exists
if (global.crypto && !global.crypto.webcrypto) {
  (global.crypto as any).webcrypto = global.crypto;
}

export default cryptoShim;
