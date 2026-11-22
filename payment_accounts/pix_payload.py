"""Read a Pix charge from the Pix network ourselves, at no provider cost.

A fixed-amount static BR Code carries everything in the code: key, amount,
txid. A dynamic BR Code carries a location (field 26.25); the payer fetches
it over HTTPS and gets a signed JWS with the charge: amount, expiry, status.
This module implements the payer's checks of the BCB "Manual de Segurança do
SFN, Vol. II: Segurança do Pix" (v6.01, 2026-11-09), section 4:

  4.1  HTTPS with TLS 1.2+, no protocol prefix in the code, host not ending in
       "-h" in production (homologation sites).
  4.2  JOSE header: alg RS/PS/ES 256+ (never HS*/none), x5t or x5t#S256, jku on
       the same site, kid. The JWK Set key matches kid and thumbprint, its
       x5c chain is valid and issued by a widely known CA.
  4.3  The site's TLS certificate names the host; the signing certificate is
       validated with its chain (RFC 5280); the payload is used only if the
       signature is valid.

One payer check is out of reach: the list of QR sites registered with the BCB
(CERTQRC) is published only to Pix participants (ARQ interface). Infinia, a
participant, resolves the same code again when it pays it out, so a site that
is not a registered PSP fails there, before any money reaches it.

The receiver name: BCB rules say a payer shows the name from DICT. That lookup
is paid (Infinia validation), so the name shown here is the one the charge
itself carries (cobv `recebedor`) or the QR's merchant name, always labelled
as such, never as a verified holder.

Every fetch is a server-side request to a URL from a user's QR code, so the
HTTP layer refuses anything that is not a public HTTPS host on port 443: the
address is resolved once, every address must be global, and the connection is
pinned to it (no DNS rebinding), with no redirects and small size and time
limits.
"""
import base64
import functools
import hashlib
import ipaddress
import json
import logging
import re
import socket
import ssl
import threading
from time import monotonic
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_BYTES = 64 * 1024
CONNECT_TIMEOUT, READ_TIMEOUT = 4.0, 5.0
FETCH_DEADLINE = 12.0  # seconds, a whole charge read (DNS, charge and keys)
MAX_CONCURRENT_FETCHES = 8
PORT = 443
MAX_EXPIRY_SECONDS = 366 * 86400
ALGORITHMS = {'RS256', 'RS384', 'RS512', 'PS256', 'PS384', 'PS512', 'ES256', 'ES384', 'ES512'}
BRAZIL = ZoneInfo('America/Sao_Paulo')
_HOST = re.compile(r'^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')
_LOCATION_CHARS = re.compile(r"^[A-Za-z0-9.\-_~/%]+$")


class PixPayloadError(Exception):
    """The charge cannot be read or trusted. `payable` False means the Pix
    network answered that it is gone (paid, expired, removed)."""

    def __init__(self, message, *, temporary=False, gone=False):
        super().__init__(message)
        self.temporary, self.gone = temporary, gone


# --------------------------------------------------------------------- HTTPS

def _host_of(location):
    if not location or len(location) > 77 or not _LOCATION_CHARS.fullmatch(location):
        raise PixPayloadError('invalid location')
    host = location.split('/', 1)[0].lower()
    if not _HOST.fullmatch(host):
        raise PixPayloadError('location host is not a fully qualified name')
    if host.endswith('-h') or host.split('.', 1)[0].endswith('-h'):
        if not getattr(settings, 'LOCAL_MONEY_PIX_ALLOW_HOMOLOGATION', False):
            raise PixPayloadError('homologation QR site')
    return host


def _public_address(host):
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PixPayloadError('host does not resolve', temporary=True) from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise PixPayloadError('host does not resolve', temporary=True)
    for address in addresses:
        ip = ipaddress.ip_address(address.split('%', 1)[0])
        # NAT64 (64:ff9b::/96) embeds an IPv4 address that may be private.
        if not ip.is_global or ip in ipaddress.ip_network('64:ff9b::/96'):
            raise PixPayloadError('host resolves to a non-public address')
    # IPv4 first: the pool takes the address as its host.
    return sorted(addresses, key=lambda a: (':' in a, a))[0]


_FETCH_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_FETCHES)
# One site (or whoever points QR codes at it) never takes every slot: at most
# MAX_FETCHES_PER_HOST at once, and a site that just stalled fails fast.
MAX_FETCHES_PER_HOST = 2
STALLED_HOST_SECONDS = 60
_HOST_GUARD = threading.Lock()
_HOST_ACTIVE = {}


