"""Comprar admin: cities (live flag + delivery estimate), stores, listings,
orders (arbiter actions), the partner agreement, and the fee ledger with the
monthly partner settlement view.

The partner split (Bolivia: Jason 50% of the 8% fee while engaged) is tracked
HERE only — never on-chain, never in the app.
"""

import csv
from decimal import Decimal

from django.contrib import admin, messages
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.utils import timezone

from .models import (DeliveryAddress, MarketplaceCategory, MarketplaceCity, MarketplaceFeeLedger, MarketplaceInterest,
                     MarketplaceLocationCheck, MarketplacePartnerAgreement, Order, OrderRating,
                     Product, Store)


class MarketplaceCategoryAdmin(admin.ModelAdmin):
    """The product taxonomy. Add, rename, reorder or hide without a release;
    hiding keeps existing listings and stops new ones."""

    list_display = ('key', 'label', 'group', 'group_order', 'sort_order', 'icon', 'is_active', 'listings')
    list_display_links = ('key',)
    list_editable = ('label', 'group', 'group_order', 'sort_order', 'icon', 'is_active')
    list_filter = ('is_active', 'group')
    search_fields = ('label', 'key', 'group')
    ordering = ('group_order', 'sort_order', 'label')

    def get_readonly_fields(self, request, obj=None):
        # The key is what listings store: fixed once created.
        return ('key',) if obj else ()

    def get_queryset(self, request):
        from django.db.models import IntegerField, OuterRef, Subquery
        from django.db.models.functions import Coalesce
        counts = (Product.objects.filter(category=OuterRef('key'), deleted_at__isnull=True)
                  .values('category').annotate(n=Count('id')).values('n'))
        return super().get_queryset(request).annotate(
            _listings=Coalesce(Subquery(counts, output_field=IntegerField()), 0))

    @admin.display(description='Listings', ordering='_listings')
    def listings(self, obj):
        return obj._listings


class MarketplaceCityAdmin(admin.ModelAdmin):
    list_display = ('city', 'country_code', 'is_live', 'delivery_estimate', 'currency_code',
                    'delivery_partner', 'latitude', 'longitude', 'radius_km', 'updated_at')
    list_filter = ('country_code', 'is_live')
    list_editable = ('is_live', 'delivery_estimate')
    search_fields = ('city',)


class MarketplaceLocationCheckAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'account', 'matched_city', 'ip_country', 'accuracy_m')
    list_filter = ('ip_country', 'matched_city')
    raw_id_fields = ('user', 'account')
    readonly_fields = [f.name for f in MarketplaceLocationCheck._meta.fields]

    def has_add_permission(self, request):
        return False


class MarketplaceInterestAdmin(admin.ModelAdmin):
    """Fake-door answers from cities that are not live. The changelist opens
    with a per-city summary: who would buy vs sell, price bands, current
    seller volume and how many want to be told when Comprar arrives."""

    list_display = ('created_at', 'city', 'country_code', 'role', 'price_range', 'monthly_sales',
                    'wants', 'notify', 'user')
    list_filter = ('country_code', 'role', 'price_range', 'monthly_sales', 'notify')
    search_fields = ('city', 'wants', 'user__username')
    raw_id_fields = ('user', 'account')
    readonly_fields = [f.name for f in MarketplaceInterest._meta.fields]
    change_list_template = 'admin/marketplace/interest_change_list.html'
    actions = ['export_csv']

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.db.models import Q
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            qs = response.context_data['cl'].queryset
        except (AttributeError, KeyError):
            return response
        response.context_data['by_city'] = (
            qs.values('country_code', 'city').annotate(
                total=Count('id'),
                buyers=Count('id', filter=Q(role__in=('buyer', 'both'))),
                sellers=Count('id', filter=Q(role__in=('seller', 'both'))),
                browsing=Count('id', filter=Q(role='browsing')),
                notify=Count('id', filter=Q(notify=True)),
                sellers_selling=Count('id', filter=Q(role__in=('seller', 'both'))
                                      & ~Q(monthly_sales__in=('', 'none'))),
            ).order_by('-total')[:100])
        return response

    @admin.action(description='Export selected rows as CSV')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="comprar-interest.csv"'
        writer = csv.writer(response)
        writer.writerow(['created_at', 'country', 'city', 'role', 'categories', 'wants', 'price_range',
                         'monthly_sales', 'channels', 'notify', 'user_id', 'app_version'])
        for r in queryset:
            writer.writerow([r.created_at.isoformat(), r.country_code, r.city, r.role,
                             ' '.join(r.categories), r.wants, r.price_range, r.monthly_sales,
                             ' '.join(r.channels), r.notify, r.user_id, r.app_version])
        return response


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0
    fields = ('title', 'category', 'price_usd', 'stock', 'status')
    readonly_fields = fields
    show_change_link = True
    can_delete = False


