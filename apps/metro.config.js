/**
 * Metro configuration for React Native
 * https://github.com/facebook/react-native
 *
 * @format
 */

const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');

const defaultConfig = getDefaultConfig(__dirname);

const {
  resolver: { sourceExts, assetExts },
} = getDefaultConfig(__dirname);

const config = {
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
      return context.resolveRequest(context, moduleName, platform);
    },
  },
};

module.exports = mergeConfig(defaultConfig, config);
