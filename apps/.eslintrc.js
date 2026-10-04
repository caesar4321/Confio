module.exports = {
  root: true,
  extends: '@react-native',
  rules: {
    // All text renders through components/common/AppText so the app uses
    // Instrument Sans (React 19 has no Text.defaultProps for a global font).
    '@typescript-eslint/no-restricted-imports': [
      'error',
      {
        paths: [
          {
            name: 'react-native',
            importNames: ['Text', 'TextInput'],
            message:
              "Import Text/TextInput from 'components/common/AppText' so the app font applies.",
            allowTypeImports: true,
          },
        ],
      },
    ],
  },
  overrides: [
    {
      // Tests query react-native Text by type; AppText renders it underneath.
      files: ['**/__tests__/**', '**/*.test.ts', '**/*.test.tsx', 'jest.setup.js'],
      rules: { '@typescript-eslint/no-restricted-imports': 'off' },
    },
  ],
  settings: {
    'import/resolver': {
      typescript: {
        alwaysTryTypes: true,
        project: './tsconfig.json',
      },
      node: {
        extensions: ['.js', '.jsx', '.ts', '.tsx', '.json'],
        moduleDirectory: ['node_modules', 'src'],
      },
    },
  },
};
