"""Export Confío IA conversations for review (read-only; the OUTPUT holds customer messages).

Run on prod, then copy the file off and delete it there:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/assistant_export.py
    scp confio-prod:/tmp/assistant_export.json <private scratch dir>/
    ssh confio-prod 'sudo rm -f /tmp/assistant_export.json'

Writes /tmp/assistant_export.json: every assistant conversation since launch with its
messages, plus turns, voice sessions, pets, profiles, probe answers, needs and
subscriptions. Never commit the output or paste it anywhere public.
"""
import datetime
import json
from decimal import Decimal

from django.utils import timezone

from assistant.models import (AssistantNeed, AssistantProfile, AssistantSubscription, AssistantThreadState,
                              AssistantTurn, CustomPet, ProbeAnswer, VoiceSession)
from inbox.models import SupportConversation, SupportMessage

SINCE = datetime.datetime(2026, 10, 3, tzinfo=datetime.timezone.utc)
OUT = '/tmp/assistant_export.json'


def ser(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


conv_ids = set(AssistantTurn.objects.filter(created_at__gte=SINCE).values_list('conversation_id', flat=True))
conv_ids |= set(SupportMessage.objects.filter(created_at__gte=SINCE, metadata__ai=True)
                .values_list('conversation_id', flat=True))
conversations = []
for conv in SupportConversation.objects.filter(id__in=conv_ids).select_related('user', 'business'):
    user = conv.user
    messages = list(conv.messages.filter(created_at__gte=SINCE).order_by('created_at').values(
        'id', 'created_at', 'sender_type', 'sender_user_id', 'message_type', 'body', 'metadata'))
    state = (AssistantThreadState.objects.filter(conversation=conv)
             .values('handoff_at', 'handoff_reason', 'returned_to_ai_at').first())
    conversations.append({
        'id': conv.id, 'user_id': user.id, 'name': f'{user.first_name} {user.last_name}'.strip(),
        'username': user.username, 'phone_country': user.phone_country, 'joined': user.date_joined,
        'account_id': conv.account_id, 'business': conv.business.name if conv.business_id else None,
        'status': conv.status, 'thread_state': state, 'messages': messages,
    })

data = {
    'exported_at': timezone.now(),
    'conversations': conversations,
    'turns': list(AssistantTurn.objects.filter(created_at__gte=SINCE).order_by('created_at').values()),
    'voice_sessions': list(VoiceSession.objects.filter(started_at__gte=SINCE).order_by('started_at').values()),
    'pets': list(CustomPet.objects.filter(created_at__gte=SINCE).order_by('created_at').values()),
    'profiles': list(AssistantProfile.objects.all().order_by('created_at').values()),
    'probe_answers': list(ProbeAnswer.objects.all().order_by('created_at').values()),
    'needs': list(AssistantNeed.objects.all().order_by('message_at').values()),
    'subscriptions': list(AssistantSubscription.objects.all().values()),
}
with open(OUT, 'w', encoding='utf-8') as fh:
    fh.write(json.dumps(data, default=ser, ensure_ascii=False))
print({k: len(v) for k, v in data.items() if isinstance(v, list)},
      sum(len(c['messages']) for c in conversations), 'messages ->', OUT)
