"""Read-only: the newest Comunidad activity shares, follows and follower
notifications, for checking a test walkthrough.

    ssh confio-prod 'cd /opt/confio && ./myvenv/bin/python manage.py shell' < scripts/ops/community_shares_state.py
"""
from datetime import timedelta

from django.utils import timezone

from inbox.models import CommunityActivityShare, CommunityFollow
from notifications.models import Notification

since = timezone.now() - timedelta(hours=6)

print('== activity shares (6h)')
for s in CommunityActivityShare.objects.filter(created_at__gte=since).select_related(
        'user', 'content_item__community_review').order_by('-id')[:20]:
    item = s.content_item
    review = getattr(item, 'community_review', None)
    activity = dict((item.metadata or {}).get('activity') or {})
    activity.pop('wallet', None)
    print(s.id, s.user.username, s.kind, 'tx', s.unified_transaction_id,
          'post', item.id, item.status, review.status if review else None,
          (review.decided_by_model if review else ''), 'note=%r' % (item.body or '')[:60], activity)

print('== follows (6h)')
for f in CommunityFollow.objects.filter(created_at__gte=since).select_related('follower', 'followed').order_by('-id')[:20]:
    print(f.id, f.follower.username, '->', f.followed.username, 'notify', f.notify, f.created_at)

print('== community notifications (6h)')
for n in Notification.objects.filter(created_at__gte=since, notification_type__startswith='COMMUNITY_').order_by('-id')[:20]:
    print(n.id, n.notification_type, n.user_id, n.title, '|', n.message[:80], 'push_sent', n.push_sent)
