console.log("[polyfills] running padEnd/crypto shims…");

// 1️⃣ crypto shim
import 'react-native-get-random-values';

// 2️⃣ padEnd shim
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