"""Google's redirect target. It only passes the result to the app; it reads and stores nothing."""
import secrets

from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET

from . import config

PAGE = '''<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Confío</title></head>
<body style="font-family:system-ui,sans-serif;padding:32px;color:#111827">
<p>Vuelve a Confío para terminar de conectar tu Gmail.</p>
<p><a id="open" href="confio://gmail-connect" style="color:#047857;font-weight:700">Abrir Confío</a></p>
<script nonce="{nonce}">
var target = 'confio://gmail-connect' + window.location.search;
document.getElementById('open').href = target;
history.replaceState(null, '', window.location.pathname);
window.location.href = target;
</script></body></html>'''


@require_GET
def gmail_connect_callback(request):
    if not config.configured():
        raise Http404
    nonce = secrets.token_urlsafe(16)
    response = HttpResponse(PAGE.replace('{nonce}', nonce))
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['Content-Security-Policy'] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; frame-ancestors 'none'")
    return response
