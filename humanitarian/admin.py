from django.contrib import admin, messages
from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from blockchain.algorand_client import get_algod_client

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
    fieldsets = (
        (None, {
            'fields': (
                'public_id',
                'slug',
                'title',
                'country_code',
                'description',
                'status',
            )
        }),
        ('Donation settings', {
            'fields': (
                'goal_amount',
                'total_donated',
                'total_released',
                'donation_count',
                'release_count',
                'algorand_app_id',
                'vault_address',
            )
        }),
        ('Volunteer section', {
            'fields': (
                'volunteer_section_title',
                'volunteer_section_subtitle',
                'volunteer_service_area_placeholder',
                'volunteer_notes_placeholder',
                'volunteer_cta_label',
            ),
            'description': 'Copy shown in the app volunteer application section for this campaign.',
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(HumanitarianVolunteerApplication)
class HumanitarianVolunteerApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'campaign', 'status', 'service_area', 'has_verified_country_kyc', 'created_at')
    list_filter = ('status', 'campaign')
    search_fields = ('user__username', 'user__phone_number', 'service_area', 'local_phone')
    readonly_fields = ('public_id', 'has_verified_country_kyc', 'created_at', 'updated_at', 'reviewed_at')
    actions = ('approve_verified_volunteers', 'suspend_volunteers')

    @admin.action(description='Approve selected volunteers with verified campaign-country KYC')
    def approve_verified_volunteers(self, request, queryset):
        approved = 0
        for application in queryset.select_related('user', 'campaign'):
            if not application.has_verified_country_kyc:
                self.message_user(
                    request,
                    f'{application.user} skipped: Didit KYC is not verified for {application.campaign.country_code}.',
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
    actions = ('reimburse_donations',)

    @admin.action(description='Reimburse selected donations to their donors on-chain')
    def reimburse_donations(self, request, queryset):
        service = HumanitarianReleaseService()
        reimbursed = 0
        for donation in queryset.select_related('campaign', 'donor_user'):
            try:
                txid = service.reimburse_donation(donation, admin_user=request.user)
            except Exception as exc:
                self.message_user(request, f'{donation.public_id} failed: {exc}', messages.ERROR)
                continue
            reimbursed += 1
            self.message_user(request, f'{donation.public_id} reimbursed: {txid}', messages.SUCCESS)
        if reimbursed:
            self.message_user(request, f'Reimbursed {reimbursed} donation(s).')


@admin.register(HumanitarianRelease)
class HumanitarianReleaseAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'kind', 'volunteer_application', 'amount', 'status', 'recipient_address', 'proof_status', 'transaction_hash', 'created_at')
    list_filter = ('status', 'kind', 'campaign')
    search_fields = ('public_id', 'recipient_address', 'transaction_hash', 'volunteer_application__user__username')
    readonly_fields = (
        'public_id',
        'status',
        'transaction_hash',
        'released_by',
        'released_at',
        'created_at',
        'updated_at',
    )
    inlines = (HumanitarianProofLinkInline,)
    actions = ('submit_releases', 'mark_confirmed', 'mark_proof_pending', 'mark_proof_published')

    PAYOUT_IDENTITY_FIELDS = (
        'campaign',
        'kind',
        'volunteer_application',
        'donation',
        'amount',
        'purpose',
        'recipient_address',
    )

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status not in ('draft', 'failed'):
            fields += self.PAYOUT_IDENTITY_FIELDS
        return fields

    def has_delete_permission(self, request, obj=None):
        # An in-flight or historical row is both the one-shot broadcast claim
        # and a wallet-reenrollment blocker. Deleting it would forget an
        # ambiguous payment and permit a second signature or address retirement.
        if obj is not None and obj.status not in ('draft', 'failed', 'cancelled'):
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Django's bulk delete does not provide per-object state enforcement.
        actions.pop('delete_selected', None)
        return actions

    def save_model(self, request, obj, form, change):
        if not change or not obj.pk:
            return super().save_model(request, obj, form, change)

        # Close the stale-form race: a POST may have loaded a draft just before
        # the broadcaster claims it as submitted. ModelForm.save() writes every
        # model column, including excluded/readonly fields, so without this lock
        # that stale instance could erase the claim and signed recovery payload.
        with db_transaction.atomic():
            locked = HumanitarianRelease.objects.select_for_update().get(pk=obj.pk)
            immutable_state = (
                'status',
                'transaction_hash',
                'signed_transaction_b64',
                'submitted_first_valid_round',
                'submitted_last_valid_round',
                'released_by',
                'released_at',
            )
            for field in immutable_state:
                setattr(obj, field, getattr(locked, field))
            if locked.status not in ('draft', 'failed'):
                for field in self.PAYOUT_IDENTITY_FIELDS:
                    setattr(obj, field, getattr(locked, field))
            return super().save_model(request, obj, form, change)

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
        confirmed = 0
        rejected = queryset.exclude(status='submitted').count()
        submitted = list(queryset.filter(status='submitted'))
        service = None
        if submitted:
            service = HumanitarianReleaseService.__new__(HumanitarianReleaseService)
            service.algod = get_algod_client()
        for release in submitted:
            try:
                outcome = service.reconcile_submission(release)
            except Exception as exc:
                rejected += 1
                self.message_user(
                    request,
                    f'{release.public_id} could not be reconciled: {exc}',
                    messages.ERROR,
                )
                continue
            if outcome == 'confirmed':
                confirmed += 1
            else:
                rejected += 1
                self.message_user(
                    request,
                    f'{release.public_id} remains {outcome}; exact tx confirmation is required.',
                    messages.WARNING,
                )
        if confirmed:
            self.message_user(request, f'Confirmed {confirmed} release(s) on-chain.')
        if rejected:
            self.message_user(
                request,
                f'{rejected} release(s) were not confirmed.',
                messages.WARNING,
            )

    @admin.action(description='Mark selected releases proof pending')
    def mark_proof_pending(self, request, queryset):
        count = queryset.filter(status='confirmed').update(status='proof_pending')
        rejected = queryset.exclude(status__in=('confirmed', 'proof_pending')).count()
        self._sync_campaign_totals(queryset)
        self.message_user(request, f'Marked {count} release(s) proof pending.')
        if rejected:
            self.message_user(
                request,
                f'{rejected} release(s) were not confirmed and were left unchanged.',
                messages.WARNING,
            )

    @admin.action(description='Mark selected releases proof published')
    def mark_proof_published(self, request, queryset):
        count = queryset.filter(status='proof_pending').update(status='proof_published')
        rejected = queryset.exclude(status__in=('proof_pending', 'proof_published')).count()
        self._sync_campaign_totals(queryset)
        self.message_user(request, f'Marked {count} release(s) proof published.')

    def _sync_campaign_totals(self, queryset):
        campaign_ids = set(queryset.values_list('campaign_id', flat=True))
        for campaign in HumanitarianCampaign.objects.filter(id__in=campaign_ids):
            confirmed = campaign.releases.filter(
                kind='volunteer',
                status__in=['confirmed', 'proof_pending', 'proof_published'],
            )
            campaign.total_released = confirmed.aggregate(total=Sum('amount'))['total'] or 0
            campaign.release_count = confirmed.count()
            campaign.save(update_fields=['total_released', 'release_count', 'updated_at'])


@admin.register(HumanitarianProofLink)
class HumanitarianProofLinkAdmin(admin.ModelAdmin):
    list_display = ('release', 'platform', 'title', 'is_public', 'position', 'created_at')
    list_filter = ('is_public', 'platform')
    search_fields = ('url', 'title', 'release__public_id')
    readonly_fields = ('created_at',)
