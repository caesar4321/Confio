import {internationalPhone, splitPhone} from '../RampPhoneField';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../RampCountryPicker', () => ({RampCountryPicker: () => null}));
jest.mock('../../CountryFlag', () => ({CountryFlag: () => null}));

it('shows the main country of a shared calling code, not the first alphabetically', () => {
  const {country, number} = splitPhone('+13055550100', 'BO');
  expect(country?.[2]).toBe('US');
  expect(number).toBe('3055550100');
});

it('prefers the home country when it shares the code', () => {
  expect(splitPhone('+13055550100', 'CA').country?.[2]).toBe('CA');
});

it('keeps a code only one country uses', () => {
  expect(splitPhone('+59171234567', 'US').country?.[2]).toBe('BO');
});

it('rebuilds the same number it split', () => {
  const {country, number} = splitPhone('+13055550100', 'BO');
  expect(internationalPhone(country, number)).toBe('+13055550100');
});
