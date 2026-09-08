import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { ActivityIndicator, Alert, Text, TextInput, TouchableOpacity } from 'react-native';

const mockRefetch = jest.fn().mockResolvedValue({});
const mockClaim = jest.fn();
const mockCreate = jest.fn();
const mockNavigation = { navigate: jest.fn(), goBack: jest.fn(), setParams: jest.fn() };
let mockParams: any;
let mockRows: any[];
let mockSummary: any;
let mockDirectory: any;
let mockFocus: (() => void) | undefined;
jest.mock('@apollo/client', () => ({
  gql: (parts: TemplateStringsArray) => parts.join(''),
  useQuery: (query: string) => {
    const q = String(query);
    if (q.includes('institutionDirectory')) {
      return { data: mockDirectory, loading: false, refetch: jest.fn() };
    }
    if (q.includes('myBillingSummary')) {
      return { data: mockSummary, loading: false, refetch: jest.fn() };
    }
    return { data: { myBillingObligations: mockRows }, loading: false, refetch: mockRefetch };
  },
  useMutation: (query: string) => [query.includes('ClaimInstitutionMembership') ? mockClaim : mockCreate],
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => mockNavigation,
  useRoute: () => ({ params: mockParams }),
  useFocusEffect: (callback: () => void) => { mockFocus = callback; },
}));
jest.mock('../../contexts/AuthContext', () => ({ useAuthReady: () => true }));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import { MembershipsScreen } from '../MembershipsScreen';

