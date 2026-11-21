"""The payer-side checks of a dynamic Pix charge (BCB Manual de Segurança do
SFN Vol. II, section 4), against a test CA and real signatures."""
import base64
import hashlib
import json
import socket
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from payment_accounts import pix_payload
from payment_accounts.pix_payload import PixPayloadError

HOST = 'pix.example.com'
LOCATION = HOST + '/qr/v2/cob/4d8f085b2d9149deb10c3d0be5c59783'


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _certificate(subject, issuer, public_key, signer, *, ca, host=None):
    now = datetime.utcnow()
    builder = (x509.CertificateBuilder().subject_name(_name(subject)).issuer_name(_name(issuer))
               .public_key(public_key).serial_number(x509.random_serial_number())
               .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
               .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False))
    if ca:
        builder = builder.add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False),
            critical=True)
    else:
        builder = (builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
                   .add_extension(x509.KeyUsage(
                       digital_signature=True, content_commitment=False, key_encipherment=False,
                       data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                       encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()),
                                  critical=False))
    return builder.sign(signer, hashes.SHA256())


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class PixPayloadTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root_key = ec.generate_private_key(ec.SECP256R1())
        cls.root = _certificate('Test Root', 'Test Root', cls.root_key.public_key(), cls.root_key, ca=True)
        cls.leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.leaf = _certificate(HOST, 'Test Root', cls.leaf_key.public_key(), cls.root_key, ca=False, host=HOST)
        cls.bundle = tempfile.NamedTemporaryFile(suffix='.pem', delete=False)
        cls.bundle.write(cls.root.public_bytes(serialization.Encoding.PEM))
        cls.bundle.close()

    def setUp(self):
        mock.patch.object(pix_payload, '_ca_bundle', return_value=self.bundle.name).start()
        self.addCleanup(mock.patch.stopall)
        self.leaf_der = self.leaf.public_bytes(serialization.Encoding.DER)
        self.thumb = _b64(hashlib.sha256(self.leaf_der).digest())
        self.header = {'alg': 'PS256', 'kid': 'k1', 'jku': f'https://{HOST}/jwks', 'x5t#S256': self.thumb}
        self.jwks = {'keys': [{'kty': 'RSA', 'kid': 'k1', 'key_ops': ['verify'], 'x5t#S256': self.thumb,
                               'x5c': [base64.b64encode(self.leaf_der).decode(),
                                       base64.b64encode(self.root.public_bytes(serialization.Encoding.DER)).decode()]}]}
        now = timezone.now()
        self.payload = {'txid': 'a' * 26, 'revisao': 0, 'status': 'ATIVA', 'chave': 'loja@example.com',
                        'calendario': {'criacao': now.isoformat(), 'apresentacao': now.isoformat(), 'expiracao': 1800},
                        'valor': {'original': '250.75', 'modalidadeAlteracao': 0}}

    def token(self, payload=None, header=None, key=None):
        header = dict(header if header is not None else self.header)
        alg = header.pop('alg')
        return jwt.encode(payload if payload is not None else self.payload, key or self.leaf_key,
                          algorithm=alg, headers=header)

    def serve(self, token, jwks=None, status=200):
        responses = {'/qr/v2/cob/4d8f085b2d9149deb10c3d0be5c59783': (status, 'application/jose', token.encode()),
                     '/jwks': (200, 'application/json', json.dumps(jwks or self.jwks).encode())}
        calls = []

        def get(host, path, accept, deadline=None):
            calls.append((host, path))
            self.assertEqual(host, HOST)
            return responses[path.split('?', 1)[0]]
        mock.patch.object(pix_payload, 'https_get', side_effect=get).start()
        return calls

    def test_a_signed_charge_is_read(self):
        self.serve(self.token())
        charge = pix_payload.resolve_dynamic(LOCATION)
        self.assertEqual(charge['amount'], Decimal('250.75'))
        self.assertEqual(charge['domain'], HOST)
        self.assertEqual(charge['key'], 'loja@example.com')
        self.assertAlmostEqual(charge['expires_at'].timestamp(), (timezone.now() + timedelta(seconds=1800)).timestamp(),
                               delta=5)

    def test_every_allowed_algorithm_family_verifies(self):
        ec_key = ec.generate_private_key(ec.SECP256R1())
        ec_leaf = _certificate(HOST, 'Test Root', ec_key.public_key(), self.root_key, ca=False, host=HOST)
        der = ec_leaf.public_bytes(serialization.Encoding.DER)
        thumb = _b64(hashlib.sha256(der).digest())
        jwks = {'keys': [{'kty': 'EC', 'kid': 'e1', 'x5t#S256': thumb,
                          'x5c': [base64.b64encode(der).decode()]}]}
        self.serve(self.token(header={'alg': 'ES256', 'kid': 'e1', 'jku': f'https://{HOST}/jwks',
                                      'x5t#S256': thumb}, key=ec_key), jwks=jwks)
        self.assertEqual(pix_payload.resolve_dynamic(LOCATION)['amount'], Decimal('250.75'))

    def test_refusals(self):
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        stranger = _certificate('evil.example', 'Test Root', self.leaf_key.public_key(), self.root_key,
                                ca=False, host='evil.example')
        self_signed_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self_signed = _certificate(HOST, HOST, self_signed_key.public_key(), self_signed_key, ca=False, host=HOST)
        cases = {
            'forged signature': dict(token=self.token(key=other_key)),
            'hmac': dict(token=jwt.encode(self.payload, 'secret', algorithm='HS256', headers={
                'kid': 'k1', 'jku': f'https://{HOST}/jwks', 'x5t#S256': self.thumb})),
            'jku elsewhere': dict(token=self.token(header=dict(self.header, jku='https://evil.example/jwks'))),
            'jku not https': dict(token=self.token(header=dict(self.header, jku=f'http://{HOST}/jwks'))),
            'unknown kid': dict(token=self.token(header=dict(self.header, kid='nope'))),
            'thumbprint mismatch': dict(token=self.token(header=dict(self.header, **{'x5t#S256': 'AAAA'}))),
            'no thumbprint': dict(token=self.token(header={k: v for k, v in self.header.items() if k != 'x5t#S256'})),
            'certificate for another host': dict(token=self.token(header=dict(self.header, **{
                'x5t#S256': _b64(hashlib.sha256(stranger.public_bytes(serialization.Encoding.DER)).digest())})),
                jwks={'keys': [{'kid': 'k1', 'x5t#S256': _b64(hashlib.sha256(
                    stranger.public_bytes(serialization.Encoding.DER)).digest()),
                    'x5c': [base64.b64encode(stranger.public_bytes(serialization.Encoding.DER)).decode()]}]}),
            'untrusted chain': dict(token=self.token(header=dict(self.header, **{
                'x5t#S256': _b64(hashlib.sha256(self_signed.public_bytes(serialization.Encoding.DER)).digest())}),
                key=self_signed_key),
                jwks={'keys': [{'kid': 'k1', 'x5t#S256': _b64(hashlib.sha256(
                    self_signed.public_bytes(serialization.Encoding.DER)).digest()),
                    'x5c': [base64.b64encode(self_signed.public_bytes(serialization.Encoding.DER)).decode()]}]}),
            'not for verification': dict(token=self.token(), jwks={'keys': [dict(self.jwks['keys'][0], key_ops=['sign'])]}),
        }
        for name, case in cases.items():
            with self.subTest(name):
                mock.patch.stopall()
                mock.patch.object(pix_payload, '_ca_bundle', return_value=self.bundle.name).start()
                self.serve(case['token'], jwks=case.get('jwks'))
                with self.assertRaises(PixPayloadError):
                    pix_payload.resolve_dynamic(LOCATION)

    def test_a_charge_the_network_no_longer_offers_is_gone(self):
        for status in ('CONCLUIDA', 'REMOVIDA_PELO_PSP'):
            with self.subTest(status):
                mock.patch.stopall()
                mock.patch.object(pix_payload, '_ca_bundle', return_value=self.bundle.name).start()
                self.serve(self.token(dict(self.payload, status=status)))
                with self.assertRaises(PixPayloadError) as caught:
                    pix_payload.resolve_dynamic(LOCATION)
                self.assertTrue(caught.exception.gone)
        mock.patch.stopall()
        mock.patch.object(pix_payload, '_ca_bundle', return_value=self.bundle.name).start()
        self.serve('', status=410)
        with self.assertRaises(PixPayloadError) as caught:
            pix_payload.resolve_dynamic(LOCATION)
        self.assertTrue(caught.exception.gone)

    def test_payer_changeable_amounts_are_refused(self):
        for valor in ({'original': '0.00', 'modalidadeAlteracao': 1}, {'original': '10.00', 'modalidadeAlteracao': 1},
                      {'original': '10.00', 'retirada': {'saque': {'valor': '10.00'}}}, {'original': '10'}):
            with self.subTest(valor=valor), self.assertRaises(PixPayloadError):
                pix_payload._charge_from_payload(dict(self.payload, valor=valor), due_date=False)

    def test_due_date_charge_uses_final_amount_and_last_valid_day(self):
        data = dict(self.payload, valor={'original': '100.00', 'multa': '2.00', 'final': '102.00'},
                    calendario={'criacao': timezone.now().isoformat(), 'apresentacao': timezone.now().isoformat(),
                                'dataDeVencimento': '2030-01-10', 'validadeAposVencimento': 5},
                    recebedor={'nome': 'Loja SA', 'cnpj': '12345678000195'})
        charge = pix_payload._charge_from_payload(data, due_date=True)
        self.assertEqual(charge['amount'], Decimal('102.00'))
        self.assertEqual(charge['receiver_name'], 'Loja SA')
        # Due 2030-01-10 + 5 days, but the amount is computed for today only.
        today = timezone.now().astimezone(pix_payload.BRAZIL).date()
        self.assertEqual(charge['expires_at'].astimezone(pix_payload.BRAZIL).date(), today)

    def test_due_date_location_asks_for_todays_payment_date(self):
        calls = []

        def get(host, path, accept, deadline=None):
            calls.append(path)
            return 404, 'application/problem+json', b''
        mock.patch.object(pix_payload, 'https_get', side_effect=get).start()
        with self.assertRaises(PixPayloadError):
            pix_payload.resolve_dynamic(HOST + '/qr/cobv/abc123')
        self.assertRegex(calls[0], r'^/qr/cobv/abc123\?DPP=\d{4}-\d{2}-\d{2}$')

    def test_locations_that_are_not_a_public_pix_site_are_refused(self):
        for location in ('localhost/cob/1', '127.0.0.1/cob/1', 'pix.example.com:8443/cob/1',
                         'user@pix.example.com/cob/1', 'qrcode-h.bank.com.br/cob/1', 'a' * 78,
                         'pix.example.com/cob/1?x=1', 'pix example.com/cob/1'):
            with self.subTest(location), self.assertRaises(PixPayloadError):
                pix_payload._host_of(location)
        self.assertEqual(pix_payload._host_of(LOCATION), HOST)

    @override_settings(LOCAL_MONEY_PIX_ALLOW_HOMOLOGATION=True)
    def test_homologation_sites_only_when_allowed(self):
        self.assertEqual(pix_payload._host_of('qrcode-h.bank.com.br/cob/1'), 'qrcode-h.bank.com.br')

    def test_hosts_on_private_addresses_are_refused(self):
        for address in ('10.0.0.5', '169.254.169.254', '127.0.0.1', '::1', 'fd00::1'):
            with self.subTest(address), mock.patch.object(socket, 'getaddrinfo', return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]):
                with self.assertRaises(PixPayloadError):
                    pix_payload._public_address(HOST)
        with mock.patch.object(socket, 'getaddrinfo', return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', 443))]):
            with self.assertRaises(PixPayloadError):
                pix_payload._public_address(HOST)


class PixPayloadHardeningTests(SimpleTestCase):
    def stalled_server(self):
        """A TCP server that accepts and then never answers (a TLS handshake that drips)."""
        import threading
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(4)
        held = []

        def accept():
            try:
                while True:
                    held.append(server.accept()[0])
            except OSError:
                pass
        threading.Thread(target=accept, daemon=True).start()
        self.addCleanup(lambda: [c.close() for c in held] + [server.close()])
        return server.getsockname()[1]

    def test_a_site_that_stalls_is_cut_at_the_deadline_and_its_thread_ends(self):
        import threading
        import time as clock
        port = self.stalled_server()
        with mock.patch.object(pix_payload, '_public_address', return_value='127.0.0.1'), \
                mock.patch.object(pix_payload, 'PORT', port), \
                mock.patch.object(pix_payload, 'READ_TIMEOUT', 60):
            started = clock.monotonic()
            with self.assertRaises(PixPayloadError) as caught:
                pix_payload.https_get(HOST, '/x', 'application/jose', clock.monotonic() + 0.5)
            self.assertLess(clock.monotonic() - started, 2)
            self.assertTrue(caught.exception.temporary)
            clock.sleep(0.5)
            self.assertFalse([t for t in threading.enumerate() if t.name == 'pix-payload-fetch'])

    def test_slow_dns_is_inside_the_deadline(self):
        import time as clock
        with mock.patch.object(pix_payload, '_public_address', side_effect=lambda host: clock.sleep(2)):
            started = clock.monotonic()
            with self.assertRaises(PixPayloadError):
                pix_payload.https_get(HOST, '/x', 'application/jose', clock.monotonic() + 0.3)
            self.assertLess(clock.monotonic() - started, 1)

    def test_concurrent_reads_are_capped(self):
        with mock.patch.object(pix_payload, '_FETCH_SLOTS', mock.Mock(acquire=mock.Mock(return_value=False))):
            with self.assertRaises(PixPayloadError) as caught:
                pix_payload.https_get(HOST, '/x', 'application/jose')
        self.assertTrue(caught.exception.temporary)

    def test_unreadable_charges_are_refused_not_crashed(self):
        code = {'dynamic': True, 'location': LOCATION, 'merchant_name': 'X'}
        for error in (TypeError('unhashable'), RecursionError(), OverflowError(), ValueError('x')):
            with self.subTest(type(error).__name__), \
                    mock.patch.object(pix_payload, 'resolve_dynamic', side_effect=error):
                answer = pix_payload.validation(code)
            self.assertEqual(answer['status'], 'ERROR')

    def test_alg_of_the_wrong_type_is_refused(self):
        for alg in ([], {}, 5):
            token = '.'.join(_b64(json.dumps(part).encode()) for part in ({'alg': alg}, {})) + '.c2ln'
            with self.subTest(alg=alg), self.assertRaises(PixPayloadError):
                pix_payload._verify(token, HOST)

    def test_absurd_expiries_are_refused(self):
        base = {'status': 'ATIVA', 'txid': 'a' * 26, 'chave': 'k',
                'calendario': {'criacao': timezone.now().isoformat()}, 'valor': {'original': '1.00'}}
        for seconds in (10 ** 20, 400 * 86400, 0, -5):
            data = dict(base, calendario=dict(base['calendario'], expiracao=seconds))
            with self.subTest(seconds=seconds), self.assertRaises(PixPayloadError):
                pix_payload._charge_from_payload(data, due_date=False)
        data = dict(base, valor={'final': '1.00'},
                    calendario={'dataDeVencimento': '2030-01-01', 'validadeAposVencimento': 10 ** 9})
        with self.assertRaises(PixPayloadError):
            pix_payload._charge_from_payload(data, due_date=True)

    def test_a_due_date_amount_holds_only_for_today(self):
        data = {'status': 'ATIVA', 'txid': 'a' * 26, 'chave': 'k', 'valor': {'final': '102.00'},
                'calendario': {'dataDeVencimento': '2099-01-10', 'validadeAposVencimento': 5}}
        charge = pix_payload._charge_from_payload(data, due_date=True)
        today = timezone.now().astimezone(pix_payload.BRAZIL).date()
        self.assertEqual(charge['expires_at'].astimezone(pix_payload.BRAZIL).date(), today)
        self.assertEqual(charge['expires_at'].astimezone(pix_payload.BRAZIL).strftime('%H:%M:%S'), '23:59:59')

    def serve_once(self, payload):
        """A TCP server that answers one connection with raw bytes, then closes."""
        import threading
        server = socket.socket()
        server.bind(('127.0.0.1', 0))
        server.listen(1)

        def answer():
            try:
                conn, _ = server.accept()
                conn.recv(4096)
                if payload:
                    conn.sendall(payload)
                conn.close()
            except OSError:
                pass
        threading.Thread(target=answer, daemon=True).start()
        self.addCleanup(server.close)
        return server.getsockname()[1]

    def test_a_dropped_handshake_is_tried_again_not_refused(self):
        port = self.serve_once(b'')
        with mock.patch.object(pix_payload, '_public_address', return_value='127.0.0.1'), \
                mock.patch.object(pix_payload, 'PORT', port):
            with self.assertRaises(PixPayloadError) as caught:
                pix_payload.https_get(HOST, '/x', 'application/jose')
        self.assertTrue(caught.exception.temporary)

    def test_nat64_addresses_are_refused(self):
        with mock.patch.object(socket, 'getaddrinfo', return_value=[
                (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('64:ff9b::a00:5', 443, 0, 0))]):
            with self.assertRaises(PixPayloadError):
                pix_payload._public_address(HOST)

    def test_a_late_connection_after_the_deadline_frees_its_slot(self):
        import threading
        import time as clock
        port = self.stalled_server()
        before = pix_payload._FETCH_SLOTS._value

        def slow_dns(host):
            clock.sleep(0.8)  # the caller gives up at 0.3 s; the connect comes after
            return '127.0.0.1'
        with mock.patch.object(pix_payload, '_public_address', side_effect=slow_dns), \
                mock.patch.object(pix_payload, 'PORT', port), \
                mock.patch.object(pix_payload, 'READ_TIMEOUT', 60):
            with self.assertRaises(PixPayloadError):
                pix_payload.https_get(HOST, '/x', 'application/jose', clock.monotonic() + 0.3)
            clock.sleep(1.5)
        self.assertFalse([t for t in threading.enumerate() if t.name == 'pix-payload-fetch'])
        self.assertEqual(pix_payload._FETCH_SLOTS._value, before)

    def test_a_thread_that_cannot_start_releases_its_slot(self):
        before = pix_payload._FETCH_SLOTS._value
        with mock.patch('threading.Thread.start', side_effect=RuntimeError("can't start new thread")):
            with self.assertRaises(PixPayloadError) as caught:
                pix_payload.https_get(HOST, '/x', 'application/jose')
        self.assertTrue(caught.exception.temporary)
        self.assertEqual(pix_payload._FETCH_SLOTS._value, before)

    def test_one_site_never_takes_every_read(self):
        with mock.patch.dict(pix_payload._HOST_ACTIVE, {HOST: pix_payload.MAX_FETCHES_PER_HOST}):
            with self.assertRaises(PixPayloadError) as caught:
                pix_payload.https_get(HOST, '/x', 'application/jose')
        self.assertTrue(caught.exception.temporary)

    def test_a_site_that_stalled_fails_fast_for_a_while(self):
        import time as clock
        from django.core.cache import cache
        port = self.stalled_server()
        with mock.patch.object(pix_payload, '_public_address', return_value='127.0.0.1'), \
                mock.patch.object(pix_payload, 'PORT', port), \
                mock.patch.object(pix_payload, 'READ_TIMEOUT', 60):
            with self.assertRaises(PixPayloadError):
                pix_payload.https_get('slow.example.com', '/x', 'application/jose', clock.monotonic() + 0.3)
            started = clock.monotonic()
            with self.assertRaisesRegex(PixPayloadError, 'stalled recently'):
                pix_payload.https_get('slow.example.com', '/x', 'application/jose')
            self.assertLess(clock.monotonic() - started, 0.1)
        cache.delete(pix_payload._stalled_key('slow.example.com'))
