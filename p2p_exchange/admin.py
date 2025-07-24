from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db import models
from .models import (
    P2PPaymentMethod, 
    P2POffer, 
    P2PTrade, 
    P2PMessage, 
    P2PUserStats, 
    P2PEscrow,
    P2PTradeRating
)

@admin.register(P2PPaymentMethod)
class P2PPaymentMethodAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'country_display', 'provider_type', 'is_active', 'offer_count', 'created_at']
    list_filter = ['is_active', 'provider_type', 'country_code', 'created_at']
    search_fields = ['name', 'display_name', 'country_code']
    ordering = ['country_code', 'display_name']
    
    def offer_count(self, obj):
        """Show how many active offers use this payment method"""
        return obj.offers.filter(status='ACTIVE').count()
    offer_count.short_description = 'Active Offers'
    
    def country_display(self, obj):
        """Display country with flag emoji"""
        if obj.country_code:
            # Get flag emoji for country
            if obj.bank and obj.bank.country:
                return f"{obj.bank.country.flag_emoji} {obj.country_code}"
            elif obj.country:
                return f"{obj.country.flag_emoji} {obj.country_code}"
            return obj.country_code
        return "🌐 Global"
    country_display.short_description = 'Country'
    
    def get_queryset(self, request):
        """Optimize queries by prefetching related offers"""
        return super().get_queryset(request).prefetch_related('offers').select_related('bank__country', 'country')