describe('membership checkout', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRows = [];
    mockSummary = { myBillingSummary: { linked: false } };
    mockDirectory = undefined;
    mockParams = undefined;
    jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  });

  it('does not claim an identity from a public institution QR', async () => {
    mockParams = { provider: 'cip' };
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    expect(mockClaim).not.toHaveBeenCalled();
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Este QR público no vincula tu cuenta');
    await act(async () => { tree.unmount(); });
  });

  it('opens the selected bill without starting a payment', async () => {
    mockParams = { obligationId: 'chosen' };
    mockRows = ['chosen', 'other'].map(id => ({ id, institutionName: id === 'chosen' ? 'CIP' : 'Other',
      memberReference: '••42', amountMinor: 3500, amountRemainingMinor: 3500,
      currency: 'PEN', status: 'open', dueAt: '2026-09-30T12:00:00Z' }));
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('CIP');
    expect(copy).not.toContain('Other');
    expect(mockCreate).not.toHaveBeenCalled();
    await act(async () => { tree.unmount(); });
  });

  it('finishes a one-use claim after the loading state rerender', async () => {
    mockParams = { provider: 'cip', token: 'one-use-token' };
    let resolve!: (value: any) => void;
    mockClaim.mockReturnValue(new Promise(done => { resolve = done; }));
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    expect(tree.root.findAllByType(ActivityIndicator)).toHaveLength(1);
    await act(async () => {
      resolve({ data: { claimInstitutionMembership: { success: true } } });
    });
    expect(mockClaim).toHaveBeenCalledTimes(1);
    expect(mockRefetch).toHaveBeenCalled();
    expect(mockNavigation.setParams).toHaveBeenCalledWith({ provider: undefined, token: undefined });
    expect(tree.root.findAllByType(ActivityIndicator)).toHaveLength(0);
    await act(async () => { tree.unmount(); });
  });

  it('clears a rejected link without automatic replay and stops spinning', async () => {
    mockParams = { provider: 'cip', token: 'expired-token' };
    mockClaim.mockResolvedValue({ data: { claimInstitutionMembership: { success: false } } });
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    expect(mockClaim).toHaveBeenCalledTimes(1);
    expect(Alert.alert).toHaveBeenCalledTimes(1);
    expect(tree.root.findAllByType(ActivityIndicator)).toHaveLength(0);
    await act(async () => { tree.unmount(); });
  });

  it('offers payment only for collectible dues and refreshes after returning', async () => {
    mockRows = ['open', 'held', 'disputed', 'void'].map((status, i) => ({
      id: String(i), institutionName: 'Institution', memberReference: '••42',
      amountMinor: 3500, amountRemainingMinor: 3500, currency: 'PEN', status,
    }));
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const paymentButtons = tree.root.findAllByType(TouchableOpacity).filter(button =>
      button.findAllByType(Text).some(text => text.props.children === 'Pagar ahora'));
    expect(paymentButtons).toHaveLength(1);
    await act(async () => { mockFocus?.(); });
    expect(mockRefetch).toHaveBeenCalled();
    await act(async () => { tree.unmount(); });
  });

  it('separates confirmed payment from pending institution application', async () => {
    mockRows = [{ id: 'paid', institutionName: 'CIP', memberReference: '••42',
      amountMinor: 3500, amountRemainingMinor: 0, currency: 'PEN', status: 'paid',
      institutionApplicationStatus: 'application_pending' }];
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Pago confirmado');
    expect(copy).toContain('Esperando confirmación de la institución. No vuelvas a pagar.');
    expect(copy).not.toContain('membresía activa');
    expect(copy).not.toContain('Pagar ahora');
    await act(async () => { tree.unmount(); });
  });

  const pressLabel = (tree: renderer.ReactTestRenderer, label: string) => {
    const button = tree.root.findAllByType(TouchableOpacity)
      .find(node => node.props.accessibilityLabel === label);
    if (!button) throw new Error(`no button labelled ${label}`);
    return button;
  };

  it('offers both linking paths and makes no pricing claim when not linked', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Vincula tu institución');
    // Linking is paid on BOTH paths, and no charge is implemented yet, so a
    // discovery surface must not claim free or quote a price.
    expect(copy).not.toMatch(/no tiene costo|gratis|US\$/);
    expect(pressLabel(tree, 'Escanear QR')).toBeTruthy();
    expect(pressLabel(tree, 'Tengo un enlace o código')).toBeTruthy();
    await act(async () => { tree.unmount(); });
  });

  it('reads a linked member with no dues as up to date, not as unlinked', async () => {
    mockSummary = { myBillingSummary: { linked: true } };
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Estás al día');
    expect(copy).not.toContain('Vincula tu institución');
    await act(async () => { tree.unmount(); });
  });

  it('keeps a member with dues linked even when the summary query returns nothing', async () => {
    mockSummary = undefined;
    mockRows = [{ id: 'a', institutionName: 'CIP', memberReference: '••42',
      amountMinor: 3500, amountRemainingMinor: 3500, currency: 'PEN', status: 'open',
      dueAt: '2026-09-30T12:00:00Z' }];
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).not.toContain('Vincula tu institución');
    expect(copy).toContain('CIP');
    await act(async () => { tree.unmount(); });
  });

  it('routes a pasted institution link through the existing claim path', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    await act(async () => { pressLabel(tree, 'Tengo un enlace o código').props.onPress(); });
    await act(async () => {
      tree.root.findByType(TextInput).props.onChangeText(
        'confio://memberships?provider=cip&token=abc123');
    });
    await act(async () => { pressLabel(tree, 'Continuar').props.onPress(); });
    expect(mockNavigation.setParams).toHaveBeenCalledWith({ provider: 'cip', token: 'abc123' });
    await act(async () => { tree.unmount(); });
  });

  it('rejects an invalid pasted link without navigating', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    await act(async () => { pressLabel(tree, 'Tengo un enlace o código').props.onPress(); });
    await act(async () => {
      tree.root.findByType(TextInput).props.onChangeText('https://evil.example/memberships?provider=cip&token=x');
    });
    await act(async () => { pressLabel(tree, 'Continuar').props.onPress(); });
    expect(mockNavigation.setParams).not.toHaveBeenCalled();
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Ese enlace no es válido');
    await act(async () => { tree.unmount(); });
  });

  it('groups institutions and puts the soonest due date first', async () => {
    mockRows = [
      { id: 'late', institutionName: 'Colegio Zeta', memberReference: '••01',
        amountMinor: 5000, amountRemainingMinor: 5000, currency: 'PEN', status: 'open',
        dueAt: '2026-12-01T12:00:00Z' },
      { id: 'soon', institutionName: 'CIP', memberReference: '••42',
        amountMinor: 3500, amountRemainingMinor: 3500, currency: 'PEN', status: 'open',
        dueAt: '2026-09-30T12:00:00Z' },
    ];
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children);
    const firstIndex = (name: string) => copy.findIndex(entry => entry === name);
    expect(firstIndex('CIP')).toBeGreaterThanOrEqual(0);
    expect(firstIndex('CIP')).toBeLessThan(firstIndex('Colegio Zeta'));
    await act(async () => { tree.unmount(); });
  });

  it('lists institutions with a not-yet-linkable one marked, and keeps scan/paste', async () => {
    mockDirectory = { institutionDirectory: [
      { id: 'c1', name: 'Colegio de Ingenieros del Perú', provider: 'cip', linkingAvailable: false },
    ] };
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Colegio de Ingenieros del Perú');
    expect(copy).toContain('Próximamente');
    // The directory is additive: it must never replace the paths that work today.
    expect(pressLabel(tree, 'Escanear QR')).toBeTruthy();
    expect(pressLabel(tree, 'Tengo un enlace o código')).toBeTruthy();
    await act(async () => { tree.unmount(); });
  });

  it('a linkable institution carries no Proximamente badge', async () => {
    mockDirectory = { institutionDirectory: [
      { id: 'c1', name: 'Colegio Listo', provider: 'cip', linkingAvailable: true },
    ] };
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Colegio Listo');
    expect(copy).not.toContain('Próximamente');
    await act(async () => { tree.unmount(); });
  });

  it('a directory that fails to load never hides the working linking paths', async () => {
    mockDirectory = undefined; // server without institutionDirectory, errorPolicy: all
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Vincula tu institución');
    expect(copy).not.toContain('Instituciones en Confío');
    expect(pressLabel(tree, 'Escanear QR')).toBeTruthy();
    await act(async () => { tree.unmount(); });
  });

  it('does not show the directory to an already linked member', async () => {
    mockSummary = { myBillingSummary: { linked: true } };
    mockDirectory = { institutionDirectory: [
      { id: 'c1', name: 'Colegio de Ingenieros del Perú', provider: 'cip', linkingAvailable: false },
    ] };
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<MembershipsScreen />); });
    const copy = tree.root.findAllByType(Text).map(node => node.props.children).join(' ');
    expect(copy).toContain('Estás al día');
    expect(copy).not.toContain('Instituciones en Confío');
    await act(async () => { tree.unmount(); });
  });
});