def _host_slot(host, take):
    with _HOST_GUARD:
        count = _HOST_ACTIVE.get(host, 0)
        if take:
            if count >= MAX_FETCHES_PER_HOST:
                return False
            _HOST_ACTIVE[host] = count + 1
        elif count <= 1:
            _HOST_ACTIVE.pop(host, None)
        else:
            _HOST_ACTIVE[host] = count - 1
        return True


def _stalled_key(host):
    return 'pix-payload:stalled:' + hashlib.sha256(host.encode()).hexdigest()[:32]


def _recently_stalled(host):
    from django.core.cache import cache
    try:
        return bool(cache.get(_stalled_key(host)))
    except Exception:
        return False  # the cache is an optimization: never a reason to refuse


def _mark_stalled(host):
    from django.core.cache import cache
    try:
        cache.set(_stalled_key(host), 1, STALLED_HOST_SECONDS)
    except Exception:
        pass


def https_get(host, path_and_query, accept, deadline=None):
    """GET https://host/path over TLS 1.2+, pinned to a public address.

    Bounded in wall-clock time, DNS included, not only per socket read: a site
    (or its DNS) that answers one byte every few seconds must never hold a
    worker, a web request or a database lock. Everything runs in one thread
    that registers each socket as soon as it exists; at the deadline those
    sockets are shut down, so the thread ends too, and the caller gets a
    temporary error. At most MAX_CONCURRENT_FETCHES run at once.
    """
    import http.client
    deadline = deadline or (monotonic() + FETCH_DEADLINE)
    if not _host_slot(host, True):
        raise PixPayloadError('too many reads of this site at once', temporary=True)
    if not _FETCH_SLOTS.acquire(blocking=False):
        _host_slot(host, False)
        raise PixPayloadError('too many charge reads at once', temporary=True)
    outcome, sockets = {}, []
    guard = threading.Lock()
    cancelled = []  # set (non-empty) by the caller at the deadline

    def register(sock):
        # A socket created after the caller gave up is closed at once: no
        # thread may keep reading (and hold a slot) past the deadline.
        with guard:
            if cancelled:
                sock.close()
                raise TimeoutError('cancelled at the deadline')
            sockets.append(sock)

    def check():
        if cancelled or monotonic() >= deadline:
            raise TimeoutError('deadline reached')

    def fetch():
        try:
            if _recently_stalled(host):  # inside the deadline: a slow cache cannot hold the caller
                raise PixPayloadError('site stalled recently', temporary=True)
            address = _public_address(host)
            check()
            context = ssl.create_default_context(cafile=_ca_bundle())
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            raw = socket.create_connection((address, PORT), timeout=CONNECT_TIMEOUT)
            register(raw)
            raw.settimeout(READ_TIMEOUT)
            # wrap_socket takes over raw's descriptor: register the TLS socket
            # before its handshake, so a stalled handshake can be shut down too.
            tls = context.wrap_socket(raw, server_hostname=host, do_handshake_on_connect=False)
            register(tls)
            tls.do_handshake()  # checks the certificate and that it names host
            outcome['peer'] = tls.getpeercert(binary_form=True)
            check()
            connection = http.client.HTTPSConnection(host, PORT, context=context, timeout=READ_TIMEOUT)
            connection.sock = tls
            connection.putrequest('GET', path_and_query, skip_host=True, skip_accept_encoding=True)
            for name, value in (('Host', host), ('Accept', accept), ('Accept-Encoding', 'identity'),
                                ('User-Agent', 'Confio-Pix/1.0'), ('Connection', 'close')):
                connection.putheader(name, value)
            connection.endheaders()
            check()
            response = connection.getresponse()
            chunks, size = [], 0
            while size <= MAX_BYTES:
                if monotonic() >= deadline:
                    raise TimeoutError('deadline reached while reading')
                chunk = response.read(8192)  # raw bytes: nothing is decompressed
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size <= MAX_BYTES and response.length:
                # Closed before its declared length: a cut connection, not an answer.
                raise ConnectionError('truncated response')
            outcome['result'] = (response.status, response.getheader('Content-Type', '') or '', b''.join(chunks))
        except BaseException as exc:  # handed to the caller below
            outcome['error'] = exc
        finally:
            for sock in sockets:
                try:
                    sock.close()
                except OSError:
                    pass
            _FETCH_SLOTS.release()
            _host_slot(host, False)

    worker = threading.Thread(target=fetch, name='pix-payload-fetch', daemon=True)
    try:
        worker.start()
    except RuntimeError as exc:  # no thread available: a resource blip, not an answer
        _FETCH_SLOTS.release()
        _host_slot(host, False)
        raise PixPayloadError('fetch could not start', temporary=True) from exc
    worker.join(max(0.0, deadline - monotonic()))
    if worker.is_alive():
        with guard:
            cancelled.append(True)
            stalled = list(sockets)
        for sock in stalled:
            # Shutdown only: it wakes the read or handshake under way, which
            # fails and ends the thread. The owning thread closes its sockets
            # (closing here could free a descriptor it is still using).
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        # Remembered off the caller's thread: a slow cache cannot hold it.
        threading.Thread(target=_mark_stalled, args=(host,), name='pix-payload-mark', daemon=True).start()
        raise PixPayloadError('fetch took too long', temporary=True)
    error = outcome.get('error')
    if isinstance(error, PixPayloadError):
        raise error
    if isinstance(error, ssl.SSLCertVerificationError):
        # A certificate that is invalid, expired or for another host does not
        # heal by asking again: the site cannot be trusted. Other TLS errors
        # (a dropped handshake) are network blips and are tried again.
        raise PixPayloadError(f'TLS check failed: {type(error).__name__}') from error
    if isinstance(error, (OSError, TimeoutError, http.client.IncompleteRead)):
        raise PixPayloadError(f'fetch failed: {type(error).__name__}', temporary=True) from error
    if error is not None:
        raise PixPayloadError(f'fetch failed: {type(error).__name__}') from error
    if 'result' not in outcome:
        raise PixPayloadError('fetch took too long', temporary=True)
    status, content_type, body = outcome['result']
    if len(body) > MAX_BYTES:
        raise PixPayloadError('response too large')
    # The site's own certificate, for the caller that wants to know who the
    # site belongs to (pix_participants): kept per calling thread.
    _PEER.certificate = outcome.get('peer')
    return status, content_type, body