class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'country_code', 'owner', 'status', 'ships_outside_city',
                    'product_count', 'created_at')
    list_filter = ('country_code', 'status', 'ships_outside_city')
    search_fields = ('name', 'city', 'owner__username', 'owner__phone_number')
    raw_id_fields = ('owner', 'owner_account')
    inlines = [ProductInline]
    actions = ['suspend', 'reinstate']

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_products=Count('products'))

    @admin.display(description='Products', ordering='_products')
    def product_count(self, obj):
        return obj._products

    @admin.action(description='Suspend selected stores')
    def suspend(self, request, queryset):
        n = queryset.exclude(status='suspended').update(status='suspended')
        self.message_user(request, f'{n} store(s) suspended.')

    @admin.action(description='Reinstate selected stores')
    def reinstate(self, request, queryset):
        n = queryset.filter(status='suspended').update(status='active', suspended_reason='')
        self.message_user(request, f'{n} store(s) reinstated.')


class ProductAdmin(admin.ModelAdmin):
    list_display = ('title', 'store', 'category', 'price_usd', 'stock',
                    'status', 'reviewed_at')
    list_filter = ('status', 'category', 'store__country_code')
    search_fields = ('title', 'description', 'store__name')
    raw_id_fields = ('store',)
    readonly_fields = ('review_verdict', 'review_claim', 'reviewed_at', 'rejection_reason')
    actions = ['approve', 'reject', 'rerun_review']

    @admin.action(description='Approve (manual override; photos must already be public)')
    def approve(self, request, queryset):
        # A new claim invalidates any AI review still in flight for these rows.
        n = queryset.exclude(photo_urls=[]).update(status='active', reviewed_at=timezone.now(),
                                                   review_claim='admin-approved')
        self.message_user(request, f'{n} product(s) approved. Listings without public photos were skipped.')

    @admin.action(description='Reject')
    def reject(self, request, queryset):
        n = queryset.update(status='rejected', rejection_reason='Rechazado por el equipo de Confío.',
                            reviewed_at=timezone.now(), review_claim='admin-rejected')
        self.message_user(request, f'{n} product(s) rejected.')

    @admin.action(description='Re-run AI review')
    def rerun_review(self, request, queryset):
        from .moderation import start_review
        for product in queryset:
            start_review(product, update_fields=[])
        self.message_user(request, f'{queryset.count()} review(s) queued.')


class OrderAdmin(admin.ModelAdmin):
    list_display = ('public_id', 'status', 'pending_action', 'store', 'buyer', 'product_title',
                    'quantity', 'unit_price_usd', 'amount_usd', 'created_at')
    list_filter = ('status', 'store__country_code', 'delivery_outside_city')
    search_fields = ('public_id', 'order_id32', 'product_title', 'store__name', 'buyer__username',
                     'last_tx_hash')
    raw_id_fields = ('buyer', 'buyer_account', 'store', 'product')
    readonly_fields = [f.name for f in Order._meta.fields]
    actions = ['sync_from_chain', 'resolve_refund_buyer', 'resolve_release_merchant']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Re-read from the escrow contract')
    def sync_from_chain(self, request, queryset):
        from . import escrow
        for order in queryset:
            try:
                escrow.sync_order(order)
            except Exception as exc:  # noqa: BLE001
                self.message_user(request, f'{order.public_id}: {exc}', level=messages.ERROR)
        self.message_user(request, 'Synced.')

    def _resolve(self, request, queryset, to_merchant):
        from . import escrow
        for order in queryset:
            if order.status != 'disputed':
                self.message_user(request, f'{order.public_id} is not disputed — skipped',
                                  level=messages.WARNING)
                continue
            try:
                tx = escrow.arbiter_resolve(order, to_merchant)
                self.message_user(request, f'{order.public_id}: resolve sent ({tx})')
            except Exception as exc:  # noqa: BLE001
                self.message_user(request, f'{order.public_id}: {exc}', level=messages.ERROR)

    @admin.action(description='Arbiter: REFUND the buyer (disputed only)')
    def resolve_refund_buyer(self, request, queryset):
        self._resolve(request, queryset, to_merchant=False)

    @admin.action(description='Arbiter: RELEASE to the merchant (disputed only)')
    def resolve_release_merchant(self, request, queryset):
        self._resolve(request, queryset, to_merchant=True)