@admin.register(P2POffer)
class P2POfferAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'offer_entity_display', 'exchange_type', 'token_type', 'country_display', 'rate_display', 
        'available_amount', 'status', 'created_at'
    ]
    list_filter = [
        'exchange_type', 'token_type', 'country_code', 'status', 'created_at',
        # New direct relationship filters
        ('offer_user', admin.RelatedOnlyFieldListFilter),
        ('offer_business', admin.RelatedOnlyFieldListFilter),
        # Old filters (keep for legacy data)
        ('account__account_type', admin.ChoicesFieldListFilter),
        ('account__business', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'offer_user__username', 'offer_user__email', 'offer_business__name',
        'user__username', 'user__email', 'country_code', 'account__business__name'
    ]
    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ['payment_methods']
    
    def offer_entity_display(self, obj):
        """Display offer entity (User or Business) using new direct relationships"""
        if obj.offer_user:
            return f"👤 {obj.offer_user.username}"
        elif obj.offer_business:
            return f"🏢 {obj.offer_business.name}"
        elif obj.user:  # Fallback to old system
            return f"⚠️ {obj.user.username} (Legacy)"
        return "❓ Unknown"
    offer_entity_display.short_description = 'Offer Creator'
    
    def country_display(self, obj):
        """Display country with flag"""
        # Map country codes to flag emojis
        country_flags = {
            'VE': '🇻🇪', 'CO': '🇨🇴', 'AR': '🇦🇷', 'PE': '🇵🇪', 'CL': '🇨🇱',
            'BR': '🇧🇷', 'MX': '🇲🇽', 'US': '🇺🇸', 'DO': '🇩🇴', 'PA': '🇵🇦',
            'EC': '🇪🇨', 'BO': '🇧🇴', 'UY': '🇺🇾', 'PY': '🇵🇾', 'GT': '🇬🇹',
            'HN': '🇭🇳', 'SV': '🇸🇻', 'NI': '🇳🇮', 'CR': '🇨🇷', 'CU': '🇨🇺',
            'JM': '🇯🇲', 'TT': '🇹🇹'
        }
        flag = country_flags.get(obj.country_code, '🌐')
        return f"{flag} {obj.country_code}"
    country_display.short_description = 'Country'
    
    def rate_display(self, obj):
        """Display rate with currency"""
        # Use the stored currency_code if available, otherwise fall back to mapping
        if obj.currency_code:
            currency = obj.currency_code
        else:
            # Fallback for old records
            country_currencies = {
                'VE': 'VES', 'CO': 'COP', 'AR': 'ARS', 'PE': 'PEN', 'CL': 'CLP',
                'BR': 'BRL', 'MX': 'MXN', 'US': 'USD', 'DO': 'DOP', 'PA': 'USD',
                'EC': 'USD', 'BO': 'BOB', 'UY': 'UYU', 'PY': 'PYG', 'GT': 'GTQ',
                'HN': 'HNL', 'SV': 'USD', 'NI': 'NIO', 'CR': 'CRC', 'CU': 'CUP',
                'JM': 'JMD', 'TT': 'TTD'
            }
            currency = country_currencies.get(obj.country_code, 'USD')
        return f"{obj.rate:,.2f} {currency}"
    rate_display.short_description = 'Rate'
    
    fieldsets = (
        ('Offer Creator (Direct Relationships)', {
            'fields': ('offer_user', 'offer_business'),
            'description': 'New clean relationship model - directly links users or businesses'
        }),
        ('Legacy Offer Creator (Deprecated)', {
            'fields': ('user', 'account'),
            'classes': ('collapse',),
            'description': 'Old indirect relationship model - will be removed in future'
        }),
        ('Basic Info', {
            'fields': ('exchange_type', 'token_type', 'country_code', 'status')
        }),
        ('Pricing', {
            'fields': ('rate', 'min_amount', 'max_amount', 'available_amount')
        }),
        ('Payment & Terms', {
            'fields': ('payment_methods', 'terms', 'response_time_minutes')
        }),
        ('Auto-complete', {
            'fields': ('auto_complete_enabled', 'auto_complete_time_minutes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_form(self, request, obj=None, **kwargs):
        """Customize the form to show available payment methods info"""
        form = super().get_form(request, obj, **kwargs)
        
        # Add help text showing available payment methods for the country
        if obj and obj.country_code:
            from .default_payment_methods import get_payment_methods_for_country
            available_methods = get_payment_methods_for_country(obj.country_code)
            method_names = [m['display_name'] for m in available_methods]
            
            form.base_fields['payment_methods'].help_text = (
                f"Available payment methods for {obj.country_code}: {', '.join(method_names)}. "
                f"Missing methods will be created automatically when you save."
            )
        else:
            form.base_fields['payment_methods'].help_text = (
                "Payment methods will be filtered based on the selected country code."
            )
            
        return form
    
    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Customize payment methods field to include country-specific options"""
        if db_field.name == "payment_methods":
            # Get the offer being edited
            obj = None
            if request.resolver_match.kwargs.get('object_id'):
                try:
                    obj = self.model.objects.get(pk=request.resolver_match.kwargs['object_id'])
                except self.model.DoesNotExist:
                    pass
            
            if obj and obj.country_code:
                # Ensure all payment methods for this country exist in the database
                from .default_payment_methods import get_payment_methods_for_country
                available_methods = get_payment_methods_for_country(obj.country_code)
                
                for method_data in available_methods:
                    from .models import P2PPaymentMethod
                    P2PPaymentMethod.objects.get_or_create(
                        name=method_data['name'],
                        defaults={
                            'display_name': method_data['display_name'],
                            'icon': method_data['icon'],
                            'is_active': method_data['is_active'],
                        }
                    )
                
                # Filter queryset to show only methods available for this country
                method_names = [m['name'] for m in available_methods]
                kwargs["queryset"] = P2PPaymentMethod.objects.filter(name__in=method_names)
        
        return super().formfield_for_manytomany(db_field, request, **kwargs)

@admin.register(P2PTrade)
class P2PTradeAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'buyer_entity_display', 'seller_entity_display', 
        'trade_type_display', 'crypto_amount', 'fiat_amount_display', 
        'country_code', 'status', 'rating_display', 'created_at', 'expires_at'
    ]
    list_filter = [
        'status', 'offer__token_type', 'country_code', 'currency_code', 
        'created_at', 'expires_at',
        ('buyer_user', admin.RelatedOnlyFieldListFilter),
        ('buyer_business', admin.RelatedOnlyFieldListFilter),
        ('seller_user', admin.RelatedOnlyFieldListFilter),
        ('seller_business', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'buyer_user__username', 'seller_user__username', 'offer__user__username',
        'buyer_business__name', 'seller_business__name'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'completed_at', 
        'disputed_at', 'resolved_at', 'rating_link'
    ]
    
    def buyer_entity_display(self, obj):
        """Display buyer entity (User or Business) using new direct relationships"""
        if obj.buyer_user:
            return f"👤 {obj.buyer_user.username}"
        elif obj.buyer_business:
            return f"🏢 {obj.buyer_business.name}"
        elif obj.buyer:  # Fallback to old system
            return f"⚠️ {obj.buyer.username} (Legacy)"
        return "❓ Unknown"
    buyer_entity_display.short_description = 'Buyer'
    
    def seller_entity_display(self, obj):
        """Display seller entity (User or Business) using new direct relationships"""
        if obj.seller_user:
            return f"👤 {obj.seller_user.username}"
        elif obj.seller_business:
            return f"🏢 {obj.seller_business.name}"
        elif obj.seller:  # Fallback to old system
            return f"⚠️ {obj.seller.username} (Legacy)"
        return "❓ Unknown"
    seller_entity_display.short_description = 'Seller'
    
    def trade_type_display(self, obj):
        """Display the trade type with icons for better visual distinction"""
        buyer_type = "👤" if obj.buyer_user else "🏢" if obj.buyer_business else "⚠️"
        seller_type = "👤" if obj.seller_user else "🏢" if obj.seller_business else "⚠️"
        
        if obj.buyer_user and obj.seller_user:
            return "👤↔️👤 Personal"
        elif obj.buyer_business and obj.seller_business:
            return "🏢↔️🏢 Business"
        elif obj.buyer_user and obj.seller_business:
            return "👤→🏢 Personal→Business"
        elif obj.buyer_business and obj.seller_user:
            return "🏢→👤 Business→Personal"
        else:
            return f"{buyer_type}↔️{seller_type} Mixed/Legacy"
    trade_type_display.short_description = 'Trade Type'
    
    def fiat_amount_display(self, obj):
        """Display fiat amount with currency code"""
        # Map country codes to flag emojis
        country_flags = {
            'VE': '🇻🇪', 'CO': '🇨🇴', 'AR': '🇦🇷', 'PE': '🇵🇪', 'CL': '🇨🇱',
            'BR': '🇧🇷', 'MX': '🇲🇽', 'US': '🇺🇸', 'DO': '🇩🇴', 'PA': '🇵🇦',
            'EC': '🇪🇨', 'BO': '🇧🇴', 'UY': '🇺🇾', 'PY': '🇵🇾', 'GT': '🇬🇹',
            'HN': '🇭🇳', 'SV': '🇸🇻', 'NI': '🇳🇮', 'CR': '🇨🇷', 'CU': '🇨🇺',
            'JM': '🇯🇲', 'TT': '🇹🇹'
        }
        flag = country_flags.get(obj.country_code, '🌐')
        return f"{flag} {obj.fiat_amount:,.2f} {obj.currency_code}"
    fiat_amount_display.short_description = 'Fiat Amount'
    
    def payment_method_display(self, obj):
        """Display payment method with icon"""
        if obj.payment_method:
            return f"💳 {obj.payment_method.display_name}"
        return "❓ Unknown"
    payment_method_display.short_description = 'Payment Method'
    
    def offer_display(self, obj):
        """Display offer information"""
        if obj.offer:
            return f"{obj.offer.exchange_type} {obj.offer.token_type} @ {obj.offer.rate}"
        return "❓ No Offer"
    offer_display.short_description = 'Offer'
    
    def rating_display(self, obj):
        """Display rating status with stars"""
        try:
            if hasattr(obj, 'rating') and obj.rating:
                rating = obj.rating
                stars = '⭐' * rating.overall_rating
                return format_html(
                    '<span title="Rating: {}/5">{}</span>',
                    rating.overall_rating,
                    stars
                )
            return format_html('<span style="color: #999;">No rating</span>')
        except:
            return format_html('<span style="color: #999;">No rating</span>')
    rating_display.short_description = 'Rating'
    
    def rating_link(self, obj):
        """Link to view/edit rating"""
        try:
            if hasattr(obj, 'rating') and obj.rating:
                url = reverse('admin:p2p_exchange_p2ptraderating_change', args=[obj.rating.pk])
                return format_html(
                    '<a href="{}" target="_blank">View Rating ({}/5)</a>',
                    url,
                    obj.rating.overall_rating
                )
            return "No rating yet"
        except:
            return "No rating yet"
    rating_link.short_description = 'Rating Details'
    
    fieldsets = (
        ('Trade Participants (Direct Relationships)', {
            'fields': ('offer', 'buyer_user', 'buyer_business', 'seller_user', 'seller_business'),
            'description': 'New clean relationship model - directly links users or businesses'
        }),
        ('Legacy Trade Participants (Deprecated)', {
            'fields': ('buyer', 'buyer_account', 'seller', 'seller_account'),
            'classes': ('collapse',),
            'description': 'Old indirect relationship model - will be removed in future'
        }),
        ('Trade Details', {
            'fields': (
                'crypto_amount', 'fiat_amount', 'rate_used', 
                'country_code', 'currency_code',
                'payment_method', 'status', 'expires_at'
            )
        }),
        ('Payment Info', {
            'fields': ('payment_reference', 'payment_notes')
        }),
        ('Completion', {
            'fields': ('crypto_transaction_hash', 'completed_at', 'rating_link')
        }),
        ('Dispute Handling', {
            'fields': ('dispute_reason', 'disputed_at', 'resolved_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(P2PMessage)
class P2PMessageAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'trade', 'sender_entity_display', 'message_type', 'is_read', 'created_at'
    ]
    list_filter = [
        'message_type', 'is_read', 'created_at',
        # New direct relationship filters
        ('sender_user', admin.RelatedOnlyFieldListFilter),
        ('sender_business', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'trade__id', 'sender_user__username', 'sender_business__name', 'sender__username', 'content'
    ]
    readonly_fields = ['created_at', 'updated_at', 'read_at']
    
    def sender_entity_display(self, obj):
        """Display sender entity (User or Business) using new direct relationships"""
        if obj.sender_user:
            return f"👤 {obj.sender_user.username}"
        elif obj.sender_business:
            return f"🏢 {obj.sender_business.name}"
        elif obj.sender:  # Fallback to old system
            return f"⚠️ {obj.sender.username} (Legacy)"
        return "❓ Unknown"
    sender_entity_display.short_description = 'Sender'
    
    fieldsets = (
        ('Message Sender (Direct Relationships)', {
            'fields': ('sender_user', 'sender_business'),
            'description': 'New clean relationship model - directly links users or businesses'
        }),
        ('Legacy Sender (Deprecated)', {
            'fields': ('sender',),
            'classes': ('collapse',),
            'description': 'Old indirect relationship model - will be removed in future'
        }),
        ('Message Details', {
            'fields': ('trade', 'message_type', 'content', 'is_read')
        }),
        ('Attachments', {
            'fields': ('attachment_url', 'attachment_type'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'read_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(P2PUserStats)
class P2PUserStatsAdmin(admin.ModelAdmin):
    list_display = [
        'stats_entity_display', 'total_trades', 'completed_trades', 'success_rate', 
        'avg_rating_display', 'rating_count', 'avg_response_time', 'is_verified'
    ]
    list_filter = [
        'is_verified', 'verification_level', 'last_seen_online',
        # New direct relationship filters
        ('stats_user', admin.RelatedOnlyFieldListFilter),
        ('stats_business', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'stats_user__username', 'stats_user__email', 'stats_business__name', 'user__username', 'user__email'
    ]
    readonly_fields = ['created_at', 'updated_at', 'last_seen_online']
    
    def stats_entity_display(self, obj):
        """Display stats entity (User or Business) using new direct relationships"""
        if obj.stats_user:
            return f"👤 {obj.stats_user.username}"
        elif obj.stats_business:
            return f"🏢 {obj.stats_business.name}"
        elif obj.user:  # Fallback to old system
            return f"⚠️ {obj.user.username} (Legacy)"
        return "❓ Unknown"
    stats_entity_display.short_description = 'Stats Owner'
    
    def avg_rating_display(self, obj):
        """Display average rating with stars"""
        from django.db.models import Avg
        
        # Get ratings for this entity
        ratings = P2PTradeRating.objects.filter(
            models.Q(ratee_user=obj.stats_user) | 
            models.Q(ratee_business=obj.stats_business)
        )
        
        if ratings.exists():
            avg = ratings.aggregate(Avg('overall_rating'))['overall_rating__avg']
            if avg:
                stars = '⭐' * int(avg)
                partial = '✨' if (avg % 1) >= 0.5 else ''
                return format_html(
                    '<span title="{}/5">{}</span>',
                    f"{avg:.2f}",
                    stars + partial
                )
        return format_html('<span style="color: #999;">No ratings</span>')
    avg_rating_display.short_description = 'Avg Rating'
    
    def rating_count(self, obj):
        """Show total number of ratings received"""
        count = P2PTradeRating.objects.filter(
            models.Q(ratee_user=obj.stats_user) | 
            models.Q(ratee_business=obj.stats_business)
        ).count()
        
        if count > 0:
            return format_html(
                '<span style="color: #4CAF50; font-weight: bold;">{}</span>',
                count
            )
        return format_html('<span style="color: #999;">0</span>')
    rating_count.short_description = 'Ratings'
    
    fieldsets = (
        ('Stats Owner (Direct Relationships)', {
            'fields': ('stats_user', 'stats_business'),
            'description': 'New clean relationship model - directly links users or businesses'
        }),
        ('Legacy Owner (Deprecated)', {
            'fields': ('user',),
            'classes': ('collapse',),
            'description': 'Old indirect relationship model - will be removed in future'
        }),
        ('Trading Statistics', {
            'fields': ('total_trades', 'completed_trades', 'cancelled_trades', 'disputed_trades', 'success_rate')
        }),
        ('Performance Metrics', {
            'fields': ('avg_response_time', 'last_seen_online')
        }),
        ('Volume Statistics', {
            'fields': ('total_volume_cusd', 'total_volume_confio'),
            'classes': ('collapse',)
        }),
        ('Verification', {
            'fields': ('is_verified', 'verification_level')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(P2PEscrow)
class P2PEscrowAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'trade', 'escrow_amount', 'token_type', 
        'is_escrowed', 'is_released', 'created_at'
    ]
    list_filter = [
        'token_type', 'is_escrowed', 'is_released', 'created_at'
    ]
    search_fields = [
        'trade__id', 'escrow_transaction_hash', 'release_transaction_hash'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'escrowed_at', 'released_at'
    ]


@admin.register(P2PTradeRating)
class P2PTradeRatingAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'trade_link', 'rater_display', 'ratee_display', 
        'overall_rating_stars', 'rating_breakdown', 'has_comment', 
        'tags_display', 'rated_at'
    ]
    list_filter = [
        'overall_rating', 'communication_rating', 'speed_rating', 
        'reliability_rating', 'rated_at',
        ('rater_user', admin.RelatedOnlyFieldListFilter),
        ('rater_business', admin.RelatedOnlyFieldListFilter),
        ('ratee_user', admin.RelatedOnlyFieldListFilter),
        ('ratee_business', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'trade__id', 'comment',
        'rater_user__username', 'rater_business__name',
        'ratee_user__username', 'ratee_business__name'
    ]
    readonly_fields = ['rated_at', 'trade_details']
    
    def trade_link(self, obj):
        """Link to the trade"""
        url = reverse('admin:p2p_exchange_p2ptrade_change', args=[obj.trade.pk])
        return format_html(
            '<a href="{}" target="_blank">Trade #{}</a>',
            url,
            obj.trade.id
        )
    trade_link.short_description = 'Trade'
    
    def rater_display(self, obj):
        """Display rater with icon"""
        if obj.rater_user:
            return f"👤 {obj.rater_user.username}"
        elif obj.rater_business:
            return f"🏢 {obj.rater_business.name}"
        return "❓ Unknown"
    rater_display.short_description = 'Rater'
    
    def ratee_display(self, obj):
        """Display ratee with icon"""
        if obj.ratee_user:
            return f"👤 {obj.ratee_user.username}"
        elif obj.ratee_business:
            return f"🏢 {obj.ratee_business.name}"
        return "❓ Unknown"
    ratee_display.short_description = 'Ratee'
    
    def overall_rating_stars(self, obj):
        """Display overall rating as stars"""
        stars = '⭐' * obj.overall_rating
        empty_stars = '☆' * (5 - obj.overall_rating)
        return format_html(
            '<span style="font-size: 16px;" title="{}/5">{}{}</span>',
            obj.overall_rating,
            stars,
            empty_stars
        )
    overall_rating_stars.short_description = 'Overall Rating'
    
    def rating_breakdown(self, obj):
        """Display all ratings in a compact format"""
        ratings = []
        if obj.communication_rating:
            ratings.append(f"💬 {obj.communication_rating}/5")
        if obj.speed_rating:
            ratings.append(f"⚡ {obj.speed_rating}/5")
        if obj.reliability_rating:
            ratings.append(f"🛡️ {obj.reliability_rating}/5")
        
        if ratings:
            return format_html('<br>'.join(ratings))
        return format_html('<span style="color: #999;">No detailed ratings</span>')
    rating_breakdown.short_description = 'Detailed Ratings'
    
    def has_comment(self, obj):
        """Show if rating has a comment"""
        if obj.comment:
            return format_html(
                '<span title="{}" style="cursor: help;">✅ Yes ({} chars)</span>',
                obj.comment[:100] + '...' if len(obj.comment) > 100 else obj.comment,
                len(obj.comment)
            )
        return format_html('<span style="color: #999;">❌ No</span>')
    has_comment.short_description = 'Comment'
    
    def tags_display(self, obj):
        """Display tags as badges"""
        if obj.tags:
            tag_html = []
            for tag in obj.tags[:3]:  # Show first 3 tags
                tag_html.append(
                    '<span style="background: #e3f2fd; color: #1976d2; '
                    'padding: 2px 8px; border-radius: 12px; font-size: 11px; '
                    'margin-right: 4px;">{}</span>'.format(tag)
                )
            if len(obj.tags) > 3:
                tag_html.append(
                    '<span style="color: #999; font-size: 11px;">+{} more</span>'.format(len(obj.tags) - 3)
                )
            return format_html(''.join(tag_html))
        return format_html('<span style="color: #999;">No tags</span>')
    tags_display.short_description = 'Tags'
    
    def trade_details(self, obj):
        """Show trade details in a formatted way"""
        trade = obj.trade
        details = f"""
        <div style="background: #f5f5f5; padding: 10px; border-radius: 5px;">
            <strong>Trade #{trade.id}</strong><br>
            <strong>Amount:</strong> {trade.crypto_amount} {trade.offer.token_type} / {trade.fiat_amount} {trade.currency_code}<br>
            <strong>Status:</strong> {trade.status}<br>
            <strong>Created:</strong> {trade.created_at.strftime('%Y-%m-%d %H:%M')}<br>
            <strong>Completed:</strong> {trade.completed_at.strftime('%Y-%m-%d %H:%M') if trade.completed_at else 'N/A'}
        </div>
        """
        return format_html(details)
    trade_details.short_description = 'Trade Information'
    
    fieldsets = (
        ('Rating Information', {
            'fields': ('trade', 'overall_rating', 'communication_rating', 
                      'speed_rating', 'reliability_rating')
        }),
        ('Participants', {
            'fields': ('rater_user', 'rater_business', 'ratee_user', 'ratee_business')
        }),
        ('Feedback', {
            'fields': ('comment', 'tags')
        }),
        ('Metadata', {
            'fields': ('rated_at', 'trade_details'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation of ratings through admin"""
        return False