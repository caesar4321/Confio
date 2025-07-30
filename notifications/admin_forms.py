"""
Custom forms for notification admin
"""
from django import forms
from django.contrib.auth import get_user_model
from .models import Notification, NotificationType
from .fcm_service import send_test_push

User = get_user_model()


class BroadcastNotificationForm(forms.ModelForm):
    """Form for creating broadcast notifications"""
    
    # Override fields for better UI
    notification_type = forms.ChoiceField(
        choices=[
            (NotificationType.ANNOUNCEMENT, 'Announcement'),
            (NotificationType.PROMOTION, 'Promotion'),
            (NotificationType.SYSTEM, 'System Update'),
        ],
        initial=NotificationType.ANNOUNCEMENT,
        help_text="Type of broadcast notification"
    )
    
    broadcast_target = forms.ChoiceField(
        choices=[
            ('all', 'All Users'),
            ('verified', 'Verified Users Only'),
            ('business', 'Business Account Holders'),
            ('active_7d', 'Active in Last 7 Days'),
            ('active_30d', 'Active in Last 30 Days'),
        ],
        initial='all',
        help_text="Target audience for this broadcast"
    )
    
    test_user_email = forms.EmailField(
        required=False,
        help_text="Send a test to this user before broadcasting (optional)"
    )
    
    send_push = forms.BooleanField(
        initial=True,
        required=False,
        help_text="Send push notifications (in addition to in-app notifications)"
    )
    
    schedule_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text="Schedule for later (leave empty to send immediately)"
    )
    
    class Meta:
        model = Notification
        fields = ['notification_type', 'title', 'message', 'action_url', 
                  'broadcast_target', 'data']
        widgets = {
            'title': forms.TextInput(attrs={
                'placeholder': 'Notification Title',
                'maxlength': '100',
                'style': 'width: 100%;'
            }),
            'message': forms.Textarea(attrs={
                'placeholder': 'Notification message...',
                'rows': 4,
                'style': 'width: 100%;'
            }),
            'action_url': forms.TextInput(attrs={
                'placeholder': 'confio://screen/path (optional)',
                'style': 'width: 100%;'
            }),
            'data': forms.Textarea(attrs={
                'placeholder': '{"key": "value"} (optional JSON data)',
                'rows': 3,
                'style': 'width: 100%; font-family: monospace;'
            })
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set is_broadcast to True for all instances
        self.instance.is_broadcast = True
        
    def clean_test_user_email(self):
        email = self.cleaned_data.get('test_user_email')
        if email:
            try:
                User.objects.get(email=email)
            except User.DoesNotExist:
                raise forms.ValidationError(f"User with email {email} not found")
        return email
    
    def clean_data(self):
        data = self.cleaned_data.get('data')
        if data:
            import json
            try:
                # Validate JSON
                if isinstance(data, str):
                    json.loads(data)
            except json.JSONDecodeError:
                raise forms.ValidationError("Invalid JSON format")
        return data


class NotificationPreviewForm(forms.Form):
    """Form for previewing notifications before sending"""
    
    preview_device = forms.ChoiceField(
        choices=[
            ('ios', 'iOS Device'),
            ('android', 'Android Device'),
        ],
        initial='ios',
        help_text="Preview how the notification will appear"
    )
    
    include_image = forms.BooleanField(
        required=False,
        help_text="Include app icon in preview"
    )