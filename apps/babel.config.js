const fs = require('fs');
const path = require('path');

const envName = (process.env.CONFIO_ENV || 'mainnet').toLowerCase();
const candidate = path.resolve(__dirname, `.env.${envName}`);
const fallback = path.resolve(__dirname, '.env');
const dotenvPath = fs.existsSync(candidate) ? candidate : fallback;

console.log(`[babel] Using ${path.basename(dotenvPath)} for react-native-dotenv (CONFIO_ENV=${envName})`);

module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    ['module:react-native-dotenv', {
      moduleName: '@env',
      path: dotenvPath,
      blacklist: null,
      whitelist: null,
      safe: false,
      allowUndefined: true,
    }],
    // Reanimated must be last
    'react-native-reanimated/plugin'
  ]
};
