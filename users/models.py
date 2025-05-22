from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from .country_codes import COUNTRY_CODES

class User(AbstractUser):
    firebase_uid = models.CharField(max_length=128, unique=True)
    phone_country = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        choices=[(code[2], f"{code[0]} ({code[1]})") for code in COUNTRY_CODES],
        help_text="User's country ISO code for phone number"
    )
    phone_number = models.CharField(max_length=15, blank=True, null=True, help_text="User's phone number without country code")
    auth_token_version = models.IntegerField(default=1, help_text="Version number for JWT tokens. Incrementing this invalidates all existing tokens.")
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='custom_user_set',
        related_query_name='custom_user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='custom_user_set',
        related_query_name='custom_user',
    )
    
    def __str__(self):
        return self.username or self.email or self.firebase_uid

    @property
    def phone_country_code(self):
        """Get the country code for the user's phone country"""
        if not self.phone_country:
            return None
        for country in COUNTRY_CODES:
            if country[2] == self.phone_country:
                return country[1]
        return None

    @property
    def phone_country_name(self):
        """Get the country name for the user's phone country"""
        if not self.phone_country:
            return None
        for country in COUNTRY_CODES:
            if country[2] == self.phone_country:
                return country[0]
        return None

    def increment_auth_token_version(self):
        """Increment the auth token version to invalidate all existing tokens"""
        self.auth_token_version += 1
        self.save(update_fields=['auth_token_version'])

class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    # —————————————————————————————
    # persistent per‑user state
    # —————————————————————————————
    sui_address = models.CharField(
        max_length=66,
        blank=True, null=True,
        help_text="Last‑computed Sui address"
    )

    # —————————————————————————————
    # audit‑style timestamps
    # —————————————————————————————
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} Profile"