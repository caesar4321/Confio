from django.contrib import admin
from .models import User

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'firebase_uid', 'phone_country', 'phone_number', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email', 'firebase_uid', 'phone_country', 'phone_number')