"""Time the admin dashboard pages and attribute their SQL to source lines (read-only).

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/admin_dashboard_profile.py

Calls each admin page view directly as the first active superuser inside a
READ ONLY transaction that is rolled back, so nothing can be written. Prints
total time, view vs render split, query count, and the slowest source lines.
Env PAGES (comma list of url names) narrows the run; PASSES=2 repeats it
to show warm-cache timings.
"""
import os
import time
import traceback
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.db import connection, transaction
from django.test import RequestFactory
from django.urls import reverse

from config.admin_dashboard import confio_admin_site as site

PAGES = [p for p in os.environ.get('PAGES', '').split(',') if p] or [
    'dashboard', 'dash_activation', 'dash_money', 'dash_invest', 'dash_community', 'dash_comprar',
    'dash_ops', 'dash_archive',
]
VIEW_FOR = {u.name: u.callback for u in site.get_urls() if getattr(u, 'name', None)}
user = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by('id').first()


class Recorder:
    def __init__(self):
        self.by_line = defaultdict(lambda: [0, 0.0])
        self.count = 0
        self.total = 0.0

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            elapsed = time.perf_counter() - start
            self.count += 1
            self.total += elapsed
            site_line = '?'
            for frame in reversed(traceback.extract_stack()):
                if '/site-packages/' in frame.filename or 'admin_dashboard_profile' in frame.filename:
                    continue
                if frame.filename.endswith(('.py', '.html')) and '/django/' not in frame.filename:
                    site_line = f"{os.path.basename(frame.filename)}:{frame.lineno}"
                    break
            bucket = self.by_line[site_line]
            bucket[0] += 1
            bucket[1] += elapsed


for name in PAGES * int(os.environ.get('PASSES', '1')):
    view = VIEW_FOR[name]
    request = RequestFactory().get(reverse(f'confio_admin:{name}'))
    request.user = user
    request.session = SessionStore()
    request.user.is_verified = lambda: True
    rec = Recorder()
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
        with connection.execute_wrapper(rec):
            t0 = time.perf_counter()
            response = view.__wrapped__(request) if hasattr(view, '__wrapped__') else view(request)
            t1 = time.perf_counter()
            if hasattr(response, 'render'):
                response.render()
            t2 = time.perf_counter()
        transaction.set_rollback(True)
    print(f"\n== {name}: total {t2 - t0:6.2f}s  view {t1 - t0:6.2f}s  render {t2 - t1:6.2f}s  "
          f"queries {rec.count}  sql {rec.total:6.2f}s  bytes {len(response.content)}")
    for line, (n, secs) in sorted(rec.by_line.items(), key=lambda kv: -kv[1][1])[:25]:
        print(f"   {secs:7.3f}s  {n:4d}q  {line}")
