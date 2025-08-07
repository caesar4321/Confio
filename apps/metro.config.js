/**
 * Metro configuration for React Native
 * https://github.com/facebook/react-native
 *
 * @format
 */

const path = require('path');
const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');
const exclusionList = require('metro-config/src/defaults/exclusionList');

const defaultConfig = getDefaultConfig(__dirname);

const {
  resolver: { sourceExts, assetExts },
} = defaultConfig;

const projectRoot = path.resolve(__dirname);

const config = {
  projectRoot,
  watchFolders: [
    path.resolve(__dirname, 'stubs'),
    path.resolve(__dirname, 'node_modules'),
    path.resolve(__dirname, '../node_modules'),
    path.resolve(__dirname, '..'),
  ],
  transformer: {
    getTransformOptions: async () => ({
      transform: {
        experimentalImportSupport: false,
        inlineRequires: false, // Disable for faster builds
      },
    }),
    babelTransformerPath: require.resolve('react-native-svg-transformer'),
    minifierPath: require.resolve('metro-minify-terser'),
    minifierConfig: {
      // Faster minification
      keep_fnames: true,
      mangle: {
        keep_fnames: true,
      },
    },
  },
  resolver: {
    resolverMainFields: ['react-native', 'browser', 'module', 'main'],
    assetExts: assetExts.filter(ext => ext !== 'svg'),
    sourceExts: [...sourceExts, 'svg'],
    unstable_enableSymlinks: true,
    extraNodeModules: {
      assert: require.resolve('empty-module'),
      http: require.resolve('empty-module'),
      https: require.resolve('./stubs/https.js'),
      os: require.resolve('empty-module'),
      url: require.resolve('empty-module'),
      zlib: require.resolve('empty-module'),
      path: require.resolve('empty-module'),
      stream: require.resolve('./stubs/stream.js'),
      buffer: require.resolve('./stubs/buffer.js'),
      process: require.resolve('./stubs/process.js'),
      util: require.resolve('./stubs/util.js'),
      punycode: require.resolve('punycode/'),
    },
    resolveRequest: (context, moduleName, platform) => {
      // Mock react-native-fast-base64 to avoid JSI binding errors
      if (moduleName === 'react-native-fast-base64') {
        return {
          filePath: require.resolve('./react-native-fast-base64.js'),
          type: 'sourceFile',
        };
      }
      
      // Handle Node.js core modules that need polyfills
      if (moduleName === 'stream' || moduleName === 'node:stream') {
        return {
          filePath: require.resolve('./stubs/stream.js'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'buffer' || moduleName === 'node:buffer') {
        return {
          filePath: require.resolve('./stubs/buffer.js'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'process' || moduleName === 'node:process') {
        return {
          filePath: require.resolve('./stubs/process.js'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'assert' || moduleName === 'node:assert') {
        return {
          filePath: require.resolve('empty-module'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'http' || moduleName === 'node:http') {
        return {
          filePath: require.resolve('empty-module'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'os' || moduleName === 'node:os') {
        return {
          filePath: require.resolve('empty-module'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'zlib' || moduleName === 'node:zlib') {
        return {
          filePath: require.resolve('empty-module'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'path' || moduleName === 'node:path') {
        return {
          filePath: require.resolve('empty-module'),
          type: 'sourceFile',
        };
      }
      
      if (moduleName === 'util' || moduleName === 'node:util') {
        return {
          filePath: require.resolve('./stubs/util.js'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'https' || moduleName === 'node:https') {
        return {
          filePath: require.resolve('./stubs/https.js'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'punycode') {
        return {
          filePath: require.resolve('punycode/'),
          type: 'sourceFile',
        };
      }
      
      if (moduleName.includes('DebuggingOverlayNativeComponent')) {
        return {
          filePath: require.resolve('./stubs/DebuggingOverlayNativeComponent.js'),
          type: 'sourceFile',
        };
      }
      if (moduleName.includes('NativeDevMenu')) {
        return {
          filePath: require.resolve('./stubs/NativeDevMenu.js'),
          type: 'sourceFile',
        };
      }
      
      return context.resolveRequest(context, moduleName, platform);
    },
    blacklistRE: exclusionList([]),
  },
  serializer: {
    getModulesRunBeforeMainModule: () => [
      require.resolve("./polyfills.js"),
    ],
  },
};

module.exports = mergeConfig(defaultConfig, config);