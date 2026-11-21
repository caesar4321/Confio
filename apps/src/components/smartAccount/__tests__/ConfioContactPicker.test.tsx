// The payee / beneficiary picker applies SendToFriend's wrong-recipient guard:
// a Confío match inferred from a number saved without a country code must be
// confirmed before it can be picked.
const mockIsConfirmed = jest.fn();
const mockConfirm = jest.fn();
jest.mock('../../../services/recipientConfirmationService', () => ({
  recipientNeedsConfirmation: jest.requireActual('../../../services/recipientConfirmationService').recipientNeedsConfirmation,
  formatRecipientPhoneForDisplay: (p: string) => p,
  recipientConfirmationService: {
    isConfirmed: (...a: unknown[]) => mockIsConfirmed(...a),
    confirm: (...a: unknown[]) => mockConfirm(...a),
  },
}));
const mockContacts = jest.fn();
jest.mock('../../../services/contactService', () => ({ contactService: { getAllContacts: () => mockContacts() } }));
jest.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: { id: 'u1' } }) }));
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ goBack: jest.fn() }), useRoute: () => ({}) }));
jest.mock('../../../navigation/Header', () => ({ Header: () => null }));
jest.mock('../../svg/CuentaInteligenteMark', () => 'CuentaInteligenteMark');
jest.mock('../../SkeletonLoader', () => ({ SkeletonLoader: 'SkeletonLoader' }));

import React from 'react';
import { Alert } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import { ConfioContactPicker, confirmPickedEntry } from '../ConfioContactPicker';
import { flush, tap } from '../testing/fixtures';

const entry = (over = {}) => ({
  inferred: true, contactName: 'Ana', contactRecordId: 'c1', recipientUserId: '42',
  matchedPhone: '+584121234567', confioUsername: 'ana', name: 'Ana P.', ...over,
});

beforeEach(() => {
  jest.clearAllMocks();
  mockIsConfirmed.mockResolvedValue(false);
});

describe('confirmPickedEntry', () => {
  it('lets a match that was not inferred through without asking', async () => {
    const alert = jest.fn();
    expect(await confirmPickedEntry(entry({ inferred: false }), 'u1', alert)).toBe(true);
    expect(alert).not.toHaveBeenCalled();
  });

  it('asks for an inferred match and remembers a yes', async () => {
    const alert = jest.fn((_t, _b, buttons: any[]) => { void buttons[1].onPress(); });
    expect(await confirmPickedEntry(entry(), 'u1', alert as any)).toBe(true);
    expect(alert.mock.calls[0][0]).toBe('Confirma a la persona');
    expect(mockConfirm).toHaveBeenCalledWith('u1', 'c1', '42', '+584121234567');
  });

  it('a cancel does not pick', async () => {
    const alert = jest.fn((_t, _b, buttons: any[]) => { buttons[0].onPress(); });
    expect(await confirmPickedEntry(entry(), 'u1', alert as any)).toBe(false);
    expect(mockConfirm).not.toHaveBeenCalled();
  });

  it('does not ask again once confirmed for this contact and account', async () => {
    mockIsConfirmed.mockResolvedValue(true);
    const alert = jest.fn();
    expect(await confirmPickedEntry(entry(), 'u1', alert)).toBe(true);
    expect(alert).not.toHaveBeenCalled();
  });

  it('refuses an inferred match it cannot verify', async () => {
    const alert = jest.fn();
    expect(await confirmPickedEntry(entry({ recipientUserId: '' }), 'u1', alert)).toBe(false);
    expect(alert.mock.calls[0][0]).toBe('No pudimos verificar a esta persona');
  });
});

describe('ConfioContactPicker', () => {
  it('does not call onPick for an inferred match until confirmed', async () => {
    mockContacts.mockResolvedValue([{
      id: 'c1', name: 'Ana', isOnConfio: true, confioUserId: '42', confioUsername: 'ana',
      confioFirstName: 'Ana', confioLastName: 'P.', confioMatchedPhone: '+584121234567', confioMatchWasInferred: true,
    }]);
    const spy = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    const onPick = jest.fn();
    let tree: renderer.ReactTestRenderer;
    await act(async () => {
      tree = renderer.create(<ConfioContactPicker visible title="x" onClose={() => {}} onPick={onPick} />);
    });
    await flush();
    await tap(tree!, 'Ana P., @ana');
    await flush();
    expect(spy).toHaveBeenCalled();
    expect(onPick).not.toHaveBeenCalled();
    const buttons = spy.mock.calls[0][2] as any[];
    await act(async () => { await buttons[1].onPress(); });
    await flush();
    expect(onPick).toHaveBeenCalledWith({ handle: 'ana', name: 'Ana P.' });
    spy.mockRestore();
    await act(async () => tree!.unmount());
  });
});
