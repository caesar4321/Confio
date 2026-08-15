import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {StyleSheet, Text} from 'react-native';

jest.mock('@apollo/client', () => ({
  gql: (strings: TemplateStringsArray) => strings.join(''),
  useQuery: () => ({
    data: {
      statsSummary: {totalValueLocked: 100, usdyReserve: 100},
      cusdPlusSummary: {
        grossApyPct: 3.55,
        netApyPct: 3.01,
        savingsEnabled: true,
        cusdDepositsPaused: true,
      },
    },
  }),
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: jest.fn(), goBack: jest.fn()}),
}));
jest.mock('../../navigation/Header', () => ({Header: 'Header'}));
jest.mock('../../hooks/useCurrency', () => ({
  useCurrency: () => ({currency: {thousandsSeparator: '.'}}),
}));
jest.mock('../../hooks/useRampCountry', () => ({
  useRampCountry: () => ({navigateToRampOrEfectivo: jest.fn()}),
}));
jest.mock('../../utils/numberFormatting', () => ({
  useNumberFormat: () => ({formatNumber: (value: number) => String(value)}),
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import {ProtectedSavingsScreen} from '../ProtectedSavingsScreen';

describe('ProtectedSavingsScreen section headings', () => {
  it('keeps the annual-yield heading inside narrow cards', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<ProtectedSavingsScreen />);
    });

    const heading = tree.root
      .findAllByType(Text)
      .find(node => node.props.children === 'Rendimiento anual');

    expect(heading).toBeDefined();
    expect(StyleSheet.flatten(heading!.props.style)).toEqual(
      expect.objectContaining({flexShrink: 1}),
    );
  });
});
