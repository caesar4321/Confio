import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Linking, StyleSheet, Text, TouchableOpacity} from 'react-native';

const defaultQueryResult: any = {
  data: {
    statsSummary: {
      totalValueLocked: 100,
      usdyReserve: 100,
      cusdBscCirculating: 50,
      cusdBscReserve: 50,
    },
    cusdPlusSummary: {
      grossApyPct: 3.55,
      netApyPct: 3.01,
      savingsEnabled: true,
      cusdDepositsPaused: true,
    },
  },
};
const mockUseQuery = jest.fn((_query?: any, _options?: any) => defaultQueryResult);
const openUrlSpy = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined as never);

jest.mock('@apollo/client', () => ({
  gql: (strings: TemplateStringsArray) => strings.join(''),
  useQuery: (...args: any[]) => mockUseQuery(...args),
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
jest.mock('../../config/env', () => ({
  CUSD_BSC_VAULT_ADDRESS: '0x6101cC370635cF2c7f2725EaB010aC407A8d543F',
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import {ProtectedSavingsScreen} from '../ProtectedSavingsScreen';

describe('ProtectedSavingsScreen section headings', () => {
  beforeEach(() => {
    mockUseQuery.mockClear();
    openUrlSpy.mockClear();
  });

  it('keeps the annual-yield heading inside narrow cards', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<ProtectedSavingsScreen />);
    });

    const heading = tree.root
      .findAllByType(Text)
      .find(node => node.props.children === 'Rendimiento todos los días');

    expect(heading).toBeDefined();
    expect(StyleSheet.flatten(heading!.props.style)).toEqual(
      expect.objectContaining({flexShrink: 1}),
    );
  });

  it('explains that annual APY still accumulates daily without a fixed term', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<ProtectedSavingsScreen />);
    });

    const copy = tree.root
      .findAllByType(Text)
      .flatMap(node =>
        Array.isArray(node.props.children)
          ? node.props.children
          : [node.props.children],
      )
      .filter(child => typeof child === 'string')
      .join(' ');

    expect(copy).toContain('La tasa que ves es anual (APY)');
    expect(copy).toContain('acumula rendimiento todos los días');
    expect(copy).toContain('No tienes que esperar un plazo fijo');
  });

  it('distinguishes all three dollar products and their reserves', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<ProtectedSavingsScreen />);
    });

    const copy = tree.root
      .findAllByType(Text)
      .flatMap(node =>
        Array.isArray(node.props.children)
          ? node.props.children
          : [node.props.children],
      )
      .filter(child => typeof child === 'string')
      .join(' ');

    expect(copy).toContain('Antiguo Confío Dollar (a-cUSD)');
    expect(copy).toContain('Confío Dollar (cUSD)');
    expect(copy).toContain('Confío Dollar+ (cUSD+)');
    expect(copy).toContain('Ver reserva USDC de a-cUSD');
    expect(copy).toContain('Ver reserva USDT de cUSD');
    expect(copy).toContain('Ver reserva USDY de cUSD+');
    expect(copy).not.toContain('red BNB Chain');
  });

  it('shows an unavailable USDY reserve as unknown rather than zero', () => {
    mockUseQuery.mockReturnValueOnce({
      data: {
        statsSummary: {
          totalValueLocked: 100,
          cusdBscReserve: 50,
          usdyReserve: null,
        },
      },
    });

    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<ProtectedSavingsScreen />);
    });

    const copy = tree.root
      .findAllByType(Text)
      .flatMap(node =>
        Array.isArray(node.props.children)
          ? node.props.children
          : [node.props.children],
      )
      .filter(child => typeof child === 'string')
      .join(' ');

    expect(copy).toMatch(/US\$\s*—\s*en USDY en reserva/);
    expect(copy).not.toMatch(/US\$\s*0\s*en USDY en reserva/);
  });

  it('opens the correct BscScan circulation and reserve pages', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => {
      tree = renderer.create(<ProtectedSavingsScreen />);
    });

    const pressLink = (label: string) => {
      const button = tree.root.findAllByType(TouchableOpacity).find(node =>
        node.findAllByType(Text).some(text => text.props.children === label),
      );
      expect(button).toBeDefined();
      act(() => button!.props.onPress());
    };

    pressLink('Ver cUSD en circulación');
    pressLink('Ver reserva USDT de cUSD');
    pressLink('Ver cUSD+ en circulación');
    pressLink('Ver reserva USDY de cUSD+');

    expect(openUrlSpy).toHaveBeenNthCalledWith(
      1,
      'https://bscscan.com/token/0x6101cC370635cF2c7f2725EaB010aC407A8d543F',
    );
    expect(openUrlSpy).toHaveBeenNthCalledWith(
      2,
      'https://bscscan.com/tokenholdings?a=0x6101cC370635cF2c7f2725EaB010aC407A8d543F',
    );
    expect(openUrlSpy).toHaveBeenNthCalledWith(
      3,
      'https://bscscan.com/token/0x3C29417eb4314155e63d4C7D4507852b87763Ed1',
    );
    expect(openUrlSpy).toHaveBeenNthCalledWith(
      4,
      'https://bscscan.com/tokenholdings?a=0x3C29417eb4314155e63d4C7D4507852b87763Ed1',
    );
  });
});
