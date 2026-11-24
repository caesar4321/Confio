import { isWhatsAppNotification, routeWhatsAppNotification } from '../route';
import { takeWhatsAppRequest } from '../../connections/store';

jest.mock('react-native-keychain', () => ({}));

it('knows a WhatsApp notice in every shape a push arrives in', () => {
  expect(isWhatsAppNotification({ type: 'whatsapp_link' })).toBe(true);
  expect(isWhatsAppNotification({ data_type: 'whatsapp_link' })).toBe(true);
  expect(isWhatsAppNotification(JSON.stringify({ type: 'whatsapp_link' }))).toBe(true);
  expect(isWhatsAppNotification({ type: 'agent_task' })).toBe(false);
  expect(isWhatsAppNotification('not json')).toBe(false);
});

it('a WhatsApp notice goes to Inicio and asks for the WhatsApp screen there', () => {
  const navigate = jest.fn();
  expect(routeWhatsAppNotification({ type: 'whatsapp_link' }, navigate)).toBe(true);
  expect(navigate).toHaveBeenCalledTimes(1);
  expect(takeWhatsAppRequest()).toBe(true);
  expect(takeWhatsAppRequest()).toBe(false);  // once
  expect(routeWhatsAppNotification({ type: 'other' }, navigate)).toBe(false);
});
