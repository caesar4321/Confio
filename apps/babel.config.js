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

const gradleContextPath = path.resolve(__dirname, '.generated/appcheck-gradle-context');
const gradleContext = fs.existsSync(gradleContextPath)
  ? fs.readFileSync(gradleContextPath, 'utf8')
  : '';
const forceAppCheckDebugOff =
  process.env.CONFIO_GRADLE_BUNDLE_RELEASE === 'true' ||
  /^CONFIO_GRADLE_BUNDLE_RELEASE=true$/m.test(gradleContext);

const releaseConfig = envName === 'mainnet' || forceAppCheckDebugOff ||
  process.env.NODE_ENV === 'production' || process.env.BABEL_ENV === 'production' ||
  /release/i.test(process.env.CONFIGURATION || '');

if (releaseConfig) {
  process.env.ALLOW_APP_CHECK_DEBUG = 'false';
  resolvedDotenvContents = setEnvValue(
    resolvedDotenvContents,
    'ALLOW_APP_CHECK_DEBUG',
    'false',
  );
} else if (process.env.ALLOW_APP_CHECK_DEBUG) {
  resolvedDotenvContents = setEnvValue(
    resolvedDotenvContents,
    'ALLOW_APP_CHECK_DEBUG',
    process.env.ALLOW_APP_CHECK_DEBUG,
  );
}

// A disabled debug provider does not make its credential safe to bundle.
// Strip both tokens from every mainnet/release generated environment.
if (releaseConfig) {
  for (const key of ['FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID', 'FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS']) {
    process.env[key] = ''; // react-native-dotenv also reads shell variables.
    resolvedDotenvContents = setEnvValue(resolvedDotenvContents, key, '');
  }
}

const generatedDir = path.resolve(__dirname, '.generated');
const generatedDotenvPath = path.join(generatedDir, `.env.${envName}.generated`);

fs.mkdirSync(generatedDir, { recursive: true });
fs.writeFileSync(generatedDotenvPath, resolvedDotenvContents, {mode: 0o600});
fs.chmodSync(generatedDotenvPath, 0o600);

console.log(
  `[babel] Using ${path.basename(dotenvPath)} for react-native-dotenv (CONFIO_ENV=${envName}, ALLOW_APP_CHECK_DEBUG=${releaseConfig ? 'forced-false-for-release' : process.env.ALLOW_APP_CHECK_DEBUG ?? 'file'})`
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
    ],
    env: {
      // Jest runs on Node, which can't execute untransformed `await import()`
      // without --experimental-vm-modules. Metro handles these itself.
      test: {
        plugins: ['@babel/plugin-transform-dynamic-import'],
      },
    },
  };
};