_PEER = threading.local()


def last_site_certificate():
    """The TLS certificate (DER) of the site the last https_get on this
    thread reached, or None."""
    return getattr(_PEER, 'certificate', None)


@functools.lru_cache(maxsize=4)
def _trusted_roots(bundle):
    import warnings
    from cryptography import x509
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')  # certifi carries a root with a negative serial
        return tuple(x509.load_pem_x509_certificates(open(bundle, 'rb').read()))


def _ca_bundle():
    import certifi
    return certifi.where()


# ----------------------------------------------------------------------- JWS

def _b64(segment):
    try:
        return base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))
    except (ValueError, TypeError) as exc:
        raise PixPayloadError('malformed JWS') from exc


def _thumbprints(der):
    def enc(digest):
        return base64.urlsafe_b64encode(digest).rstrip(b'=').decode()
    return {'x5t': enc(hashlib.sha1(der).digest()), 'x5t#S256': enc(hashlib.sha256(der).digest())}


def _signing_certificate(header, jwks, host):
    """The certificate whose key signed the JWS, after the manual's checks."""
    from cryptography import x509
    from cryptography.x509.verification import PolicyBuilder, Store
    kid = header.get('kid')
    keys = jwks.get('keys') if isinstance(jwks, dict) else None
    if not kid or not isinstance(keys, list):
        raise PixPayloadError('JWK Set without keys or JWS without kid')
    matches = [k for k in keys if isinstance(k, dict) and k.get('kid') == kid]
    if len(matches) != 1:
        raise PixPayloadError('kid does not identify one key')
    jwk = matches[0]
    if jwk.get('key_ops') is not None and 'verify' not in (jwk.get('key_ops') or []):
        raise PixPayloadError('key is not for verification')
    chain = jwk.get('x5c')
    if not isinstance(chain, list) or not chain:
        raise PixPayloadError('key without certificate chain')
    try:
        ders = [base64.b64decode(item, validate=True) for item in chain]
        certificates = [x509.load_der_x509_certificate(der) for der in ders]
    except (ValueError, TypeError) as exc:
        raise PixPayloadError('malformed certificate chain') from exc
    prints = _thumbprints(ders[0])
    named = [name for name in ('x5t', 'x5t#S256') if header.get(name)]
    if not named or any(header[name] != prints[name] or jwk.get(name, header[name]) != prints[name]
                        for name in named):
        raise PixPayloadError('certificate thumbprint does not match')
    store = Store(list(_trusted_roots(_ca_bundle())))
    now = timezone.now().astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
    verifier = PolicyBuilder().store(store).time(now).build_server_verifier(
        x509.DNSName(host))
    try:
        verifier.verify(certificates[0], certificates[1:])
    except Exception as exc:  # cryptography raises VerificationError and friends
        raise PixPayloadError('signing certificate is not valid for the QR site') from exc
    return certificates[0], jwk


