"""
Custom admin views for notifications
"""
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta

from .models import Notification, FCMDeviceToken, NotificationPreference
from .admin_forms import BroadcastNotificationForm
from .utils import create_notification
from .fcm_service import send_push_notification, send_test_push


@staff_member_required
def broadcast_notification_view(request):
    """View for creating and sending broadcast notifications"""
    
    if request.method == 'POST':
        form = BroadcastNotificationForm(request.POST)
        
        if form.is_valid():
            # Check if this is a test send
            if 'send_test' in request.POST:
                test_email = form.cleaned_data.get('test_user_email')
                if test_email:
                    try:
                        from users.models import User
                        test_user = User.objects.get(email=test_email)
                        
                        # Create a test notification (not saved to DB)
                        test_notification = form.save(commit=False)
                        test_notification.user = test_user
                        test_notification.is_broadcast = False
                        test_notification.save()
                        
                        # Send push notification
                        if form.cleaned_data.get('send_push'):
                            result = send_push_notification(test_notification)
                            if result.get('success'):
                                messages.success(
                                    request, 
                                    f"Test notification sent to {test_email} "
                                    f"({result.get('sent', 0)} device(s))"
                                )
                            else:
                                messages.error(
                                    request, 
                                    f"Failed to send test: {result.get('error', 'Unknown error')}"
                                )
                        else:
                            messages.success(request, f"Test notification created for {test_email}")
                        
                        # Delete test notification
                        test_notification.delete()
                        
                    except Exception as e:
                        messages.error(request, f"Error sending test: {str(e)}")
                
                # Return to form with same data
                return render(request, 'admin/notifications/broadcast_form.html', {
                    'form': form,
                    'title': 'Send Broadcast Notification',
                    'stats': get_broadcast_stats(form.cleaned_data.get('broadcast_target', 'all')),
                })
            
            # This is the actual broadcast
            elif 'send_broadcast' in request.POST:
                try:
                    # Create the broadcast notification
                    notification = form.save(commit=False)
                    notification.is_broadcast = True
                    notification.save()
                    
                    # Get target audience stats
                    target = form.cleaned_data.get('broadcast_target', 'all')
                    stats = get_broadcast_stats(target)
                    
                    # Send push notifications if enabled
                    if form.cleaned_data.get('send_push'):
                        result = send_push_notification(notification)
                        
                        if result.get('success'):
                            messages.success(
                                request,
                                f"Broadcast sent successfully! "
                                f"Reached {result.get('sent', 0)} devices "
                                f"({stats['user_count']} users targeted)"
                            )
                        else:
                            messages.warning(
                                request,
                                f"Broadcast created but push sending had issues: "
                                f"{result.get('error', 'Check logs')}"
                            )
                    else:
                        messages.success(
                            request,
                            f"Broadcast notification created for {stats['user_count']} users "
                            f"(in-app only, no push)"
                        )
                    
                    # Redirect to notification list
                    return redirect(reverse('admin:notifications_notification_changelist'))
                    
                except Exception as e:
                    messages.error(request, f"Error creating broadcast: {str(e)}")
            
            # Preview button
            elif 'preview' in request.POST:
                # Show preview
                return render(request, 'admin/notifications/broadcast_form.html', {
                    'form': form,
                    'title': 'Send Broadcast Notification',
                    'preview_data': {
                        'title': form.cleaned_data.get('title'),
                        'message': form.cleaned_data.get('message'),
                        'type': form.cleaned_data.get('notification_type'),
                    },
                    'stats': get_broadcast_stats(form.cleaned_data.get('broadcast_target', 'all')),
                })
    else:
        form = BroadcastNotificationForm()
    
    return render(request, 'admin/notifications/broadcast_form.html', {
        'form': form,
        'title': 'Send Broadcast Notification',
        'stats': get_broadcast_stats('all'),
    })


def get_broadcast_stats(target):
    """Get statistics for broadcast target audience"""
    from users.models import User
    
    # Base query
    users = User.objects.filter(is_active=True)
    
    # Apply filters based on target
    if target == 'verified':
        users = users.filter(is_verified=True)
    elif target == 'business':
        users = users.filter(business_accounts__isnull=False).distinct()
    elif target == 'active_7d':
        cutoff = timezone.now() - timedelta(days=7)
        users = users.filter(last_login__gte=cutoff)
    elif target == 'active_30d':
        cutoff = timezone.now() - timedelta(days=30)
        users = users.filter(last_login__gte=cutoff)
    
    user_count = users.count()
    
    # Get device stats
    device_stats = FCMDeviceToken.objects.filter(
        user__in=users,
        is_active=True
    ).values('device_type').distinct().count()
    
    # Get users with push enabled
    push_enabled_count = NotificationPreference.objects.filter(
        user__in=users,
        push_enabled=True,
        push_announcements=True
    ).count()
    
    return {
        'user_count': user_count,
        'device_count': FCMDeviceToken.objects.filter(
            user__in=users,
            is_active=True
        ).count(),
        'push_enabled_count': push_enabled_count,
        'target_description': get_target_description(target),
    }


def get_target_description(target):
    """Get human-readable description of target audience"""
    descriptions = {
        'all': 'All active users',
        'verified': 'Verified users only',
        'business': 'Users with business accounts',
        'active_7d': 'Users active in the last 7 days',
        'active_30d': 'Users active in the last 30 days',
    }
    return descriptions.get(target, 'Unknown target')


@staff_member_required
def notification_stats_view(request):
    """View for notification statistics"""
    
    # Get date range
    days = int(request.GET.get('days', 7))
    start_date = timezone.now() - timedelta(days=days)
    
    # Get notification stats
    notifications = Notification.objects.filter(created_at__gte=start_date)
    
    stats = {
        'total_sent': notifications.count(),
        'broadcasts': notifications.filter(is_broadcast=True).count(),
        'personal': notifications.filter(is_broadcast=False).count(),
        'push_sent': notifications.filter(push_sent=True).count(),
        'by_type': {},
        'daily_counts': [],
    }
    
    # Count by type
    for choice in Notification._meta.get_field('notification_type').choices:
        count = notifications.filter(notification_type=choice[0]).count()
        if count > 0:
            stats['by_type'][choice[1]] = count
    
    # Daily counts
    from django.db.models import Count
    from django.db.models.functions import TruncDate
    
    daily = notifications.annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')
    
    stats['daily_counts'] = list(daily)
    
    return render(request, 'admin/notifications/stats.html', {
        'title': 'Notification Statistics',
        'stats': stats,
        'days': days,
    })