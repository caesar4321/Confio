// base64.js
const base64Chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

function encode(input) {
  if (typeof input === 'string') {
    // Use TextEncoder for proper UTF-8 encoding
    input = new TextEncoder().encode(input);
  }
  let output = '';
  for (let i = 0; i < input.length; i += 3) {
    const a = input[i];
    const b = input[i + 1] || 0;
    const c = input[i + 2] || 0;
    
    const byte1 = a >> 2;
    const byte2 = ((a & 3) << 4) | (b >> 4);
    const byte3 = ((b & 15) << 2) | (c >> 6);
    const byte4 = c & 63;
    
    output += base64Chars[byte1] + base64Chars[byte2] + 
              (i + 1 < input.length ? base64Chars[byte3] : '=') + 
              (i + 2 < input.length ? base64Chars[byte4] : '=');
  }
  return output;
}

function decode(b64) {
  const bytes = toByteArray(b64);
  return new TextDecoder('utf-8').decode(bytes);
}

function toByteArray(b64) {
  // Remove padding and non-base64 characters
  b64 = b64.replace(/[^A-Za-z0-9+/]/g, '');
  
  const output = new Uint8Array(Math.floor(b64.length * 3 / 4));
  let i = 0;
  let j = 0;
  
  while (i < b64.length) {
    const a = base64Chars.indexOf(b64[i++]);
    const b = base64Chars.indexOf(b64[i++]);
    const c = base64Chars.indexOf(b64[i++]);
    const d = base64Chars.indexOf(b64[i++]);
    
    output[j++] = (a << 2) | (b >> 4);
    if (c !== -1) {
      output[j++] = ((b & 15) << 4) | (c >> 2);
      if (d !== -1) {
        output[j++] = ((c & 3) << 6) | d;
      }
    }
  }
  
  return output;
}

function fromByteArray(bytes) {
  return encode(bytes);
}

module.exports = {
  encode,
  decode,
  toByteArray,
  fromByteArray
}; 