def _verify(token, host, deadline=None):
    parts = token.split('.')
    if len(parts) != 3 or not all(parts):
        raise PixPayloadError('response is not a compact JWS')
    try:
        header = json.loads(_b64(parts[0]))
    except ValueError as exc:
        raise PixPayloadError('malformed JWS header') from exc
    if not isinstance(header, dict) or not isinstance(header.get('alg'), str) or header['alg'] not in ALGORITHMS:
        raise PixPayloadError('signature algorithm not allowed')
    jku = header.get('jku')
    if not isinstance(jku, str) or not jku.lower().startswith('https://'):
        raise PixPayloadError('jku must be https')
    jku_host, _, jku_path = jku[len('https://'):].partition('/')
    if jku_host.lower() != host:
        raise PixPayloadError('jku is not on the QR site')
    if not re.fullmatch(r"/[A-Za-z0-9.\-_~/%]*", '/' + jku_path):
        raise PixPayloadError('invalid jku path')
    status, _, body = https_get(host, '/' + jku_path, 'application/json', deadline)
    if status != 200:
        raise PixPayloadError(f'JWK Set returned {status}', temporary=status >= 500 or status in (408, 429))
    try:
        jwks = json.loads(body)
    except ValueError as exc:
        raise PixPayloadError('JWK Set is not JSON') from exc
    certificate, _ = _signing_certificate(header, jwks, host)
    import jwt
    try:
        return jwt.api_jws.PyJWS().decode(token, key=certificate.public_key(), algorithms=[header['alg']])
    except jwt.exceptions.PyJWTError as exc:
        raise PixPayloadError('invalid signature') from exc


# ------------------------------------------------------------------- charges

def _money(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,10}\.\d{2}', value):
        raise PixPayloadError('amount is not in cents')
    amount = Decimal(value)
    if amount <= 0:
        raise PixPayloadError('amount is not positive')
    return amount


def _when(value):
    from django.utils.dateparse import parse_datetime
    try:
        stamp = parse_datetime(str(value or ''))
    except ValueError:
        stamp = None
    if stamp is None:
        raise PixPayloadError('charge without a valid creation time')
    return stamp if timezone.is_aware(stamp) else stamp.replace(tzinfo=ZoneInfo('UTC'))


def _charge_from_payload(data, *, due_date):
    if not isinstance(data, dict):
        raise PixPayloadError('payload is not an object')
    status = data.get('status')
    if status != 'ATIVA':
        raise PixPayloadError(f'charge is {status}', gone=True)
    valor, calendario = data.get('valor') or {}, data.get('calendario') or {}
    if not isinstance(valor, dict) or not isinstance(calendario, dict):
        raise PixPayloadError('malformed charge')
    if due_date or 'dataDeVencimento' in calendario:
        amount = _money(valor.get('final'))
        try:
            due = datetime.strptime(str(calendario.get('dataDeVencimento')), '%Y-%m-%d').date()
            days = int(calendario.get('validadeAposVencimento', 30))
        except (TypeError, ValueError) as exc:
            raise PixPayloadError('due date charge without a valid due date') from exc
        if not 0 <= days <= 366:
            raise PixPayloadError('invalid validity')
        # The last day it can be paid, to its last second in Brazil. Weekend
        # and holiday extensions are ignored: an earlier expiry is the safe side.
        expires = datetime.combine(due + timedelta(days=days), time(23, 59, 59), tzinfo=BRAZIL)
        # valor.final is computed for the payment date asked (DPP = today in
        # Brazil): it holds until the end of today, never later.
        today_end = datetime.combine(timezone.now().astimezone(BRAZIL).date(), time(23, 59, 59), tzinfo=BRAZIL)
        expires = min(expires, today_end)
    else:
        # Payer-changed amounts (saque/troco) and cash-out are not payments.
        if str(valor.get('modalidadeAlteracao', 0)) not in ('0', 'None') or valor.get('retirada'):
            raise PixPayloadError('charge lets the payer change the amount')
        amount = _money(valor.get('original'))
        try:
            seconds = int(calendario.get('expiracao', 86400))
        except (TypeError, ValueError) as exc:
            raise PixPayloadError('invalid expiry') from exc
        if not 0 < seconds <= MAX_EXPIRY_SECONDS:
            raise PixPayloadError('invalid expiry')
        expires = _when(calendario.get('criacao')) + timedelta(seconds=seconds)
    recebedor = data.get('recebedor') if isinstance(data.get('recebedor'), dict) else {}
    name = str(recebedor.get('nomeFantasia') or recebedor.get('nome') or '').strip()
    return {'amount': amount, 'expires_at': expires, 'txid': str(data.get('txid') or '')[:35],
            'key': str(data.get('chave') or '')[:77], 'receiver_name': name[:200],
            'revision': data.get('revisao')}


