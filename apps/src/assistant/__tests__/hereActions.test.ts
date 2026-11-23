// Things finished right in the chat: the card's button does it on this phone.
const mockShareReferral = jest.fn(async () => {});
const mockShareUsername = jest.fn(async (username?: string | null) => !!username);
jest.mock('../../services/referralShare', () => ({
  shareReferralOnWhatsApp: (...args: unknown[]) => mockShareReferral(...(args as [])),
  shareOwnUsername: (username?: string | null) => mockShareUsername(username),
}));
jest.mock('../../apollo/queries', () => ({ UPDATE_USERNAME: 'updateUsername' }));
jest.mock('../../apollo/mutations', () => ({
  SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR: 'setPortfolioHidden', SET_DIRECT_MESSAGES_ENABLED: 'setMessages',
  SET_REFERRER: 'setReferrer',
}));
jest.mock('../api', () => ({ UPDATE_ASSISTANT_PROFILE: 'updatePet' }));
jest.mock('../../graphql/mutations/notifications', () => ({ UPDATE_NOTIFICATION_PREFERENCES: 'updatePreferences' }));
jest.mock('../../graphql/queries/notifications', () => ({ GET_NOTIFICATION_PREFERENCES: 'preferences' }));

import { HERE_CARDS, resolveHere, runHere } from '../hereActions';

const mutate = jest.fn();
const refreshProfile = jest.fn(async () => {});
const context = { username: 'ana', client: { mutate } as any, refreshProfile };
const action = (target: string, label = 'Hazlo') => resolveHere({ type: 'do', target, label })!;

beforeEach(() => jest.clearAllMocks());

describe('what the app accepts', () => {
  it('only the actions it knows, each with the argument it takes', () => {
    expect(resolveHere({ type: 'do', target: 'invite_whatsapp', label: 'Invitar por WhatsApp' }))
      .toEqual({ key: 'invite_whatsapp', arg: undefined, label: 'Invitar por WhatsApp' });
    expect(action('set_username:ana_perez')).toMatchObject({ key: 'set_username', arg: 'ana_perez' });
    expect(action('set_notifications:promotions=off')).toMatchObject({ key: 'set_notifications', arg: 'promotions=off' });
    for (const bad of ['delete_account', 'set_username', 'set_username:a b', 'set_username:ab', `set_username:${'x'.repeat(21)}`,
      'set_notifications:security=off', 'set_notifications:promotions=maybe', 'invite_whatsapp:extra', 'constructor',
      'customize_pet:x', 'set_pet_name', 'set_pet_name: Luna', `set_pet_name:${'x'.repeat(25)}`, 'set_messages:maybe',
      'set_messages', 'set_investor_profile:on', 'set_referrer', 'set_referrer:a b',
      'top_up', 'top_up:500', 'top_up:bob=500', 'top_up:BOB=-5', 'top_up:BOB=1,500', 'top_up:BOB=5.123']) {
      expect(resolveHere({ type: 'do', target: bad, label: 'x' })).toBeNull();
    }
    // Not this kind of action, or nothing to show on the card.
    expect(resolveHere({ type: 'navigate', target: 'invite_whatsapp', label: 'x' })).toBeNull();
    expect(resolveHere({ type: 'do', target: 'invite_whatsapp', label: '' })).toBeNull();
    expect(action('set_notifications:in_app=off')).toMatchObject({ arg: 'in_app=off' });
    // A name may carry spaces and a colon: everything after the first colon is the name.
    expect(action('set_pet_name:Luna: la gata')).toMatchObject({ key: 'set_pet_name', arg: 'Luna: la gata' });
    expect(action('set_investor_profile:hidden')).toMatchObject({ arg: 'hidden' });
    expect(action('top_up:BOB=1500.50')).toMatchObject({ key: 'top_up', arg: 'BOB=1500.50' });
    expect(Object.keys(HERE_CARDS).sort()).toEqual(['customize_pet', 'invite_whatsapp', 'set_investor_profile',
      'set_messages', 'set_notifications', 'set_pet_name', 'set_referrer', 'set_username', 'share_username', 'top_up']);
  });
});

