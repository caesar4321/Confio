const fs = require('fs');
const path = require('path');

const envName = (process.env.CONFIO_ENV || 'mainnet').toLowerCase();
const candidate = path.resolve(__dirname, `.env.${envName}`);
const fallback = path.resolve(__dirname, '.env');
const dotenvPath = fs.existsSync(candidate) ? candidate : fallback;
const dotenvContents = fs.existsSync(dotenvPath) ? fs.readFileSync(dotenvPath, 'utf8') : '';

function setEnvValue(contents, key, value) {
  const line = `${key}=${value}`;
  const pattern = new RegExp(`^${key}=.*$`, 'm');

  if (pattern.test(contents)) {
    return contents.replace(pattern, line);
  }

  const trimmed = contents.trimEnd();
  return trimmed ? `${trimmed}\n${line}\n` : `${line}\n`;
}

let resolvedDotenvContents = dotenvContents;

if (process.env.ALLOW_APP_CHECK_DEBUG) {
  resolvedDotenvContents = setEnvValue(
    resolvedDotenvContents,
    'ALLOW_APP_CHECK_DEBUG',
    process.env.ALLOW_APP_CHECK_DEBUG,
  );
}

const generatedDir = path.resolve(__dirname, '.generated');
const generatedDotenvPath = path.join(generatedDir, `.env.${envName}.generated`);

fs.mkdirSync(generatedDir, { recursive: true });
fs.writeFileSync(generatedDotenvPath, resolvedDotenvContents);

console.log(
  `[babel] Using ${path.basename(dotenvPath)} for react-native-dotenv (CONFIO_ENV=${envName}, ALLOW_APP_CHECK_DEBUG=${process.env.ALLOW_APP_CHECK_DEBUG ?? 'file'})`
);

module.exports = function babelConfig(api) {
  api.cache.using(() => `${envName}:${generatedDotenvPath}:${resolvedDotenvContents}`);

  return {
    presets: ['module:@react-native/babel-preset'],
    plugins: [
      ['module:react-native-dotenv', {
        moduleName: '@env',
        path: generatedDotenvPath,
        blacklist: null,
        whitelist: null,
        safe: false,
        allowUndefined: true,
      }],
      // Reanimated must be last
      'react-native-reanimated/plugin'
    ]
  };
};
