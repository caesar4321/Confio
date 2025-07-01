from django.contrib import admin
from .models import ZkLoginProof

@admin.register(ZkLoginProof)
class ZkLoginProofAdmin(admin.ModelAdmin):
    list_display = ('id',)  # Minimal display for debugging
    # search_fields and readonly_fields can be added back after debugging
