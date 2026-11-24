# Read-only: a user's recent shopping-agent tasks and assistant turns about them.
# Usage: ssh confio-prod 'cd /opt/confio && USERNAME=<username> ./myvenv/bin/python manage.py shell' < scripts/ops/agent_tasks_user.py
import os

from django.contrib.auth import get_user_model

from agent_tasks.models import AgentTask

user = get_user_model().objects.get(username=os.environ['USERNAME'])
print('user', user.pk, 'country', getattr(user, 'country', ''))
for task in AgentTask.objects.filter(user=user).order_by('-created_at')[:6]:
    print('\n== task', task.internal_id, task.created_at, task.site, task.country, task.state, task.reason,
          'phase', task.phase, 'checkout_at', task.checkout_at, 'app', task.app_version)
    print('   goal:', (task.goal or '')[:120])
    print('   order:', {k: v for k, v in (task.order or {}).items() if k not in ('image',)})
    print('   counts:', task.counts, 'options:', len(task.options or []))
    for entry in (task.history or [])[-25:]:
        print('   -', str(entry.get('did'))[:90], '=>', str(entry.get('result'))[:140])

from assistant.models import AssistantTurn

print('\n== assistant turns (newest first)')
for turn in AssistantTurn.objects.filter(user=user).select_related('user_message', 'reply_message') \
        .order_by('-created_at')[:int(os.environ.get('TURNS', '10'))]:
    said = getattr(turn.user_message, 'body', '') if turn.user_message else ''
    reply = getattr(turn.reply_message, 'body', '') if turn.reply_message else ''
    print(f'\n- {turn.created_at} tools={turn.tools} actions={turn.actions} error={turn.error!r}')
    print('  PERSON:', str(said)[:300].replace('\n', ' '))
    print('  REPLY :', str(reply)[:500].replace('\n', ' '))
