"""Which Pix participant hosts a charge, from the site's EV certificate and
the Central Bank's public list."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from payment_accounts import pix_participants
from payment_accounts.models import PixChargeHost, PixParticipant

HEADER = ('Lista de participantes ativos do Pix\n'
          ' ;Nome Reduzido;ISPB;CNPJ;Tipo de Instituição;Autorizada pelo BCB;Tipo de Participação no SPI;'
          'Tipo de Participação no Pix;Modalidade de Participação no Pix;Iniciação de Transação de Pagamento;FSS\n')
ROWS = ('1;99PAY IP S.A.;24313102;24.313.102/0001-25;Instituição de Pagamento;Sim;Direta;Facultativa;'
        'Provedor de Conta Transacional;Sim;Não\n'
        '4;ACCESSTAGE IP LTDA.;;46.410.407/0001-98;Instituição de Pagamento;Sim;;Facultativa;Iniciador;Sim;N/A\n'
        '62;BCO DO BRASIL S.A.;00000000;00.000.000/0001-91;Banco Múltiplo;Sim;Direta;Obrigatória;'
        'Provedor de Conta Transacional;Sim;Sim\n')


def certificate(*, cnpj='00000000000191', organization='BANCO DO BRASIL SA', ev=True, names=('qr.example.com',),
                country='BR'):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import NameOID, ObjectIdentifier
    key = ec.generate_private_key(ec.SECP256R1())
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, names[0]),
                  x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization)]
    if country:
        attributes.append(x509.NameAttribute(NameOID.COUNTRY_NAME, country))
    if cnpj:
        attributes.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, cnpj))
    subject = x509.Name(attributes)
    now = datetime.now(dt_timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
               .not_valid_after(now + timedelta(days=30))
               .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False))
    policy = pix_participants.EV_POLICY if ev else '2.23.140.1.2.2'
    builder = builder.add_extension(x509.CertificatePolicies(
        [x509.PolicyInformation(ObjectIdentifier(policy), None)]), critical=False)
    return builder.sign(key, hashes.SHA256()).public_bytes(Encoding.DER)


class SiteIdentityTests(SimpleTestCase):
    def test_reads_the_company_and_whether_the_certificate_is_ev(self):
        site = pix_participants.site_identity(certificate(cnpj='00.000.000/0001-91'))
        self.assertEqual(site, {'organization': 'BANCO DO BRASIL SA', 'cnpj': '00000000000191', 'ev': True,
                                'wildcard': False})
        self.assertFalse(pix_participants.site_identity(certificate(ev=False))['ev'])
        self.assertTrue(pix_participants.site_identity(certificate(names=('*.example.com',)))['wildcard'])
        # A foreign parent company: no CNPJ to join.
        self.assertEqual(pix_participants.site_identity(certificate(cnpj='5045712'))['cnpj'], '')
        self.assertEqual(pix_participants.site_identity(certificate(cnpj=''))['cnpj'], '')
        # Fourteen digits registered in another country are not a CNPJ.
        self.assertEqual(pix_participants.site_identity(certificate(country='US'))['cnpj'], '')
        self.assertEqual(pix_participants.site_identity(certificate(country=''))['cnpj'], '')

    def test_an_unreadable_certificate_vouches_for_nothing(self):
        self.assertIsNone(pix_participants.site_identity(b'not a certificate'))
        self.assertIsNone(pix_participants.site_identity(None))

    def test_the_public_list_is_parsed_as_published(self):
        rows = pix_participants.parse_list(HEADER + ROWS)
        self.assertEqual([(r['ispb'], r['cnpj'], r['name']) for r in rows], [
            ('24313102', '24313102000125', '99PAY IP S.A.'), ('00000000', '00000000000191', 'BCO DO BRASIL S.A.')])
        self.assertEqual(rows[0]['participation'], 'Provedor de Conta Transacional')
        # An initiator has no ISPB: never read as ISPB 00000000.
        self.assertNotIn('ACCESSTAGE IP LTDA.', [r['name'] for r in rows])
        with self.assertRaises(ValueError):
            pix_participants.parse_list('nothing here')

    def test_institutions_still_joining_are_not_participants(self):
        joining = ('\nLista de instituições em processo de adesão ao Pix\n' + HEADER.split('\n', 1)[1]
                   + '1;AINDA NAO IP S.A.;55555555;55.555.555/0001-55;Instituição de Pagamento;Sim;Direta;'
                     'Facultativa;Provedor de Conta Transacional;Sim;Não\n')
        rows = pix_participants.parse_list(HEADER + ROWS + joining)
        self.assertEqual({r['ispb'] for r in rows}, {'24313102', '00000000'})
        # The separator may be a row of bare delimiters instead of a blank line.
        rows = pix_participants.parse_list(HEADER + ROWS + ';;;;;;;;;;' + joining)
        self.assertEqual({r['ispb'] for r in rows}, {'24313102', '00000000'})


class InstitutionTests(TestCase):
    def setUp(self):
        self.bb = PixParticipant.objects.create(ispb='00000000', cnpj='00000000000191', name='BCO DO BRASIL S.A.',
                                                listed_on=timezone.localdate(), updated_at=timezone.now())
        self.site = pix_participants.site_identity(certificate())

    def test_an_ev_certificate_of_a_participant_names_the_institution(self):
        self.assertEqual(pix_participants.institution_for('qr.example.com', self.site),
                         {'name': 'BCO DO BRASIL S.A.', 'ispb': '00000000', 'source': 'ev_certificate'})
        # Any branch of the same company (another CNPJ suffix) is the same institution.
        branch = pix_participants.site_identity(certificate(cnpj='00000000528710'))
        self.assertEqual(pix_participants.institution_for('qr.example.com', branch)['ispb'], '00000000')

    def test_nothing_weaker_is_called_an_institution(self):
        for site in (dict(self.site, ev=False), dict(self.site, wildcard=True), dict(self.site, cnpj=''),
                     dict(self.site, cnpj='99999999000100'), None):
            with self.subTest(site=site):
                self.assertIsNone(pix_participants.institution_for('qr.example.com', site))
        PixParticipant.objects.filter(pk=self.bb.pk).update(active=False)
        self.assertIsNone(pix_participants.institution_for('qr.example.com', self.site))

    def test_a_stale_list_vouches_for_nobody(self):
        PixParticipant.objects.update(updated_at=timezone.now() - timedelta(days=40))
        self.assertIsNone(pix_participants.institution_for('qr.example.com', self.site))

    def test_a_host_reviewed_by_hand_is_named_whatever_its_certificate(self):
        PixChargeHost.objects.create(host='Pix-QR.Example.com.', institution_name='Mercado Pago IP')
        self.assertEqual(pix_participants.institution_for('pix-qr.example.com', None),
                         {'name': 'Mercado Pago IP', 'ispb': '', 'source': 'reviewed_host'})
        PixChargeHost.objects.update(active=False)
        self.assertIsNone(pix_participants.institution_for('pix-qr.example.com', None))
        # A reviewed host tied to an institution that has left Pix stops counting.
        PixChargeHost.objects.create(host='old.example.com', participant=self.bb)
        self.assertEqual(pix_participants.institution_for('old.example.com', None)['ispb'], '00000000')
        PixParticipant.objects.filter(pk=self.bb.pk).update(active=False)
        self.assertIsNone(pix_participants.institution_for('old.example.com', None))

    @override_settings(PIX_PARTICIPANTS_MIN_ROWS=2)
    def test_refresh_replaces_the_list_and_refuses_a_truncated_one(self):
        PixParticipant.objects.create(ispb='11111111', cnpj='11111111000111', name='GONE',
                                      listed_on=timezone.localdate(), updated_at=timezone.now())
        self.assertEqual(pix_participants.refresh(HEADER + ROWS), 2)
        self.assertFalse(PixParticipant.objects.get(ispb='11111111').active)
        self.assertTrue(PixParticipant.objects.get(ispb='24313102').active)
        with override_settings(PIX_PARTICIPANTS_MIN_ROWS=300), self.assertRaises(ValueError):
            pix_participants.refresh(HEADER + ROWS)
        self.assertTrue(PixParticipant.objects.get(ispb='24313102').active)
