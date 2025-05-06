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
    path.resolve(__dirname, '../node_modules'),
    path.resolve(__dirname, '..'),
  ],
  transformer: {
    getTransformOptions: async () => ({
      transform: {
        experimentalImportSupport: false,
        inlineRequires: true,
      },
    }),
    babelTransformerPath: require.resolve('react-native-svg-transformer'),
  },
  resolver: {
    assetExts: assetExts.filter(ext => ext !== 'svg'),
    sourceExts: [...sourceExts, 'svg'],
    unstable_enableSymlinks: true,
    resolveRequest: (context, moduleName, platform) => {
      if (moduleName === 'node:buffer' || moduleName === 'buffer') {
        return {
          filePath: require.resolve('react-native-buffer'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'node:util' || moduleName === 'util') {
        return {
          filePath: require.resolve('react-native-util'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'node:crypto' || moduleName === 'crypto') {
        return {
          filePath: require.resolve('react-native-crypto'),
          type: 'sourceFile',
        };
      }
      if (moduleName === 'node:https' || moduleName === 'https') {
        return {
          filePath: require.resolve('react-native-https'),
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