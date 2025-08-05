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

// Note: react-native-fast-base64 JSI binding issues are handled by Metro resolver
// which redirects the module to base64-js

// Export a dummy value to make this a module
export const aptosPolyfillsLoaded = true;