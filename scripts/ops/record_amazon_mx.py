# Records what Amazon México's real pages contain, anonymously (no sign-in, a throwaway browser profile),
# through search -> product -> add to cart -> cart -> "Proceder al pago" (stops at the sign-in).
# For agent_tasks tests and the click judge. Prints how today's guard reads each page.
# Usage: ssh confio-prod 'cd /opt/confio && ./myvenv/bin/python manage.py shell' < scripts/ops/record_amazon_mx.py
import json
import re

from agent_tasks import guard
from agent_tasks.browsers.browserbase import Browserbase
from agent_tasks.cdp import Page
from agent_tasks.page import Reader

OUT = '/tmp/amazon_mx_record.json'
vendor = Browserbase()
profile = vendor.create_profile()
session = vendor.open(profile_id=profile, country='MX', seconds=600)
pages = []


def keep(name, snap, page):
    on_checkout = guard.is_checkout(snap)
    stage = guard.stage_of(snap, on_checkout=on_checkout)
    verdicts = []
    for element in snap.elements:
        label = str(element.get('label') or '')
        if re.search(r'carrito|pago|eliminar|guardar|proceder|comprar|continuar|cantidad|agregar', label, re.I):
            verdicts.append((label[:80], element.get('tag'), element.get('type'), element.get('role'),
                             guard.may_press(element, on_checkout=on_checkout, stage=stage, page=snap)))
    print(f'\n== {name}: {snap.url.split("?")[0]} on_checkout={on_checkout} stage={stage} '
          f'elements={len(snap.elements)}')
    for verdict in verdicts[:30]:
        print('   ', verdict)
    pages.append({'name': name, 'url': snap.url.split('?')[0], 'title': snap.title, 'text': snap.text[:6000],
                  'elements': snap.elements, 'on_checkout': on_checkout, 'stage': stage})


def find(snap, pattern, tag=None):
    for element in snap.elements:
        if re.search(pattern, str(element.get('label') or ''), re.I) and (tag is None or element.get('tag') == tag):
            return element
    return None


try:
    with Page(session.connect_url) as page:
        reader = Reader(page)
        page.goto('https://www.amazon.com.mx/s?k=chocolate+turin+magno')
        page.pump(3)
        results = reader.read()
        keep('search', results, page)
        product = next((e for e in results.elements if e.get('tag') == 'a' and '/dp/' in str(e.get('href') or '')),
                       None)
        if product is None:
            raise SystemExit('no product link found')
        page.goto(product['href'].split('?')[0])
        page.pump(3)
        snap = reader.read()
        keep('product', snap, page)
        add = find(snap, r'^agregar al carrito') or find(snap, r'agregar al carrito')
        print('add to cart:', add and add.get('label'), reader.click(add) if add else 'none')
        page.pump(4)
        snap = reader.read()
        keep('after_add', snap, page)
        page.goto('https://www.amazon.com.mx/gp/cart/view.html')
        page.pump(3)
        snap = reader.read()
        keep('cart', snap, page)
        proceed = find(snap, r'proceder al pago')
        print('proceed:', proceed and proceed.get('label'), reader.click(proceed) if proceed else 'none')
        page.pump(5)
        snap = reader.read()
        keep('after_proceed', snap, page)
finally:
    try:
        vendor.close(session.id)
    finally:
        vendor.delete_profile(profile)
    with open(OUT, 'w') as out:
        json.dump(pages, out, ensure_ascii=False)
    print('\nsaved', OUT, len(pages), 'pages; session closed, throwaway profile deleted')
