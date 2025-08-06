// Polyfills for Aptos SDK in React Native
// The Aptos SDK expects browser globals that don't exist in React Native

// Add Event polyfill for Hermes
if (typeof global.Event === 'undefined') {
  global.Event = class Event {
    type: string;
    target: any;
    currentTarget: any;
    eventPhase: number;
    bubbles: boolean;
    cancelable: boolean;
    defaultPrevented: boolean;
    timeStamp: number;
    
    constructor(type: string, eventInit?: any) {
      this.type = type;
      this.target = null;
      this.currentTarget = null;
      this.eventPhase = 0;
      this.bubbles = eventInit?.bubbles || false;
      this.cancelable = eventInit?.cancelable || false;
      this.defaultPrevented = false;
      this.timeStamp = Date.now();
    }
    
    preventDefault() {
      this.defaultPrevented = true;
    }
    
    stopPropagation() {}
    stopImmediatePropagation() {}
  };
}

// Add CustomEvent polyfill
if (typeof global.CustomEvent === 'undefined') {
  global.CustomEvent = class CustomEvent extends global.Event {
    detail: any;
    
    constructor(type: string, eventInit?: any) {
      super(type, eventInit);
      this.detail = eventInit?.detail;
    }
  };
}

// Add EventTarget polyfill if needed
if (typeof global.EventTarget === 'undefined') {
  global.EventTarget = class EventTarget {
    private listeners: Map<string, Function[]> = new Map();
    
    addEventListener(type: string, listener: Function) {
      if (!this.listeners.has(type)) {
        this.listeners.set(type, []);
      }
      this.listeners.get(type)!.push(listener);
    }
    
    removeEventListener(type: string, listener: Function) {
      const typeListeners = this.listeners.get(type);
      if (typeListeners) {
        const index = typeListeners.indexOf(listener);
        if (index !== -1) {
          typeListeners.splice(index, 1);
        }
      }
    }
    
    dispatchEvent(event: any): boolean {
      const typeListeners = this.listeners.get(event.type);
      if (typeListeners) {
        typeListeners.forEach(listener => listener(event));
      }
      return true;
    }
  };
}

// Add any other browser globals the Aptos SDK might need
if (typeof global.window === 'undefined') {
  global.window = global;
}

// Add crypto.subtle polyfill if needed (React Native doesn't have WebCrypto)
if (typeof global.crypto === 'undefined') {
  global.crypto = {
    getRandomValues: (array: Uint8Array) => {
      // This should be handled by react-native-get-random-values
      // but add a fallback just in case
      for (let i = 0; i < array.length; i++) {
        array[i] = Math.floor(Math.random() * 256);
      }
      return array;
    }
  };
}

// Add TextDecoder and TextEncoder polyfills for React Native
if (typeof global.TextDecoder === 'undefined') {
  global.TextDecoder = class TextDecoder {
    encoding: string;
    
    constructor(encoding: string = 'utf-8') {
      this.encoding = encoding.toLowerCase();
    }
    
    decode(input?: ArrayBuffer | ArrayBufferView): string {
      if (!input) return '';
      
      let bytes: Uint8Array;
      if (input instanceof ArrayBuffer) {
        bytes = new Uint8Array(input);
      } else if (input instanceof Uint8Array) {
        bytes = input;
      } else {
        // Handle other typed arrays
        const view = input as ArrayBufferView;
        bytes = new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
      }
      
      // Simple UTF-8 decoding (handles ASCII and basic UTF-8)
      let result = '';
      for (let i = 0; i < bytes.length; i++) {
        const byte = bytes[i];
        if (byte < 0x80) {
          result += String.fromCharCode(byte);
        } else if ((byte & 0xe0) === 0xc0) {
          // 2-byte sequence
          const byte2 = bytes[++i];
          result += String.fromCharCode(((byte & 0x1f) << 6) | (byte2 & 0x3f));
        } else if ((byte & 0xf0) === 0xe0) {
          // 3-byte sequence
          const byte2 = bytes[++i];
          const byte3 = bytes[++i];
          result += String.fromCharCode(((byte & 0x0f) << 12) | ((byte2 & 0x3f) << 6) | (byte3 & 0x3f));
        } else if ((byte & 0xf8) === 0xf0) {
          // 4-byte sequence (surrogate pair)
          const byte2 = bytes[++i];
          const byte3 = bytes[++i];
          const byte4 = bytes[++i];
          const codePoint = ((byte & 0x07) << 18) | ((byte2 & 0x3f) << 12) | ((byte3 & 0x3f) << 6) | (byte4 & 0x3f);
          // Convert to surrogate pair
          const highSurrogate = 0xd800 + ((codePoint - 0x10000) >> 10);
          const lowSurrogate = 0xdc00 + ((codePoint - 0x10000) & 0x3ff);
          result += String.fromCharCode(highSurrogate, lowSurrogate);
        }
      }
      return result;
    }
  };
}

if (typeof global.TextEncoder === 'undefined') {
  global.TextEncoder = class TextEncoder {
    encoding: string = 'utf-8';
    
    encode(input: string): Uint8Array {
      if (!input) return new Uint8Array(0);
      
      // Count bytes needed
      let byteLength = 0;
      for (let i = 0; i < input.length; i++) {
        const code = input.charCodeAt(i);
        if (code < 0x80) {
          byteLength++;
        } else if (code < 0x800) {
          byteLength += 2;
        } else if (code < 0xd800 || code >= 0xe000) {
          byteLength += 3;
        } else {
          // Surrogate pair
          i++;
          byteLength += 4;
        }
      }
      
      // Encode to bytes
      const bytes = new Uint8Array(byteLength);
      let byteIndex = 0;
      
      for (let i = 0; i < input.length; i++) {
        const code = input.charCodeAt(i);
        if (code < 0x80) {
          bytes[byteIndex++] = code;
        } else if (code < 0x800) {
          bytes[byteIndex++] = 0xc0 | (code >> 6);
          bytes[byteIndex++] = 0x80 | (code & 0x3f);
        } else if (code < 0xd800 || code >= 0xe000) {
          bytes[byteIndex++] = 0xe0 | (code >> 12);
          bytes[byteIndex++] = 0x80 | ((code >> 6) & 0x3f);
          bytes[byteIndex++] = 0x80 | (code & 0x3f);
        } else {
          // Surrogate pair
          const highSurrogate = code;
          const lowSurrogate = input.charCodeAt(++i);
          const codePoint = 0x10000 + ((highSurrogate & 0x3ff) << 10) + (lowSurrogate & 0x3ff);
          
          bytes[byteIndex++] = 0xf0 | (codePoint >> 18);
          bytes[byteIndex++] = 0x80 | ((codePoint >> 12) & 0x3f);
          bytes[byteIndex++] = 0x80 | ((codePoint >> 6) & 0x3f);
          bytes[byteIndex++] = 0x80 | (codePoint & 0x3f);
        }
      }
      
      return bytes;
    }
  };
}

// Note: react-native-fast-base64 JSI binding issues are handled by Metro resolver
// which redirects the module to base64-js

// Export a dummy value to make this a module
export const aptosPolyfillsLoaded = true;