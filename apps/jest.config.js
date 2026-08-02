module.exports = {
  preset: 'react-native',
  // @noble/* ship ESM only. Metro handles that at runtime, but Jest needs it
  // transformed or any test importing evmWallet (which uses @noble/curves for
  // secp256k1) dies with "Cannot use import statement outside a module".
  // The leading entries are the react-native preset's own default, kept
  // verbatim because setting this key REPLACES the preset's value.
  transformIgnorePatterns: [
    'node_modules/(?!(?:@react-native|react-native|@noble)/)',
  ],
};