def resolve_dynamic(location):
    """The charge behind a dynamic BR Code's location, verified as the manual asks."""
    host = _host_of(location)
    path = location[len(host):] or '/'
    due_date = '/cobv/' in path.lower()
    query = ''
    if due_date:
        # Data de Pagamento Pretendida: today in Brazil (codMun is optional).
        query = '?DPP=' + timezone.now().astimezone(BRAZIL).date().isoformat()
    deadline = monotonic() + FETCH_DEADLINE  # one budget for the charge and its keys
    _PEER.certificate = None
    status, content_type, body = https_get(host, path + query, 'application/jose', deadline)
    site_certificate = last_site_certificate()
    if status in (404, 410):
        raise PixPayloadError(f'charge returned {status}', gone=True)
    if status != 200:
        raise PixPayloadError(f'charge returned {status}', temporary=status >= 500 or status in (408, 429))
    try:
        token = body.decode('ascii').strip()
    except UnicodeDecodeError as exc:
        raise PixPayloadError('response is not a compact JWS') from exc
    payload = _verify(token, host, deadline)
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise PixPayloadError('payload is not JSON') from exc
    from . import pix_participants
    return dict(_charge_from_payload(data, due_date=due_date), domain=host,
                site=pix_participants.site_identity(site_certificate))


def validation(code):
    """A charge in the shape local_money keeps for a recipient check.

    status: SUCCESSFUL (payable), ERROR (the network says it is gone or it
    cannot be trusted), TEMPORARY_FAILURE (try again).
    """
    checked = timezone.now().isoformat()
    base = {'id': '', 'holder_document': '', 'checked_at': checked, 'source': 'pix_network'}
    merchant = ' '.join(str(code.get('merchant_name') or '').split())[:255]
    if not code['dynamic']:
        return dict(base, status='SUCCESSFUL', holder_name=merchant, holder_source='qr', institution='',
                    charge={'type': 'static', 'amount': code['amount'], 'expiration': '', 'txid': code['txid']})
    try:
        charge = resolve_dynamic(code['location'])
    except PixPayloadError as exc:
        return dict(base, status='TEMPORARY_FAILURE' if exc.temporary else 'ERROR', holder_name='',
                    institution='', failure=str(exc)[:200], gone=exc.gone)
    except Exception as exc:  # malformed input from an untrusted site: refuse, never crash
        return dict(base, status='ERROR', holder_name='', institution='',
                    failure=f'unreadable charge: {type(exc).__name__}'[:200], gone=False)
    # The signed payload names the receiver only for due-date charges;
    # otherwise the QR's own (unsigned) merchant name, labelled as such.
    name = charge['receiver_name'] or merchant
    # Which Pix participant hosts this charge, when public data can tell
    # (never who the receiver is: that is the DICT name).
    host_institution = None
    try:
        from . import pix_participants
        host_institution = pix_participants.institution_for(charge['domain'], charge.get('site'))
    except Exception:  # noqa: BLE001 - unknown host institution: the charge reads as unverified
        logger.warning('Pix host institution lookup failed', exc_info=True)
    return dict(base, status='SUCCESSFUL', holder_name=name,
                holder_source='charge' if charge['receiver_name'] else 'qr',
                institution=charge['domain'], host_institution=host_institution,
                charge={'type': 'dynamic', 'amount': str(charge['amount']),
                        'expiration': charge['expires_at'].isoformat(), 'txid': charge['txid'],
                        'revision': charge['revision']})
