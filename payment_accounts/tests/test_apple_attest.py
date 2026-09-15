import base64
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import nullcontext
import json
import cbor2
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature
from django.test import SimpleTestCase, override_settings
from payment_accounts import apple_attest as apple


def encode(obj):
    return base64.b64encode(cbor2.dumps(obj)).decode()


@override_settings(BREB_IOS_APP_ID='ABCDEFGHIJ.com.Confio.Confio', BREB_IOS_APP_ATTEST_ENABLED=True)
class AppleAttestTests(SimpleTestCase):
    def setUp(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.raw = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.key_bytes = hashlib.sha256(self.raw).digest()
        self.key_id = base64.b64encode(self.key_bytes).decode()
        self.rp = hashlib.sha256(b'ABCDEFGHIJ.com.Confio.Confio').digest()
        self.client_hash = hashlib.sha256(b'challenge.location').digest()
        self.pem = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def assertion(self, counter=1, rp=None, flags=b'\x01', extra=b''):
        auth = (rp or self.rp) + flags + counter.to_bytes(4, 'big') + extra
        return encode({'authenticatorData': auth, 'signature': self.key.sign(hashlib.sha256(auth+self.client_hash).digest(), ec.ECDSA(hashes.SHA256()))})

    def test_assertion_signature_binding_and_counter(self):
        token = self.assertion(7)
        self.assertEqual(apple.validate_assertion(token, self.pem, 6, self.client_hash), 7)
        with self.assertRaises(ValueError): apple.validate_assertion(token, self.pem, 7, self.client_hash)
        with self.assertRaises(InvalidSignature): apple.validate_assertion(token, self.pem, 0, b'x'*32)
        with self.assertRaises(ValueError): apple.validate_assertion(self.assertion(rp=b'x'*32), self.pem, 0, self.client_hash)

    def test_device_assertion_with_at_flag(self):
        # A real iPhone's assertion sets the AT bit (0x40) with no credential
        # data (seen on an iPhone SE, 2026-09-15): accepted, but still exactly
        # 37 bytes; anything appended is refused.
        self.assertEqual(apple.validate_assertion(self.assertion(3, flags=b'\x41'), self.pem, 0, self.client_hash), 3)
        with self.assertRaises(ValueError):
            apple.validate_assertion(self.assertion(3, flags=b'\x41', extra=b'\x00' * 18), self.pem, 0, self.client_hash)

    def certificate(self, subject, issuer, public, signer, ca, nonce=None, expired=False):
        now = datetime.now(timezone.utc)
        builder = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(public).serial_number(x509.random_serial_number()) \
            .not_valid_before(now-timedelta(days=2)).not_valid_after(now+timedelta(days=-1 if expired else 1)) \
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        if nonce is not None:
            builder = builder.add_extension(x509.UnrecognizedExtension(x509.ObjectIdentifier('1.2.840.113635.100.8.2'), b'\x30\x24\xa1\x22\x04\x20'+nonce), critical=False)
        return builder.sign(signer, hashes.SHA256())

    def attestation(self, development=False, expired=False):
        root_key = ec.generate_private_key(ec.SECP256R1())
        inter_key = ec.generate_private_key(ec.SECP256R1())
        name = lambda s: x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, s)])
        root = self.certificate(name('root'), name('root'), root_key.public_key(), root_key, True)
        inter = self.certificate(name('inter'), name('root'), inter_key.public_key(), root_key, True)
        auth = self.rp + b'\x41' + b'\0'*4 + (b'appattestdevelop' if development else b'appattest'+b'\0'*7) + b'\x00\x20' + self.key_bytes
        auth += cbor2.dumps({1: 2, 3: -7, -1: 1, -2: self.raw[1:33], -3: self.raw[33:]})
        leaf = self.certificate(name('device'), name('inter'), self.key.public_key(), inter_key, False, hashlib.sha256(auth+self.client_hash).digest(), expired=expired)
        token = encode({'fmt': 'apple-appattest', 'authData': auth, 'attStmt': {'x5c': [c.public_bytes(serialization.Encoding.DER) for c in (leaf, inter)], 'receipt': b'receipt'}})
        return token, root.public_bytes(serialization.Encoding.PEM)

    def test_attestation_chain_and_registration_binding(self):
        token, root = self.attestation()
        with patch.object(apple.Path, 'read_bytes', return_value=root):
            public, receipt = apple.validate_attestation(token, self.key_id, self.client_hash)
            self.assertEqual(public, self.pem)
            self.assertEqual(receipt, b'receipt')
            with self.assertRaises(ValueError): apple.validate_attestation(token, self.key_id, b'x'*32)
            with self.assertRaises(ValueError): apple.validate_attestation(token, base64.b64encode(b'x'*32).decode(), self.client_hash)
        # The test root is not Apple's pinned root; no arbitrary trust anchor.
        with self.assertRaises(Exception): apple.validate_attestation(token, self.key_id, self.client_hash)

    def test_development_attestations_rejected(self):
        token, root = self.attestation(development=True)
        with patch.object(apple.Path, 'read_bytes', return_value=root), self.assertRaises(ValueError):
            apple.validate_attestation(token, self.key_id, self.client_hash)

    def test_expired_certificate_rejected(self):
        token, root = self.attestation(expired=True)
        with patch.object(apple.Path, 'read_bytes', return_value=root), self.assertRaises(apple.crypto.X509StoreContextError):
            apple.validate_attestation(token, self.key_id, self.client_hash)

    def test_signature_over_raw_data_rejected(self):
        # The device signs the SHA-256 nonce, never the raw bytes.
        auth = self.rp + b'\x41' + (1).to_bytes(4, 'big')
        token = encode({'authenticatorData': auth, 'signature': self.key.sign(auth + self.client_hash, ec.ECDSA(hashes.SHA256()))})
        with self.assertRaises(InvalidSignature):
            apple.validate_assertion(token, self.pem, 0, self.client_hash)

    def test_forged_assertion_rejected(self):
        obj = cbor2.loads(base64.b64decode(self.assertion()))
        other_key = ec.generate_private_key(ec.SECP256R1())
        obj['signature'] = other_key.sign(hashlib.sha256(obj['authenticatorData'] + self.client_hash).digest(), ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(InvalidSignature):
            apple.validate_assertion(encode(obj), self.pem, 0, self.client_hash)

    def test_signed_distribution_extensions(self):
        for category in (1, 2, 3, 4, True, '2'):
            for version in ('42', ''):
                with self.subTest(category=category, version=version):
                    auth = self.rp + b'\x81' + (1).to_bytes(4, 'big') + cbor2.dumps({
                        'apple_validation_category_01': category, 'apple_bundle_version_01': version})
                    token = encode({'authenticatorData': auth, 'signature': self.key.sign(hashlib.sha256(auth+self.client_hash).digest(), ec.ECDSA(hashes.SHA256()))})
                    if type(category) is int and category in (2, 4) and version:
                        self.assertEqual(apple.validate_assertion(token, self.pem, 0, self.client_hash), 1)
                    else:
                        with self.assertRaises(ValueError):
                            apple.validate_assertion(token, self.pem, 0, self.client_hash)

    def test_malformed_and_trailing_input(self):
        for token in ('!', 'A'*24001, base64.b64encode(cbor2.dumps({})+b'x').decode()):
            with self.assertRaises(Exception): apple.validate_attestation(token, self.key_id, self.client_hash)

    def test_user_binding_revocation_and_counter_persistence(self):
        from payment_accounts.models import BrebAppAttestKey
        from unittest.mock import Mock
        row = Mock(public_key=self.pem, counter=0)
        envelope = json.dumps({'mode': 'assertion', 'keyId': self.key_id, 'object': self.assertion(1)})
        with patch.object(apple.transaction, 'atomic', return_value=nullcontext()), \
             patch.object(BrebAppAttestKey.objects, 'select_for_update') as locked:
            locked.return_value.get.return_value = row
            apple.verify(SimpleNamespace(user_id=19), envelope, self.client_hash)
            locked.return_value.get.assert_called_once_with(key_id=self.key_id, user_id=19, revoked=False)
            self.assertEqual(row.counter, 1)
            row.save.assert_called_once_with(update_fields=['counter'])
            with self.assertRaises(ValueError): apple.verify(SimpleNamespace(user_id=19), envelope, self.client_hash)
