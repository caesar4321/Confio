from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings

class User(AbstractUser):
    firebase_uid = models.CharField(max_length=128, unique=True)
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

class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    # —————————————————————————————
    # persistent per‑user state
    # —————————————————————————————
    user_salt = models.BinaryField(
        help_text="Persistent salt used to derive the same Sui address",
        editable=False,
    )
    google_sub = models.CharField(
        max_length=255,
        blank=True, null=True,
        help_text="'sub' claim from Google ID token"
    )
    apple_sub = models.CharField(
        max_length=255,
        blank=True, null=True,
        help_text="'sub' claim from Apple ID token"
    )
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