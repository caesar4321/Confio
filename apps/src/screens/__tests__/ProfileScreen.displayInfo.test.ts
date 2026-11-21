import { profileDisplayInfo } from '../profileDisplayInfo';

const base = { userProfile: { firstName: 'Ana' }, username: '@ana', accountsLoading: false, isUserProfileLoading: false };

describe('ProfileScreen header for each account type', () => {
  it('own Cuenta inteligente shows the switcher label, not "Negocio"', () => {
    const info = profileDisplayInfo({ ...base, activeAccount: { type: 'smart', name: 'Cuenta inteligente', smart: {} } as any });
    expect(info).toMatchObject({ name: 'Cuenta inteligente', accountType: 'Tu cuenta', showAccountType: true });
  });

  it('an inherited account is marked heredada', () => {
    const info = profileDisplayInfo({ ...base, activeAccount: { type: 'smart', name: 'Cuenta de Luis', smart: { inherited: true } } as any });
    expect(info.name).toBe('Cuenta de Luis');
    expect(info.accountType).toBe('Cuenta inteligente · heredada');
    expect(info.accountType).not.toBe('Negocio');
  });

  it('business still says Negocio; personal shows no badge', () => {
    expect(profileDisplayInfo({ ...base, activeAccount: { type: 'business', name: 'Tienda' } }).accountType).toBe('Negocio');
    expect(profileDisplayInfo({ ...base, activeAccount: { type: 'personal', name: 'x' } })).toMatchObject({ name: 'Ana', showAccountType: false });
  });
});
