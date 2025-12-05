/**
 * Buffer polyfill wrapper for React Native
 * NOTE: Metro now aliases 'buffer' directly to the package. This stub remains
 * as a safety net for any direct imports of this file.
 */

// Prefer an existing global Buffer
if (global.Buffer) {
  module.exports = { Buffer: global.Buffer };
} else {
  // Fallback to the actual buffer package (resolved by Metro alias)
  module.exports = require('buffer/');
}
