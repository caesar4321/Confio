/* Drop-in replacement – patches ucs2.{decode,encode} if missing */
let real = require('../node_modules/punycode/punycode.js');   // actual library
real = real.default || real;

// Debug logging
console.log('[punycode shim] Loading - has ucs2?', !!real.ucs2);

if (!real.ucs2) real.ucs2 = {};
if (typeof real.ucs2.decode !== 'function') {
  console.log('[punycode shim] Adding ucs2.decode');
  real.ucs2.decode = str => Array.from(str).map(c => c.codePointAt(0));
}
if (typeof real.ucs2.encode !== 'function') {
  console.log('[punycode shim] Adding ucs2.encode');
  real.ucs2.encode = cps => String.fromCodePoint(...cps);
}

console.log('[punycode shim] Ready - ucs2.decode:', typeof real.ucs2.decode);

module.exports = real;