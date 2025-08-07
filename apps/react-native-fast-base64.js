// Mock implementation of react-native-fast-base64 for React Native
// This avoids JSI binding errors while providing base64 functionality

const base64 = require('base-64');

function toByteArray(base64String) {
  // Remove any whitespace
  const cleaned = base64String.replace(/\s/g, '');
  
  // Decode base64 to string
  const decoded = base64.decode(cleaned);
  
  // Convert string to Uint8Array
  const bytes = new Uint8Array(decoded.length);
  for (let i = 0; i < decoded.length; i++) {
    bytes[i] = decoded.charCodeAt(i);
  }
  
  return bytes;
}

function fromByteArray(uint8Array) {
  // Convert Uint8Array to string
  let str = '';
  for (let i = 0; i < uint8Array.length; i++) {
    str += String.fromCharCode(uint8Array[i]);
  }
  
  // Encode string as base64
  return base64.encode(str);
}

function byteLength(base64String) {
  // Calculate the byte length of a base64 string
  const len = base64String.length;
  let bytes = (len * 3) / 4;
  
  // Adjust for padding
  if (base64String[len - 1] === '=') bytes--;
  if (base64String[len - 2] === '=') bytes--;
  
  return bytes;
}

module.exports = {
  toByteArray,
  fromByteArray,
  byteLength
};