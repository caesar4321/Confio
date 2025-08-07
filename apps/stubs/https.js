/**
 * HTTPS stub for React Native
 * This provides a minimal https module stub
 */

// Export empty https module
module.exports = {
  request: () => {
    throw new Error('HTTPS requests should be made using fetch() in React Native');
  },
  get: () => {
    throw new Error('HTTPS requests should be made using fetch() in React Native');
  },
};