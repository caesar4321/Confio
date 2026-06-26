from django.contrib import admin, messages
from django.db.models import Sum
from django.utils import timezone

from .models import (
    HumanitarianCampaign,
    HumanitarianDonation,
    HumanitarianProofLink,
    HumanitarianRelease,
    HumanitarianVolunteerApplication,
)
from .services import HumanitarianReleaseService


class HumanitarianProofLinkInline(admin.TabularInline):
    model = HumanitarianProofLink
    extra = 1
    fields = ('url', 'title', 'platform', 'is_public', 'position')


@admin.register(HumanitarianCampaign)
class HumanitarianCampaignAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'slug',
        'status',
        'total_donated',
        'total_released',
        'donation_count',
        'release_count',
        'algorand_app_id',
        'updated_at',
    )
    list_filter = ('status', 'country_code')
    search_fields = ('title', 'slug', 'description', 'vault_address')
    readonly_fields = ('public_id', 'created_at', 'updated_at')


@admin.register(HumanitarianVolunteerApplication)
class HumanitarianVolunteerApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'campaign', 'status', 'service_area', 'has_verified_venezuelan_kyc', 'created_at')
    list_filter = ('status', 'campaign')
    search_fields = ('user__username', 'user__phone_number', 'service_area', 'local_phone')
    readonly_fields = ('public_id', 'has_verified_venezuelan_kyc', 'created_at', 'updated_at', 'reviewed_at')
    actions = ('approve_verified_volunteers', 'suspend_volunteers')

    @admin.action(description='Approve selected verified Venezuelan volunteers')
    def approve_verified_volunteers(self, request, queryset):
        approved = 0
        for application in queryset.select_related('user'):
            if not application.has_verified_venezuelan_kyc:
                self.message_user(
                    request,
                    f'{application.user} skipped: Venezuelan Didit KYC is not verified.',
                    messages.WARNING,
                )
                continue
            application.approve(request.user)
            approved += 1
        self.message_user(request, f'Approved {approved} volunteer application(s).')

    @admin.action(description='Suspend selected volunteers')
    def suspend_volunteers(self, request, queryset):
        count = queryset.update(status='suspended', reviewed_by=request.user, reviewed_at=timezone.now())
        self.message_user(request, f'Suspended {count} volunteer application(s).')


@admin.register(HumanitarianDonation)
class HumanitarianDonationAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'donor_display_name', 'amount', 'status', 'transaction_hash', 'donated_at')
    list_filter = ('status', 'campaign')
    search_fields = ('donor_display_name', 'transaction_hash', 'from_address')
    readonly_fields = ('public_id', 'created_at', 'updated_at')


@admin.register(HumanitarianRelease)
class HumanitarianReleaseAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'volunteer_application', 'amount', 'status', 'recipient_address', 'proof_status', 'transaction_hash', 'created_at')
    list_filter = ('status', 'campaign')
    search_fields = ('public_id', 'recipient_address', 'transaction_hash', 'volunteer_application__user__username')
    readonly_fields = ('public_id', 'transaction_hash', 'released_by', 'released_at', 'created_at', 'updated_at')
    inlines = (HumanitarianProofLinkInline,)
    actions = ('submit_releases', 'mark_confirmed', 'mark_proof_pending', 'mark_proof_published')

    def proof_status(self, obj):
        return obj.proof_url or 'pending'

    @admin.action(description='Submit selected draft releases on-chain')
    def submit_releases(self, request, queryset):
        service = HumanitarianReleaseService()
        submitted = 0
        for release in queryset.select_related('campaign', 'volunteer_application', 'volunteer_application__user'):
            try:
                txid = service.submit_release(release, admin_user=request.user)
            except Exception as exc:
                self.message_user(request, f'{release.public_id} failed: {exc}', messages.ERROR)
                continue
            submitted += 1
            self.message_user(request, f'{release.public_id} submitted: {txid}', messages.SUCCESS)
        if submitted:
            self.message_user(request, f'Submitted {submitted} release(s).')

    @admin.action(description='Mark selected releases confirmed')
    def mark_confirmed(self, request, queryset):
        count = queryset.update(status='confirmed')
        self._sync_campaign_totals(queryset)
        self.message_user(request, f'Marked {count} release(s) confirmed.')

    @admin.action(description='Mark selected releases proof pending')
    def mark_proof_pending(self, request, queryset):
        count = queryset.update(status='proof_pending')
        self._sync_campaign_totals(queryset)
        self.message_user(request, f'Marked {count} release(s) proof pending.')

    @admin.action(description='Mark selected releases proof published')
    def mark_proof_published(self, request, queryset):
        count = queryset.update(status='proof_published')
        self._sync_campaign_totals(queryset)
        self.message_user(request, f'Marked {count} release(s) proof published.')

    def _sync_campaign_totals(self, queryset):
        campaign_ids = set(queryset.values_list('campaign_id', flat=True))
        for campaign in HumanitarianCampaign.objects.filter(id__in=campaign_ids):
            confirmed = campaign.releases.filter(status__in=['confirmed', 'proof_pending', 'proof_published'])
            campaign.total_released = confirmed.aggregate(total=Sum('amount'))['total'] or 0
            campaign.release_count = confirmed.count()
            campaign.save(update_fields=['total_released', 'release_count', 'updated_at'])


@admin.register(HumanitarianProofLink)
class HumanitarianProofLinkAdmin(admin.ModelAdmin):
    list_display = ('release', 'platform', 'title', 'is_public', 'position', 'created_at')
    list_filter = ('is_public', 'platform')
    search_fields = ('url', 'title', 'release__public_id')
    readonly_fields = ('created_at',)
