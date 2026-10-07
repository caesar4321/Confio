import {Alert} from 'react-native';
import {isIdentityBlocked, showIdentityBlockedInterest} from '../localMoney';

it('only an identity refusal counts as blocked, never a step still open', () => {
  // The provider refuses who they are: the rail is listed, but not usable.
  expect(isIdentityBlocked({status: 'unavailable', reason: 'infinia_nationality_not_supported'})).toBe(true);
  expect(isIdentityBlocked({status: 'unavailable', reason: 'cobre_residence_country_not_supported'})).toBe(false);
  // Something they can still do, or a rail simply switched off.
  expect(isIdentityBlocked({status: 'needs_document', reason: 'document_not_accepted'})).toBe(false);
  expect(isIdentityBlocked({status: 'needs_verification', reason: 'identity_required'})).toBe(false);
  expect(isIdentityBlocked({status: 'unavailable', reason: 'not_enabled'})).toBe(false);
  expect(isIdentityBlocked({status: 'live', reason: ''})).toBe(false);
  expect(isIdentityBlocked({status: 'unavailable'})).toBe(false);
});


it('records curiosity only when the person declines the nationality waitlist', () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  const track = jest.fn();
  showIdentityBlockedInterest('Bre-B · Colombia', track);
  expect(track.mock.calls).toEqual([['tap']]);
  expect(alert.mock.calls[0][1]).toContain('nacionalidad venezolana');
  expect(alert.mock.calls[0][1]).toContain('aunque tengan un documento de otro país');
  const cancel = alert.mock.calls[0][2]!.find(button => button.text === 'Solo miraba')!;
  expect(cancel.style).toBe('cancel');
  cancel.onPress?.();
  expect(track.mock.calls).toEqual([['tap']]);
  expect(alert).toHaveBeenCalledTimes(1);
  alert.mockRestore();
});

it('records confirmation only after Sí, avísame, then acknowledges it', () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  const track = jest.fn();
  showIdentityBlockedInterest('Bre-B · Colombia', track);
  expect(track.mock.calls).toEqual([['tap']]);
  const confirm = alert.mock.calls[0][2]!.find(button => button.text === 'Sí, avísame')!;
  confirm.onPress!();
  expect(track.mock.calls).toEqual([['tap'], ['confirmed']]);
  expect(alert.mock.calls[1][0]).toBe('¡Anotado!');
  alert.mockRestore();
});

// The server only accepts a nationality-blocked waitlist join when its own
// IDENTITY_BLOCKED_REASONS (payment_accounts/local_money.py) agrees; a reason
// listed here but not there would show "Registramos tu interés" for a join
// the server refuses.
it('lists the same identity-blocked reasons as the server', () => {
  const {readFileSync} = require('fs');
  const {resolve} = require('path');
  const pick = (source: string, start: string, end: string) => {
    const block = source.slice(source.indexOf(start));
    return [...block.slice(0, block.indexOf(end)).matchAll(/'([a-z_]+)'/g)].map(m => m[1]).sort();
  };
  const client = pick(readFileSync(resolve(__dirname, '../localMoney.ts'), 'utf8'),
    'const IDENTITY_BLOCKED_REASONS', ']);');
  const server = pick(readFileSync(resolve(__dirname, '../../../../payment_accounts/local_money.py'), 'utf8'),
    'IDENTITY_BLOCKED_REASONS = frozenset({', '})');
  expect(client.length).toBeGreaterThan(0);
  expect(client).toEqual(server);
});
