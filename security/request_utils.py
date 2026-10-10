import ast
import ipaddress
import json

# Cloudflare's published edge ranges (https://www.cloudflare.com/ips/).
CLOUDFLARE_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    '173.245.48.0/20', '103.21.244.0/22', '103.22.200.0/22', '103.31.4.0/22',
    '141.101.64.0/18', '108.162.192.0/18', '190.93.240.0/20', '188.114.96.0/20',
    '197.234.240.0/22', '198.41.128.0/17', '162.158.0.0/15', '104.16.0.0/13',
    '104.24.0.0/14', '172.64.0.0/13', '131.0.72.0/22',
    '2400:cb00::/32', '2606:4700::/32', '2803:f800::/32', '2405:b500::/32',
    '2405:8100::/32', '2a06:98c0::/29', '2c0f:f248::/32',
))


def came_through_cloudflare(meta) -> bool:
    """True when the TCP peer is a Cloudflare edge. nginx sets X-Real-IP to
    $remote_addr, replacing anything the client sent; without nginx (dev,
    tests) REMOTE_ADDR is the peer. A request that reaches the origin
    directly can forge CF-Connecting-IP and CF-IPCountry, but not this."""
    meta = meta or {}
    peer = (meta.get('HTTP_X_REAL_IP') or meta.get('REMOTE_ADDR') or '').strip()
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in CLOUDFLARE_NETWORKS)


def extract_client_ip_from_meta(meta) -> str:
    """The end user's IP. Cloudflare's client-IP headers are honoured only
    when the peer IS Cloudflare: from anyone else they are forgeable, and
    the IP picked here feeds bans, fraud links and IP residence. Otherwise
    the nginx-set X-Real-IP (the real peer) wins."""
    headers = ("HTTP_CF_CONNECTING_IP", "HTTP_TRUE_CLIENT_IP") if came_through_cloudflare(meta) else ()
    for header in headers + ("HTTP_X_REAL_IP",):
        value = (meta or {}).get(header, "")
        if value:
            return value.strip()

    x_forwarded_for = (meta or {}).get("HTTP_X_FORWARDED_FOR", "")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return (meta or {}).get("REMOTE_ADDR", "").strip()


def extract_device_id(device_fingerprint):
    """Accept dicts, valid JSON, legacy Python-dict strings, and raw stable hashes."""
    if isinstance(device_fingerprint, dict):
        return device_fingerprint.get("deviceId")

    if not isinstance(device_fingerprint, str):
        return None

    raw = device_fingerprint.strip()
    if not raw:
        return None

    parsed = None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return raw

    if isinstance(parsed, dict):
        return parsed.get("deviceId")

    if isinstance(parsed, str) and parsed.strip():
        return parsed.strip()

    return None
