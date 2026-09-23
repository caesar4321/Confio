import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import PortalConsole from './PortalConsole';

const mockSave = jest.fn();
let mockItems = [];
const mockMe = { me: { id: '1', isStaff: true, isOtpVerified: true, firstName: 'Admin' } };
const mockSupport = { portalSupportConversations: [] };
jest.mock('../../firebase', () => ({
  isFirebaseConfigured: () => false,
  onForegroundMessage: () => () => {},
  requestNotificationPermission: jest.fn(),
  getFCMToken: jest.fn(),
}));
jest.mock('@apollo/client', () => {
  const actual = jest.requireActual('@apollo/client');
  return { ...actual,
    useQuery: query => {
      const name = query.definitions[0].name.value;
      return { data: name === 'GetPortalMe' ? mockMe : name === 'GetPortalContentItems' ? { portalContentItems: mockItems } : mockSupport };
    },
    useMutation: () => [mockSave, { loading: false }],
  };
});

beforeEach(() => {
  mockItems = [];
  mockSave.mockReset().mockResolvedValue({ data: {} });
});
const openEditor = () => {
  render(<PortalConsole />);
  fireEvent.click(screen.getByRole('button', { name: 'Publicaciones' }));
};
const fillPoll = () => {
  fireEvent.click(screen.getByLabelText('Incluir encuesta'));
  fireEvent.change(screen.getByLabelText('Pregunta'), { target: { value: '¿Qué sigue?' } });
  fireEvent.change(screen.getByLabelText('Opción 1'), { target: { value: 'Pagos' } });
  fireEvent.change(screen.getByLabelText('Opción 2'), { target: { value: 'Ahorro' } });
};

test('saves question and stable answer IDs on both publication surfaces', async () => {
  openEditor();
  fillPoll();
  fireEvent.click(screen.getByRole('button', { name: 'Descubrir' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Guardar publicación' })); });
  await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
  const variables = mockSave.mock.calls[0][0].variables;
  expect(variables.surfaces).toEqual(['CHANNEL', 'DISCOVER']);
  expect(JSON.parse(variables.metadata).poll).toEqual({ question: '¿Qué sigue?', closed: false, options: [{ id: '1', label: 'Pagos' }, { id: '2', label: 'Ahorro' }] });
});

test('rejects duplicate answers before submission', () => {
  openEditor();
  fillPoll();
  fireEvent.change(screen.getByLabelText('Opción 2'), { target: { value: ' pagos ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Guardar publicación' }));
  expect(mockSave).not.toHaveBeenCalled();
  expect(screen.getByText('Escribe una pregunta y entre 2 y 10 opciones distintas.')).toBeInTheDocument();
});

test('shows totals and permits closure while locking a poll with votes', async () => {
  const poll = { question: '¿Qué sigue?', options: [{ id: '1', label: 'Pagos' }, { id: '2', label: 'Ahorro' }], closed: false };
  mockItems = [{ id: '42', title: 'Consulta', itemType: 'TEXT', status: 'PUBLISHED', channelSlug: 'julian', channelTitle: 'Julian', surfaces: ['CHANNEL'], metadata: JSON.stringify({ poll }), poll: { ...poll, totalVotes: 2, options: poll.options.map(option => ({ ...option, count: 1 })) } }];
  openEditor();
  fireEvent.click(screen.getByRole('button', { name: /Consulta/ }));
  expect(screen.getByLabelText('Pregunta')).toBeDisabled();
  expect(screen.getByLabelText('Opción 1')).toBeDisabled();
  expect(screen.getByText('2 votos')).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('Encuesta cerrada'));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Guardar publicación' })); });
  await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
  expect(JSON.parse(mockSave.mock.calls[0][0].variables.metadata).poll).toEqual({ ...poll, closed: true });
});

test.each(['null', '[]', '"scalar"', '42', 'false'])('rejects non-object metadata %s without losing a poll', value => {
  openEditor();
  fillPoll();
  fireEvent.change(screen.getByLabelText('Metadata (JSON)'), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: 'Guardar publicación' }));
  expect(mockSave).not.toHaveBeenCalled();
  expect(screen.getByText('Metadata debe ser un objeto JSON')).toBeInTheDocument();
  expect(screen.getByLabelText('Pregunta')).toHaveValue('¿Qué sigue?');
});

test('adds and removes options while keeping saved option IDs stable', async () => {
  const randomUUID = jest.fn().mockReturnValue('added-answer-id');
  Object.defineProperty(window, 'crypto', { value: { randomUUID }, configurable: true });
  openEditor();
  fillPoll();
  fireEvent.click(screen.getByRole('button', { name: 'Agregar opción' }));
  fireEvent.change(screen.getByLabelText('Opción 3'), { target: { value: 'Remesas' } });
  fireEvent.click(screen.getByRole('button', { name: 'Quitar opción 2' }));
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Guardar publicación' })); });
  expect(JSON.parse(mockSave.mock.calls[0][0].variables.metadata).poll.options).toEqual([
    { id: '1', label: 'Pagos' }, { id: 'added-answer-id', label: 'Remesas' },
  ]);
});
