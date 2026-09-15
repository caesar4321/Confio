"""Direct, production-only App Attest. Independent of Firebase enforcement.

Protocol: SHA256(challenge + '.' + exact_location_json) is clientDataHash.
Registration and assertion use that same binding. No client-supplied roots.
"""
import base64
import hashlib
import io
import json
from pathlib import Path

import cbor2
from OpenSSL import crypto
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.db import transaction


def configured():
    app_id = getattr(settings, 'BREB_IOS_APP_ID', '')
    return bool(getattr(settings, 'BREB_IOS_APP_ATTEST_ENABLED', False)
                and app_id.endswith('.com.Confio.Confio') and len(app_id.split('.')[0]) == 10)


def _decode(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Invalid encoding')
    return base64.b64decode(value, validate=True)


def _cbor(data):
    stream = io.BytesIO(data)
    result = cbor2.CBORDecoder(stream).decode()
    if stream.read():
        raise ValueError('Trailing CBOR')
    return result


def _auth(data, registration):
    if not isinstance(data, bytes) or len(data) < 37:
        raise ValueError('Invalid authenticator data')
    expected = hashlib.sha256(settings.BREB_IOS_APP_ID.encode()).digest()
    if data[:32] != expected:
        raise ValueError('Wrong app')
    flags = data[32]
    counter = int.from_bytes(data[33:37], 'big')
    offset = 37
    credential = None
    cose = None
    if registration:
        if not flags & 0x40 or len(data) < 87 or counter != 0 or data[37:53] != b'appattest'+b'\0'*7:
            raise ValueError('Not production attestation')
        length = int.from_bytes(data[53:55], 'big')
        if length != 32:
            raise ValueError('Wrong credential length')
        credential = data[55:87]
        stream = io.BytesIO(data[87:])
        cose = cbor2.CBORDecoder(stream).decode()
        offset = 87 + stream.tell()
    # An assertion never carries credential data, but real devices still set
    # the AT bit (0x40) in its flags (seen on an iPhone SE, 2026-09-15). The bit
    # is ignored; the exact-length check below still refuses any extra payload.
    if flags & 0x80:
        extensions = _cbor(data[offset:])
        if not isinstance(extensions, dict):
            raise ValueError('Invalid extensions')
        category = extensions.get('apple_validation_category_01', extensions.get('validationCategory'))
        if type(category) is not int or category not in (2, 4):
            raise ValueError('Not Store/TestFlight distribution')
        version = extensions.get('apple_bundle_version_01', extensions.get('bundleVersion'))
        if not isinstance(version, str) or not version.strip():
            raise ValueError('Missing build version')
    elif len(data) != offset:
        raise ValueError('Trailing authenticator data')
    return counter, credential, cose


def validate_attestation(encoded, key_id, client_hash):
    obj = _cbor(_decode(encoded, 24000))
    if obj['fmt'] != 'apple-appattest':
        raise ValueError('Wrong format')
    chain = obj['attStmt']['x5c']
    if not isinstance(chain, list) or not 2 <= len(chain) <= 3:
        raise ValueError('Invalid chain')
    certificates = [crypto.load_certificate(crypto.FILETYPE_ASN1, item) for item in chain]
    store = crypto.X509Store()
    root = (Path(__file__).parent / 'data/apple_app_attestation_root.pem').read_bytes()
    store.add_cert(crypto.load_certificate(crypto.FILETYPE_PEM, root))
    crypto.X509StoreContext(store, certificates[0], certificates[1:]).verify_certificate()
    leaf = certificates[0].to_cryptography()
    auth = obj['authData']
    _, credential, cose = _auth(auth, True)
    nonce = hashlib.sha256(auth + client_hash).digest()
    extension = leaf.extensions.get_extension_for_oid(x509.ObjectIdentifier('1.2.840.113635.100.8.2')).value.value
    # Canonical DER SEQUENCE { [1] { OCTET STRING (32 bytes) } }.
    if extension != b'\x30\x24\xa1\x22\x04\x20' + nonce:
        raise ValueError('Wrong attestation challenge')
    public = leaf.public_key()
    if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
        raise ValueError('Wrong key algorithm')
    raw = public.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    key = _decode(key_id, 44)
    if len(key) != 32 or credential != key or hashlib.sha256(raw).digest() != key:
        raise ValueError('Wrong key ID')
    if cose != {1: 2, 3: -7, -1: 1, -2: raw[1:33], -3: raw[33:]}:
        raise ValueError('Wrong credential key')
    receipt = obj['attStmt']['receipt']
    if not isinstance(receipt, bytes) or not receipt:
        raise ValueError('Missing receipt')
    return public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), receipt


def validate_assertion(encoded, public_pem, counter, client_hash):
    obj = _cbor(_decode(encoded, 8000))
    auth = obj['authenticatorData']
    next_counter, _, _ = _auth(auth, False)
    if next_counter <= counter:
        raise ValueError('Replayed assertion')
    public = serialization.load_pem_public_key(public_pem.encode())
    # Apple signs nonce = SHA256(authenticatorData || clientDataHash), and
    # ECDSA-SHA256 hashes that nonce again (Apple, "Validating apps that
    # connect to your server", assertion step 1-2).
    nonce = hashlib.sha256(auth + client_hash).digest()
    public.verify(obj['signature'], nonce, ec.ECDSA(hashes.SHA256()))
    return next_counter


def verify(owner, token, client_hash):
    from .models import BrebAppAttestKey
    if not configured():
        raise ValueError('iOS verification unavailable')
    envelope = json.loads(token)
    key_id = envelope['keyId']
    raw_id = _decode(key_id, 44)
    if len(raw_id) != 32 or base64.b64encode(raw_id).decode() != key_id:
        raise ValueError('Invalid key')
    if envelope['mode'] == 'attestation':
        public, receipt = validate_attestation(envelope['object'], key_id, client_hash)
        # A duplicate registration must never reset an assertion counter or
        # reassign a key to another user. Unique PK makes races fail closed.
        BrebAppAttestKey.objects.create(key_id=key_id, user_id=owner.user_id, public_key=public, receipt=receipt)
    elif envelope['mode'] == 'assertion':
        with transaction.atomic():
            row = BrebAppAttestKey.objects.select_for_update().get(key_id=key_id, user_id=owner.user_id, revoked=False)
            row.counter = validate_assertion(envelope['object'], row.public_key, row.counter, client_hash)
            row.save(update_fields=['counter'])
    else:
        raise ValueError('Unknown assertion mode')
