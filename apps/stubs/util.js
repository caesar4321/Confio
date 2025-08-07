/**
 * Util stub for React Native
 * This provides minimal util module functionality
 */

module.exports = {
  TextDecoder: global.TextDecoder || class TextDecoder {
    decode(buffer) {
      return String.fromCharCode.apply(null, new Uint8Array(buffer));
    }
  },
  TextEncoder: global.TextEncoder || class TextEncoder {
    encode(string) {
      const buf = new Uint8Array(string.length);
      for (let i = 0; i < string.length; i++) {
        buf[i] = string.charCodeAt(i);
      }
      return buf;
    }
  },
  inherits: function(ctor, superCtor) {
    ctor.super_ = superCtor;
    ctor.prototype = Object.create(superCtor.prototype, {
      constructor: {
        value: ctor,
        enumerable: false,
        writable: true,
        configurable: true
      }
    });
  },
  deprecate: function(fn, msg) {
    return fn;
  },
  isArray: Array.isArray,
  isBuffer: function(obj) {
    return obj != null && obj.constructor != null &&
      typeof obj.constructor.isBuffer === 'function' &&
      obj.constructor.isBuffer(obj);
  },
  isFunction: function(obj) {
    return typeof obj === 'function';
  },
  isString: function(obj) {
    return typeof obj === 'string';
  },
  isObject: function(obj) {
    return typeof obj === 'object' && obj !== null;
  },
  isUndefined: function(obj) {
    return obj === void 0;
  },
  isNull: function(obj) {
    return obj === null;
  },
  isNullOrUndefined: function(obj) {
    return obj == null;
  },
  promisify: function(original) {
    return function(...args) {
      return new Promise((resolve, reject) => {
        original.call(this, ...args, (err, ...values) => {
          if (err) {
            reject(err);
          } else {
            resolve(values.length === 1 ? values[0] : values);
          }
        });
      });
    };
  }
};