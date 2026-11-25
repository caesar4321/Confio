jest.mock('@apollo/client', () => ({ gql: () => '', useApolloClient: () => ({}) }));
jest.mock('../../../components/common/AppText', () => ({ Text: 'Text', TextInput: 'TextInput' }));
jest.mock('../../../components/svg/GmailLogo', () => 'GmailLogo');
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import { parseMailNotice } from '../ChatCards';

it('reads the parts of a notice the server wrote', () => {
  expect(parseMailNotice('«Ana» te escribió a tu Gmail: «¿Cenamos?»\nSegún el correo: Pregunta por la cena.\nParece que espera tu respuesta.'))
    .toEqual({ sender: 'Ana', subject: '¿Cenamos?', summary: 'Pregunta por la cena.' });
  expect(parseMailNotice('«Luz» te escribió a tu Gmail: «Factura»\nParece un pago pendiente.'))
    .toEqual({ sender: 'Luz', subject: 'Factura', summary: null });
});

it('anything else stays a plain message', () => {
  expect(parseMailNotice('Listo, lo envié desde tu Gmail.')).toBeNull();
});
