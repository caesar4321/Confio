// Import react-native-url-polyfill first
import 'react-native-url-polyfill/auto';

// Note: WebCrypto is now setup in src/setup/webcrypto.ts which is imported in index.js
// This ensures it's available before any Web3Auth modules are imported

console.log('[polyfills] Checking WebCrypto from webcrypto.ts setup...');
console.log('[polyfills] crypto.subtle available:', !!global.crypto?.subtle);
console.log('[polyfills] crypto.getRandomValues available:', !!global.crypto?.getRandomValues);

// URL polyfill for React Native - Must be first!
// Check if we need the polyfill
const needsURLPolyfill = (() => {
  try {
    // Test if URL exists and works
    if (typeof URL !== 'undefined') {
      const testUrl = new URL('https://test.com');
      // Check if protocol property exists and works
      if (testUrl.protocol && typeof testUrl.protocol === 'string') {
        return false; // URL is already working
      }
    }
  } catch (e) {
    // URL doesn't work, needs polyfill
  }
  return true;
})();

if (needsURLPolyfill) {
  console.log('[polyfills] Installing URL polyfill...');
  
  class URLPolyfill {
    constructor(url, base) {
      if (!url) {
        throw new TypeError('URL constructor: At least 1 argument required');
      }
      
      // Handle relative URLs
      if (base && !url.startsWith('http')) {
        if (url.startsWith('/')) {
          // Absolute path
          const baseMatch = base.match(/^(https?:\/\/[^\/]+)/);
          if (baseMatch) {
            url = baseMatch[1] + url;
          }
        } else {
          // Relative path
          url = base + (base.endsWith('/') ? '' : '/') + url;
        }
      }
      
      // Basic URL parsing
      const match = url.match(/^(https?):\/\/([^\/\?#]+)(\/[^\?#]*)?(\?[^#]*)?(#.*)?$/);
      if (!match) {
        throw new TypeError('Invalid URL: ' + url);
      }
      
      this.href = url;
      this.origin = match[1] + '://' + match[2];
      this._protocol = match[1] + ':';
      this.host = match[2];
      const hostParts = match[2].split(':');
      this.hostname = hostParts[0];
      this.port = hostParts[1] || (match[1] === 'https' ? '443' : '80');
      this.pathname = match[3] || '/';
      this.search = match[4] || '';
      this.hash = match[5] || '';
      
      // Create searchParams
      this.searchParams = new URLSearchParams(this.search);
    }
    
    // Define protocol as a getter/setter
    get protocol() {
      return this._protocol;
    }
    
    set protocol(value) {
      this._protocol = value;
    }
    
    toString() {
      return this.href;
    }
    
    toJSON() {
      return this.href;
    }
  }
  
  // Replace the global URL
  global.URL = URLPolyfill;
  
  // Also check if URL.prototype needs patching
  if (URL.prototype && !Object.getOwnPropertyDescriptor(URL.prototype, 'protocol')) {
    Object.defineProperty(URL.prototype, 'protocol', {
      get: function() { return this._protocol; },
      set: function(value) { this._protocol = value; },
      enumerable: true,
      configurable: true
    });
  }
  
  console.log('[polyfills] URL polyfill installed');
  
  global.URLSearchParams = class URLSearchParams {
    constructor(init) {
      this.params = {};
      if (init) {
        if (typeof init === 'string') {
          init = init.replace(/^\?/, '');
          init.split('&').forEach(param => {
            const [key, value] = param.split('=');
            this.params[decodeURIComponent(key)] = decodeURIComponent(value || '');
          });
        } else if (typeof init === 'object') {
          Object.keys(init).forEach(key => {
            this.params[key] = init[key];
          });
        }
      }
    }
    
    get(key) {
      return this.params[key] || null;
    }
    
    set(key, value) {
      this.params[key] = value;
    }
    
    toString() {
      return Object.keys(this.params)
        .map(key => encodeURIComponent(key) + '=' + encodeURIComponent(this.params[key]))
        .join('&');
    }
  };
}

// Buffer polyfill - Simple setup
if (typeof global.Buffer === 'undefined') {
  console.log('[polyfills] Setting up global Buffer...');
  const BufferModule = require('buffer');
  global.Buffer = BufferModule.Buffer;
  console.log('[polyfills] Buffer setup complete');
}


// Set up process global for crypto-browserify
try {
  if (typeof global.process === 'undefined') {
    global.process = require('process');
  }
} catch (error) {
  console.warn('[polyfills] Failed to load process:', error);
}

// Note: crypto setup handled above with WebCrypto
// Web3Auth will use the WebCrypto API for digest operations

// padEnd shim
if (!String.prototype.padEnd) {
  Object.defineProperty(String.prototype, 'padEnd', {
    configurable: true,
    writable: true,
    value: function padEnd(targetLength, padString = ' ') {
      const str = String(this);
      const len = str.length;
      targetLength = targetLength >> 0; // integer
      if (targetLength <= len) return str;
      padString = String(padString);
      const padLen = targetLength - len;
      const repeated = padString.repeat(Math.ceil(padLen / padString.length));
      return str + repeated.slice(0, padLen);
    },
  });
}

// atob and btoa polyfills
if (typeof atob === 'undefined') {
  global.atob = function(str) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
    let output = '';
    let i = 0;
    str = str.replace(/[^A-Za-z0-9\+\/\=]/g, '');
    while (i < str.length) {
      const enc1 = chars.indexOf(str.charAt(i++));
      const enc2 = chars.indexOf(str.charAt(i++));
      const enc3 = chars.indexOf(str.charAt(i++));
      const enc4 = chars.indexOf(str.charAt(i++));
      const chr1 = (enc1 << 2) | (enc2 >> 4);
      const chr2 = ((enc2 & 15) << 4) | (enc3 >> 2);
      const chr3 = ((enc3 & 3) << 6) | enc4;
      output = output + String.fromCharCode(chr1);
      if (enc3 !== 64) {
        output = output + String.fromCharCode(chr2);
      }
      if (enc4 !== 64) {
        output = output + String.fromCharCode(chr3);
      }
    }
    return output;
  };
}

if (typeof btoa === 'undefined') {
  global.btoa = function(str) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=';
    let output = '';
    let i = 0;
    str = encodeURIComponent(str).replace(/%([0-9A-F]{2})/g, function(match, p1) {
      return String.fromCharCode(parseInt(p1, 16));
    });
    while (i < str.length) {
      const chr1 = str.charCodeAt(i++);
      const chr2 = str.charCodeAt(i++);
      const chr3 = str.charCodeAt(i++);
      let enc1 = chr1 >> 2;
      let enc2 = ((chr1 & 3) << 4) | (chr2 >> 4);
      let enc3 = ((chr2 & 15) << 2) | (chr3 >> 6);
      let enc4 = chr3 & 63;
      if (isNaN(chr2)) {
        enc3 = 64;
        enc4 = 64;
      } else if (isNaN(chr3)) {
        enc4 = 64;
      }
      output = output + chars.charAt(enc1) + chars.charAt(enc2) + chars.charAt(enc3) + chars.charAt(enc4);
    }
    return output;
  };
}

console.log("[polyfills] running padEnd/crypto shims…");