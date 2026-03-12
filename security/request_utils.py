import ast
import json


def extract_client_ip_from_meta(meta) -> str:
    """Prefer end-user IP headers from Cloudflare/proxies over edge proxy hops."""
    for header in ("HTTP_CF_CONNECTING_IP", "HTTP_TRUE_CLIENT_IP", "HTTP_X_REAL_IP"):
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
