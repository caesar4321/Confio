# Read-only: every page the shopping agent recorded (AgentTask.trace), through code's own layers:
# the click floor (guard.hard_refusal) and the browser's never-load filter (guard.account_address).
# Lists what code would refuse on real pages, so a wrong refusal is found before a person meets it.
# Usage: ssh confio-prod 'cd /opt/confio && ./myvenv/bin/python manage.py shell' < scripts/ops/replay_agent_traces.py
from types import SimpleNamespace

from agent_tasks import guard
from agent_tasks.models import AgentTask

seen_pages = set()
for task in AgentTask.objects.exclude(trace=[]).order_by('-created_at')[:40]:
    for page in task.trace or []:
        key = (page['url'], tuple(e.get('label', '') for e in page['elements'][:20]))
        if key in seen_pages:
            continue
        seen_pages.add(key)
        elements = [{**e, 'href': (f"https://{page['url'].split('/')[0]}{e['href']}" if e.get('href', '').startswith('/')
                                   else e.get('href', '')),
                     'checked': e.get('checked') == 'True', 'disabled': e.get('disabled') == 'True',
                     'on_screen': e.get('on_screen') != 'False'} for e in page['elements']]
        snap = SimpleNamespace(url=f"https://{page['url']}", title=page['title'], text=page['text'], elements=elements)
        on_checkout = guard.is_checkout(snap) if hasattr(snap, 'elements') else False
        refused = []
        for element in elements:
            if element.get('disabled'):
                continue
            reason = guard.hard_refusal(element, on_checkout=on_checkout, page=snap)
            nav = element.get('tag') == 'a' and element.get('href') and guard.account_address(element['href'])
            if reason or nav:
                refused.append((reason or 'never-load', str(element.get('label', ''))[:70], element.get('href', '')[-50:]))
        print(f"\n== {page['url'][:90]}  ({len(elements)} controls, {len(refused)} refused by code)")
        for row in refused[:25]:
            print('   ', row)