class DeliveryAddressAdmin(admin.ModelAdmin):
    """Read-only: buyers manage their own book in the app (support can look,
    not edit someone's address)."""
    list_display = ('id', 'user', 'account', 'label', 'city', 'country_code', 'is_default', 'last_used_at', 'deleted_at')
    list_filter = ('country_code', 'is_default')
    search_fields = ('user__username', 'city', 'label')
    raw_id_fields = ('user', 'account')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # buyers delete (soft) in the app; a hard delete would skip that


class OrderRatingAdmin(admin.ModelAdmin):
    list_display = ('order', 'store', 'rating', 'comment', 'comment_status', 'created_at')
    list_filter = ('rating', 'comment_status')
    raw_id_fields = ('order', 'store')
    # The reviewed text is what was approved: editable text would publish
    # words no reviewer saw.
    readonly_fields = ('order', 'store', 'rating', 'comment', 'comment_verdict', 'comment_reviewed_at',
                       'comment_queued_at')


class MarketplacePartnerAgreementAdmin(admin.ModelAdmin):
    list_display = ('partner_name', 'country_code', 'share_display', 'active', 'started_at',
                    'ended_at', 'accrued_unpaid')
    list_filter = ('active', 'country_code')
    raw_id_fields = ('partner_user',)

    @admin.display(description='Share of fee')
    def share_display(self, obj):
        return f'{obj.share_bps / 100:.1f}%'

    @admin.display(description='Accrued, unpaid (USD)')
    def accrued_unpaid(self, obj):
        total = obj.ledger_entries.filter(partner_paid_at__isnull=True).aggregate(
            s=Sum('partner_share_usd'))['s'] or Decimal('0')
        return f'{total:.2f}'


class MarketplaceFeeLedgerAdmin(admin.ModelAdmin):
    """One row per released order. The changelist shows a monthly summary
    (GMV, fee, partner share, Confío share) above the rows."""

    list_display = ('released_at', 'order', 'country_code', 'gross_usd', 'fee_usd',
                    'partner_share_usd', 'confio_share_usd', 'partner_paid_at')
    list_filter = ('country_code', 'partner_agreement', ('partner_paid_at', admin.EmptyFieldListFilter))
    date_hierarchy = 'released_at'
    readonly_fields = [f.name for f in MarketplaceFeeLedger._meta.fields if f.name != 'partner_paid_at']
    actions = ['mark_partner_paid', 'export_csv']
    change_list_template = 'admin/marketplace/feeledger_change_list.html'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            qs = response.context_data['cl'].queryset
        except (AttributeError, KeyError):
            return response
        response.context_data['monthly'] = (
            qs.annotate(month=TruncMonth('released_at')).values('month', 'country_code')
            .annotate(orders=Count('id'), gmv=Sum('gross_usd'), fee=Sum('fee_usd'),
                      partner=Sum('partner_share_usd'), confio=Sum('confio_share_usd'))
            .order_by('-month', 'country_code'))
        return response

    @admin.action(description='Mark partner share as paid (today)')
    def mark_partner_paid(self, request, queryset):
        n = queryset.filter(partner_paid_at__isnull=True).update(partner_paid_at=timezone.now())
        self.message_user(request, f'{n} row(s) marked paid.')

    @admin.action(description='Export selected rows as CSV')
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="comprar-fee-ledger.csv"'
        writer = csv.writer(response)
        writer.writerow(['released_at', 'order', 'country', 'gross_usd', 'fee_usd',
                         'partner', 'partner_share_usd', 'confio_share_usd', 'partner_paid_at'])
        for row in queryset.select_related('order', 'partner_agreement'):
            writer.writerow([
                row.released_at.isoformat(), row.order.public_id, row.country_code, row.gross_usd,
                row.fee_usd, row.partner_agreement.partner_name if row.partner_agreement else '',
                row.partner_share_usd, row.confio_share_usd,
                row.partner_paid_at.isoformat() if row.partner_paid_at else ''])
        return response