describe('what the tap does', () => {
  it('inviting and sharing open the phone\'s own sheets and change nothing', async () => {
    expect(await runHere(action('invite_whatsapp'), context)).toBeNull();
    expect(mockShareReferral).toHaveBeenCalledWith('ana', 'chat');
    expect(await runHere(action('share_username'), context)).toBeNull();
    expect(mockShareUsername).toHaveBeenCalledWith('ana');
    expect(await runHere(action('share_username'), { ...context, username: null })).toEqual({ error: 'Primero crea tu @usuario.' });
    expect(mutate).not.toHaveBeenCalled();
  });

  it('a new @usuario goes through the app\'s own mutation, and the rest of the app hears of it', async () => {
    mutate.mockResolvedValue({ data: { updateUsername: { success: true } } });
    expect(await runHere(action('set_username:ana_perez'), context)).toEqual({ done: 'Listo: ahora eres @ana_perez' });
    expect(mutate).toHaveBeenCalledWith({ mutation: 'updateUsername', variables: { username: 'ana_perez' } });
    expect(refreshProfile).toHaveBeenCalledTimes(1);
    // Taken meanwhile: the server's own words, and nothing refreshed.
    mutate.mockResolvedValue({ data: { updateUsername: { success: false, error: 'Este nombre de usuario ya está en uso.' } } });
    expect(await runHere(action('set_username:ana_perez'), context)).toEqual({ error: 'Este nombre de usuario ya está en uso.' });
    expect(refreshProfile).toHaveBeenCalledTimes(1);
  });

  it('a notification switch sends that one switch and nothing else', async () => {
    mutate.mockResolvedValue({ data: { updateNotificationPreferences: { success: true } } });
    expect(await runHere(action('set_notifications:promotions=off'), context)).toEqual({ done: 'Listo: apagadas' });
    expect(mutate).toHaveBeenCalledWith({
      mutation: 'updatePreferences', variables: { pushPromotions: false }, refetchQueries: [{ query: 'preferences' }],
    });
    expect(await runHere(action('set_notifications:all=on'), context)).toEqual({ done: 'Listo: activadas' });
    expect(mutate.mock.calls[1][0].variables).toEqual({ pushEnabled: true });
    // Turned on here while the phone blocks them: asked of the phone, and said if it says no.
    const phoneAlerts = { enabled: jest.fn(async () => false), request: jest.fn(async () => false) };
    expect(await runHere(action('set_notifications:all=on'), { ...context, phoneAlerts }))
      .toEqual({ done: 'Listo. Falta permitirlas en los ajustes de tu teléfono.' });
    phoneAlerts.request.mockResolvedValue(true);
    expect(await runHere(action('set_notifications:all=on'), { ...context, phoneAlerts })).toEqual({ done: 'Listo: activadas' });
    // Turning one off, or the list inside the app, asks the phone nothing.
    phoneAlerts.request.mockClear();
    await runHere(action('set_notifications:promotions=off'), { ...context, phoneAlerts });
    await runHere(action('set_notifications:in_app=on'), { ...context, phoneAlerts });
    expect(phoneAlerts.request).not.toHaveBeenCalled();
  });

  it('the pet: its picker opens over the chat, and a name is saved and the conversation reads it again', async () => {
    const openPetPicker = jest.fn();
    const onPetChanged = jest.fn();
    expect(await runHere(action('customize_pet'), { ...context, openPetPicker })).toBeNull();
    expect(openPetPicker).toHaveBeenCalledTimes(1);
    expect(mutate).not.toHaveBeenCalled();
    mutate.mockResolvedValue({ data: { updateAssistantProfile: { success: true } } });
    expect(await runHere(action('set_pet_name:Luna'), { ...context, onPetChanged })).toEqual({ done: 'Listo: ahora me llamo Luna' });
    expect(mutate).toHaveBeenCalledWith({ mutation: 'updatePet', variables: { mascotName: 'Luna' } });
    expect(onPetChanged).toHaveBeenCalledTimes(1);
  });

  it('a top-up opens Recargar with the amount and the currency it was written in, and creates nothing', async () => {
    const openScreen = jest.fn();
    expect(await runHere(action('top_up:BOB=500'), { ...context, openScreen })).toBeNull();
    expect(openScreen).toHaveBeenCalledWith('TopUp', { amount: '500', amountCurrency: 'BOB' });
    expect(mutate).not.toHaveBeenCalled();
  });

  it('who may write and whether the investor profile is public: the one switch, and the server\'s own refusal', async () => {
    mutate.mockResolvedValue({ data: { setDirectMessagesEnabled: { success: true, enabled: false } } });
    expect(await runHere(action('set_messages:off'), context)).toEqual({ done: 'Listo: nadie nuevo podrá escribirte' });
    expect(mutate).toHaveBeenLastCalledWith({ mutation: 'setMessages', variables: { enabled: false } });
    mutate.mockResolvedValue({ data: { setCommunityPortfolioHidden: { success: true, hidden: false } } });
    expect(await runHere(action('set_investor_profile:public'), context)).toEqual({ done: 'Listo: tu perfil de inversor es público' });
    expect(mutate).toHaveBeenLastCalledWith({ mutation: 'setPortfolioHidden', variables: { hidden: false } });
    // Hiding too soon after publishing: said as the server says it.
    mutate.mockResolvedValue({ data: { setCommunityPortfolioHidden: { success: false, hidden: false, error: 'Podrás ocultarlo en 24 horas.' } } });
    expect(await runHere(action('set_investor_profile:hidden'), context)).toEqual({ error: 'Podrás ocultarlo en 24 horas.' });
  });

  it('who invited them is registered by the tap, with the server\'s reason when it cannot be', async () => {
    mutate.mockResolvedValue({ data: { setReferrer: { success: true } } });
    expect(await runHere(action('set_referrer:Carla_99'), context)).toEqual({ done: 'Listo: registré a @Carla_99' });
    expect(mutate).toHaveBeenLastCalledWith({ mutation: 'setReferrer', variables: { referrerIdentifier: 'Carla_99' } });
    mutate.mockResolvedValue({ data: { setReferrer: { success: false, error: 'Ya registraste a @otro.' } } });
    expect(await runHere(action('set_referrer:Carla_99'), context)).toEqual({ error: 'Ya registraste a @otro.' });
  });

  it('no connection is said on the card, not thrown', async () => {
    mutate.mockRejectedValue(new Error('network'));
    expect(await runHere(action('set_username:ana_perez'), context)).toEqual({ error: 'Sin conexión. Inténtalo de nuevo.' });
  });
});
