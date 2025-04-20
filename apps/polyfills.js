// Buffer polyfill
if (typeof Buffer === 'undefined') {
  global.Buffer = require('buffer').Buffer;
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
      const enc1 = chr1 >> 2;
      const enc2 = ((chr1 & 3) << 4) | (chr2 >> 4);
      const enc3 = ((chr2 & 15) << 2) | (chr3 >> 6);
      const enc4 = chr3 & 63;
      if (isNaN(chr2)) {
        enc3 = enc4 = 64;
      } else if (isNaN(chr3)) {
        enc4 = 64;
      }
      output = output + chars.charAt(enc1) + chars.charAt(enc2) + chars.charAt(enc3) + chars.charAt(enc4);
    }
    return output;
  };
}

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