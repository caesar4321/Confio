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
    P2PTradeRating,
    P2PDispute,
    P2PDisputeTransaction,
    P2PFavoriteTrader
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
        'id', 'offer_entity_display', 'exchange_type_display', 'token_type_display', 
        'country_display', 'rate_display', 'amount_range_display', 
        'available_amount_display', 'payment_methods_count', 'status_display', 'created_at'
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
    readonly_fields = ['created_at', 'updated_at', 'exchange_type_display', 'token_type_display', 
                      'rate_display', 'amount_range_display', 'available_amount_display']
    filter_horizontal = ['payment_methods']
    list_per_page = 50
    date_hierarchy = 'created_at'
    actions = ['activate_offers', 'pause_offers', 'refresh_available_amount']
    
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
    
    def exchange_type_display(self, obj):
        """Display exchange type with colored badge"""
        if obj.exchange_type == 'BUY':
            return format_html('<span style="background-color: #10B981; color: white; padding: 2px 8px; border-radius: 4px;">COMPRA</span>')
        else:
            return format_html('<span style="background-color: #3B82F6; color: white; padding: 2px 8px; border-radius: 4px;">VENTA</span>')
    exchange_type_display.short_description = 'Tipo'
    
    def token_type_display(self, obj):
        """Display token type with proper formatting"""
        if obj.token_type == 'cUSD':
            return format_html('<span style="font-weight: bold;">💵 cUSD</span>')
        elif obj.token_type == 'CONFIO':
            return format_html('<span style="font-weight: bold;">🪙 CONFIO</span>')
        else:
            return format_html('<span style="font-weight: bold;">❓ {}</span>', obj.token_type)
    token_type_display.short_description = 'Cripto'
    
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
        
        # Add exchange direction indicator
        if obj.exchange_type == 'BUY':
            # User is buying crypto, so rate is fiat per crypto
            return format_html('<strong>{}</strong> {} / {}', 
                f'{float(obj.rate):,.2f}', currency, 
                obj.token_type)
        else:
            # User is selling crypto, so rate is fiat per crypto
            return format_html('<strong>{}</strong> {} / {}', 
                f'{float(obj.rate):,.2f}', currency,
                obj.token_type)
    rate_display.short_description = 'Tasa'
    
    def amount_range_display(self, obj):
        """Display min-max amount range"""
        token = obj.token_type
        return format_html('<span style="color: #6B7280;">{} - {} {}</span>', 
                         f'{float(obj.min_amount):,.0f}', f'{float(obj.max_amount):,.0f}', token)
    amount_range_display.short_description = 'Límites'
    
    def available_amount_display(self, obj):
        """Display available amount with color coding"""
        token = obj.token_type
        percentage = (obj.available_amount / obj.max_amount * 100) if obj.max_amount > 0 else 0
        
        # Color code based on availability
        if percentage > 75:
            color = '#10B981'  # Green
        elif percentage > 25:
            color = '#F59E0B'  # Yellow
        else:
            color = '#EF4444'  # Red
            
        return format_html('<span style="color: {}; font-weight: bold;">{} {}</span>', 
                         color, f'{float(obj.available_amount):,.0f}', token)
    available_amount_display.short_description = 'Disponible'
    
    def payment_methods_count(self, obj):
        """Display payment methods count with icons"""
        count = obj.payment_methods.count()
        if count == 0:
            return format_html('<span style="color: #EF4444;">⚠️ Sin métodos</span>')
        elif count == 1:
            return format_html('<span>💳 {} método</span>', count)
        else:
            return format_html('<span>💳 {} métodos</span>', count)
    payment_methods_count.short_description = 'Métodos de Pago'
    
    def status_display(self, obj):
        """Display status with colored badge"""
        status_colors = {
            'ACTIVE': '#10B981',
            'PAUSED': '#F59E0B', 
            'COMPLETED': '#6B7280',
            'CANCELLED': '#EF4444'
        }
        color = status_colors.get(obj.status, '#6B7280')
        status_text = obj.get_status_display()
        return format_html('<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{}</span>', 
                         color, status_text)
    status_display.short_description = 'Estado'
    
    fieldsets = (
        ('👤 Creador de la Oferta', {
            'fields': ('offer_user', 'offer_business'),
            'description': 'Usuario o negocio que creó esta oferta'
        }),
        ('📊 Información Básica', {
            'fields': (
                ('exchange_type', 'token_type'),
                ('country_code', 'currency_code'),
                'status'
            ),
            'description': 'Tipo de intercambio y monedas involucradas'
        }),
        ('💰 Precios y Límites', {
            'fields': (
                'rate',
                ('min_amount', 'max_amount'),
                'available_amount'
            ),
            'description': 'Tasa de cambio y límites de transacción'
        }),
        ('💳 Métodos de Pago y Términos', {
            'fields': (
                'payment_methods',
                'terms',
                'response_time_minutes'
            ),
            'description': 'Métodos de pago aceptados y condiciones del trader'
        }),
        ('🤖 Configuración Automática', {
            'fields': ('auto_complete_enabled', 'auto_complete_time_minutes'),
            'classes': ('collapse',),
            'description': 'Completar operaciones automáticamente después del tiempo especificado'
        }),
        ('📅 Fechas', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('🔧 Sistema Legacy (Obsoleto)', {
            'fields': ('user', 'account'),
            'classes': ('collapse',),
            'description': 'Campos antiguos - no usar para nuevos registros'
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
    
    def activate_offers(self, request, queryset):
        """Activate selected offers"""
        updated = queryset.update(status='ACTIVE')
        self.message_user(request, f'{updated} ofertas activadas exitosamente.')
    activate_offers.short_description = '✅ Activar ofertas seleccionadas'
    
    def pause_offers(self, request, queryset):
        """Pause selected offers"""
        updated = queryset.update(status='PAUSED')
        self.message_user(request, f'{updated} ofertas pausadas exitosamente.')
    pause_offers.short_description = '⏸️ Pausar ofertas seleccionadas'
    
    def refresh_available_amount(self, request, queryset):
        """Refresh available amount to max amount"""
        for offer in queryset:
            offer.available_amount = offer.max_amount
            offer.save()
        self.message_user(request, f'{queryset.count()} ofertas actualizadas con cantidad máxima disponible.')
    refresh_available_amount.short_description = '🔄 Restablecer cantidad disponible'

class DisputedTradeFilter(admin.SimpleListFilter):
    title = 'Dispute Status'
    parameter_name = 'dispute_status'
    
    def lookups(self, request, model_admin):
        return (
            ('disputed', '⚠️ Currently Disputed'),
            ('resolved', '✅ Dispute Resolved'),
            ('never_disputed', '✓ Never Disputed'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'disputed':
            return queryset.filter(status='DISPUTED')
        elif self.value() == 'resolved':
            return queryset.filter(dispute_details__status='RESOLVED')
        elif self.value() == 'never_disputed':
            return queryset.filter(dispute_details__isnull=True)
        return queryset

@admin.register(P2PTrade)
class P2PTradeAdmin(admin.ModelAdmin):
    list_display = ['id', 'crypto_amount_display', 'country_display', 'trade_summary', 'status_display', 'dispute_indicator', 'time_remaining', 'created_at', 'completed_at']
    list_filter = [DisputedTradeFilter, 'status', 'created_at', 'completed_at', 'offer__token_type', 'country_code', 'payment_method']
    search_fields = [
        'id', 'buyer_user__username', 'seller_user__username', 'offer__user__username',
        'buyer_business__name', 'seller_business__name', 'payment_reference'
    ]
    readonly_fields = ['created_at', 'updated_at', 'crypto_amount_display', 'country_display', 'status_display', 'time_remaining', 'trade_summary', 'rating_link', 'dispute_link']
    list_per_page = 50
    date_hierarchy = 'created_at'
    actions = ['mark_as_completed', 'mark_as_disputed', 'resolve_dispute']
    
    fieldsets = (
        ('Trade Parties', {
            'fields': (
                ('buyer_user', 'buyer_business'),
                ('seller_user', 'seller_business'),
            )
        }),
        ('Trade Details', {
            'fields': (
                'offer',
                ('crypto_amount', 'crypto_amount_display'),
                ('fiat_amount', 'fiat_amount_display'),
                'rate_used',
                ('country_code', 'currency_code'),
                'payment_method',
            ),
            'description': 'Trade amounts and currencies'
        }),
        ('Status & Timing', {
            'fields': (
                'status',
                'expires_at',
                ('payment_reference', 'payment_notes'),
                'crypto_transaction_hash',
                ('created_at', 'completed_at'),
            )
        }),
        ('Rating', {
            'fields': ('rating_link',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('updated_at',),
            'classes': ('collapse',)
        }),
    )
    
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
    
    def crypto_amount_display(self, obj):
        """Display crypto amount with currency type"""
        if obj.offer:
            token_type = obj.offer.token_type
            # Format token type for display
            if token_type == 'cUSD':
                token_display = 'cUSD'
            elif token_type == 'CONFIO':
                token_display = 'CONFIO'
            else:
                token_display = token_type
            
            # Add appropriate emoji
            crypto_emoji = '💵' if token_type == 'cUSD' else '🪙'
            return f"{crypto_emoji} {obj.crypto_amount:,.2f} {token_display}"
        return f"❓ {obj.crypto_amount:,.2f}"
    crypto_amount_display.short_description = 'Crypto Amount'
    
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
    
    def country_display(self, obj):
        """Display country with flag emoji"""
        country_flags = {
            'VE': '🇻🇪 Venezuela',
            'CO': '🇨🇴 Colombia',
            'AR': '🇦🇷 Argentina',
            'MX': '🇲🇽 México',
            'PE': '🇵🇪 Perú',
            'CL': '🇨🇱 Chile',
            'EC': '🇪🇨 Ecuador',
            'BO': '🇧🇴 Bolivia',
            'UY': '🇺🇾 Uruguay',
            'PY': '🇵🇾 Paraguay',
            'BR': '🇧🇷 Brasil',
            'US': '🇺🇸 Estados Unidos',
        }
        return country_flags.get(obj.country_code, f'{obj.country_code}')
    country_display.short_description = 'País'
    
    def status_display(self, obj):
        """Display status with colored badges"""
        status_colors = {
            'PENDING': '<span style="color: #FFA500; font-weight: bold;">⏳ PENDIENTE</span>',
            'PAYMENT_PENDING': '<span style="color: #FF6347; font-weight: bold;">💳 PAGO PENDIENTE</span>',
            'PAYMENT_SENT': '<span style="color: #4169E1; font-weight: bold;">📤 PAGO ENVIADO</span>',
            'PAYMENT_CONFIRMED': '<span style="color: #32CD32; font-weight: bold;">✅ PAGO CONFIRMADO</span>',
            'CRYPTO_RELEASED': '<span style="color: #228B22; font-weight: bold;">🚀 CRYPTO LIBERADO</span>',
            'COMPLETED': '<span style="color: #006400; font-weight: bold;">✅ COMPLETADO</span>',
            'DISPUTED': '<span style="background-color: #DC143C; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold;">⚠️ EN DISPUTA</span>',
            'CANCELLED': '<span style="color: #8B0000; font-weight: bold;">❌ CANCELADO</span>',
            'EXPIRED': '<span style="color: #696969; font-weight: bold;">⏰ EXPIRADO</span>',
        }
        return format_html(status_colors.get(obj.status, obj.status))
    status_display.short_description = 'Estado'
    
    def dispute_indicator(self, obj):
        """Show dispute information prominently using the P2PDispute model"""
        if obj.status == 'DISPUTED':
            try:
                dispute = obj.dispute_details
                reason_preview = dispute.reason[:50] + '...' if len(dispute.reason) > 50 else dispute.reason
                dispute_url = reverse('admin:p2p_exchange_p2pdispute_change', args=[dispute.pk])
                return format_html(
                    '<div style="background-color: #FFEBEE; border: 2px solid #DC143C; padding: 5px; border-radius: 5px;">'
                    '<strong style="color: #DC143C;">🚨 DISPUTADO</strong>'
                    '<a href="{}" target="_blank" style="margin-left: 10px; color: #DC143C; text-decoration: underline;">'
                    '[Ver Disputa #{}]</a><br/>'
                    '<small style="color: #B71C1C;">Razón: {}</small><br/>'
                    '<small style="color: #666;">Desde: {}</small>'
                    '</div>',
                    dispute_url,
                    dispute.id,
                    reason_preview,
                    dispute.opened_at.strftime('%Y-%m-%d %H:%M')
                )
            except P2PDispute.DoesNotExist:
                return format_html(
                    '<span style="color: #DC143C;">🚨 DISPUTADO (sin detalles)</span>'
                )
        else:
            # Check if there's a resolved dispute
            try:
                dispute = obj.dispute_details
                dispute_url = reverse('admin:p2p_exchange_p2pdispute_change', args=[dispute.pk])
                if dispute.status == 'RESOLVED':
                    return format_html(
                        '<span style="color: #4CAF50;">✅ Disputa resuelta</span> '
                        '<a href="{}" target="_blank" style="color: #4CAF50; text-decoration: underline;">'
                        '[Ver #{}]</a>',
                        dispute_url,
                        dispute.id
                    )
                else:
                    return format_html(
                        '<span style="color: #FF9800;">⚠️ Disputa pendiente</span> '
                        '<a href="{}" target="_blank" style="color: #FF9800; text-decoration: underline;">'
                        '[Ver #{}]</a>',
                        dispute_url,
                        dispute.id
                    )
            except P2PDispute.DoesNotExist:
                return format_html('<span style="color: #4CAF50;">✓</span>')
    dispute_indicator.short_description = 'Disputa'
    
    def dispute_link(self, obj):
        """Link to dispute details if exists"""
        try:
            dispute = obj.dispute_details
            dispute_url = reverse('admin:p2p_exchange_p2pdispute_change', args=[dispute.pk])
            status_colors = {
                'OPEN': '#DC2626',
                'UNDER_REVIEW': '#F59E0B',
                'RESOLVED': '#10B981',
                'ESCALATED': '#7C3AED',
            }
            status_color = status_colors.get(dispute.status, '#6B7280')
            return format_html(
                '<a href="{}" target="_blank" style="color: {}; font-weight: bold; text-decoration: none; '
                'background: {}; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px;">'
                '🚨 Ver Disputa #{} ({})</a>',
                dispute_url,
                status_color,
                status_color,
                dispute.id,
                dispute.get_status_display()
            )
        except P2PDispute.DoesNotExist:
            return format_html('<span style="color: #999;">No hay disputa</span>')
    dispute_link.short_description = 'Enlace a Disputa'
    
    def time_remaining(self, obj):
        """Display time remaining until expiry"""
        if obj.status in ['COMPLETED', 'CANCELLED', 'EXPIRED']:
            return '-'
        
        from django.utils import timezone
        now = timezone.now()
        remaining = obj.expires_at - now
        
        if remaining.total_seconds() < 0:
            return format_html('<span style="color: red; font-weight: bold;">EXPIRADO</span>')
        
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        
        if hours > 0:
            return format_html('<span style="color: #FF8C00;">{} h {} min</span>', hours, minutes)
        else:
            color = 'red' if minutes < 15 else '#FF8C00'
            return format_html('<span style="color: {}; font-weight: bold;">{} min</span>', color, minutes)
    time_remaining.short_description = 'Tiempo restante'
    
    def trade_summary(self, obj):
        """Display a summary of the trade"""
        buyer = obj.buyer_display_name
        seller = obj.seller_display_name
        
        if obj.offer and obj.offer.exchange_type == 'BUY':
            # Original offer was to buy crypto, so trade seller is offer creator
            direction = f"{buyer} → {seller}"
        else:
            # Original offer was to sell crypto, so trade buyer is offer creator
            direction = f"{seller} → {buyer}"
        
        return format_html(
            '<div style="line-height: 1.5;">' +
            '<strong>{}</strong><br/>' +
            '<span style="color: #666;">Método: {}</span>' +
            '</div>',
            direction,
            obj.payment_method.display_name if obj.payment_method else 'N/A'
        )
    trade_summary.short_description = 'Resumen'
    
    fieldsets = (
        ('🤝 Participantes del Intercambio', {
            'fields': ('offer', 'buyer_user', 'buyer_business', 'seller_user', 'seller_business'),
            'description': 'Usuarios o negocios participando en este intercambio'
        }),
        ('💰 Detalles del Intercambio', {
            'fields': (
                ('crypto_amount', 'crypto_amount_display'),
                ('fiat_amount', 'rate_used'),
                ('country_code', 'currency_code'),
                'payment_method',
                ('status', 'status_display'),
                ('expires_at', 'time_remaining')
            ),
            'description': 'Montos, tasas y estado de la transacción'
        }),
        ('💳 Información de Pago', {
            'fields': ('payment_reference', 'payment_notes'),
            'description': 'Referencia de pago y notas adicionales'
        }),
        ('🚨 Gestión de Disputas', {
            'fields': ('dispute_link',),
            'description': 'Enlace a detalles de disputa si existe'
        }),
        ('✅ Finalización', {
            'fields': ('crypto_transaction_hash', 'completed_at', 'rating_link'),
            'description': 'Detalles de la transacción completada'
        }),
        ('📅 Marcas de Tiempo', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('🔧 Participantes Legacy (Obsoleto)', {
            'fields': ('buyer', 'buyer_account', 'seller', 'seller_account'),
            'classes': ('collapse',),
            'description': 'Campos antiguos - no usar para nuevos registros'
        }),
    )
    
    # Admin actions
    def mark_as_completed(self, request, queryset):
        """Mark selected trades as completed"""
        from django.utils import timezone
        updated = queryset.filter(
            status__in=['PAYMENT_CONFIRMED', 'CRYPTO_RELEASED']
        ).update(
            status='COMPLETED',
            completed_at=timezone.now()
        )
        self.message_user(request, f'{updated} trades marked as completed.')
    mark_as_completed.short_description = '✅ Marcar como completado'
    
    def mark_as_disputed(self, request, queryset):
        """Mark selected trades as disputed and create dispute records"""
        from django.utils import timezone
        updated = 0
        for trade in queryset.exclude(status__in=['COMPLETED', 'CANCELLED', 'EXPIRED']):
            trade.status = 'DISPUTED'
            trade.save()
            
            # Create P2PDispute record if it doesn't exist
            P2PDispute.objects.get_or_create(
                trade=trade,
                defaults={
                    'reason': 'Marcado como disputado desde el admin',
                    'status': 'UNDER_REVIEW',
                    'priority': 2,
                    'initiator_user': request.user,
                }
            )
            updated += 1
        self.message_user(request, f'{updated} trades marked as disputed.')
    mark_as_disputed.short_description = '⚠️ Marcar como disputado'
    
    def resolve_dispute(self, request, queryset):
        """Resolve disputes and mark trades as completed"""
        from django.utils import timezone
        updated = 0
        for trade in queryset.filter(status='DISPUTED'):
            trade.status = 'COMPLETED'
            trade.completed_at = timezone.now()
            trade.save()
            
            # Update the dispute record
            try:
                dispute = trade.dispute_details
                dispute.status = 'RESOLVED'
                dispute.resolution_type = 'NO_ACTION'
                dispute.resolved_at = timezone.now()
                dispute.resolved_by = request.user
                dispute.resolution_notes = f"Resolved by {request.user.username} via admin action"
                dispute.save()
                updated += 1
            except P2PDispute.DoesNotExist:
                pass
        self.message_user(request, f'{updated} disputes resolved and trades marked as completed.')
    resolve_dispute.short_description = '✅ Resolver disputa'

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
        'id', 'trade_link', 'escrow_amount_display', 'status_badge', 
        'release_type_badge', 'dispute_indicator', 'created_at'
    ]
    list_filter = [
        'token_type', 'is_escrowed', 'is_released', 'release_type',
        'resolved_by_dispute', 'created_at', 'released_at'
    ]
    search_fields = [
        'trade__id', 'escrow_transaction_hash', 'release_transaction_hash'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'escrowed_at', 'released_at', 'status_display'
    ]
    
    def trade_link(self, obj):
        """Link to the related trade"""
        url = reverse('admin:p2p_exchange_p2ptrade_change', args=[obj.trade.pk])
        return format_html(
            '<a href="{}" target="_blank">Trade #{}</a>',
            url,
            obj.trade.id
        )
    trade_link.short_description = 'Trade'
    
    def escrow_amount_display(self, obj):
        """Display escrow amount with token type"""
        token_emoji = '💵' if obj.token_type == 'cUSD' else '🪙'
        return format_html(
            '<span style="font-weight: bold;">{} {} {}</span>',
            token_emoji, f'{float(obj.escrow_amount):.2f}', obj.token_type
        )
    escrow_amount_display.short_description = 'Amount'
    
    def status_badge(self, obj):
        """Display status with colored badge"""
        if not obj.is_escrowed:
            return format_html(
                '<span style="background-color: #F59E0B; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-weight: bold; font-size: 11px;">Pending</span>'
            )
        elif not obj.is_released:
            return format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-weight: bold; font-size: 11px;">In Escrow</span>'
            )
        else:
            return format_html(
                '<span style="background-color: #10B981; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-weight: bold; font-size: 11px;">Released</span>'
            )
    status_badge.short_description = 'Status'
    
    def release_type_badge(self, obj):
        """Display release type with colored badge"""
        if not obj.release_type:
            return format_html('<span style="color: #999;">-</span>')
        
        colors = {
            'NORMAL': '#10B981',
            'REFUND': '#F59E0B',
            'PARTIAL_REFUND': '#8B5CF6',
            'DISPUTE_RELEASE': '#DC2626',
        }
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 12px; font-size: 11px;">{}</span>',
            colors.get(obj.release_type, '#6B7280'),
            obj.get_release_type_display() if obj.release_type else 'None'
        )
    release_type_badge.short_description = 'Release Type'
    
    def dispute_indicator(self, obj):
        """Show if escrow was resolved by dispute"""
        if obj.resolved_by_dispute:
            if obj.dispute_resolution:
                url = reverse('admin:p2p_exchange_p2pdispute_change', args=[obj.dispute_resolution.pk])
                return format_html(
                    '<a href="{}" target="_blank" style="color: #DC2626; font-weight: bold;">🚨 Dispute #{}</a>',
                    url,
                    obj.dispute_resolution.id
                )
            else:
                return format_html('<span style="color: #DC2626;">🚨 Dispute</span>')
        return format_html('<span style="color: #10B981;">✓ Normal</span>')
    dispute_indicator.short_description = 'Resolution'
    
    fieldsets = (
        ('Escrow Information', {
            'fields': ('trade', 'escrow_amount', 'token_type', 'status_display')
        }),
        ('Blockchain Details', {
            'fields': ('escrow_transaction_hash', 'release_transaction_hash'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_escrowed', 'is_released', 'escrowed_at', 'released_at')
        }),
        ('Release Details', {
            'fields': ('release_type', 'release_amount', 'resolved_by_dispute', 'dispute_resolution')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation - escrows are created automatically"""
        return False


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


@admin.register(P2PDispute)
class P2PDisputeAdmin(admin.ModelAdmin):
    list_display = [
        'trade_link', 'initiator_display', 'status_badge', 'priority_badge',
        'duration_display', 'resolution_display', 'opened_at'
    ]
    list_filter = [
        'status', 'priority', 'resolution_type', 'opened_at', 'resolved_at',
        ('initiator_user', admin.RelatedOnlyFieldListFilter),
        ('initiator_business', admin.RelatedOnlyFieldListFilter),
        ('resolved_by', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'trade__id', 'reason', 'resolution_notes', 'admin_notes',
        'initiator_user__username', 'initiator_business__name'
    ]
    readonly_fields = [
        'trade', 'opened_at', 'last_updated', 'duration_display', 
        'trade_details', 'evidence_display'
    ]
    
    def trade_link(self, obj):
        """Link to the disputed trade"""
        url = reverse('admin:p2p_exchange_p2ptrade_change', args=[obj.trade.pk])
        return format_html(
            '<a href="{}" target="_blank">Trade #{}</a>',
            url,
            obj.trade.id
        )
    trade_link.short_description = 'Trade'
    
    def initiator_display(self, obj):
        """Display dispute initiator"""
        if obj.initiator_user:
            return f"👤 {obj.initiator_user.username}"
        elif obj.initiator_business:
            return f"🏢 {obj.initiator_business.name}"
        return "❓ Unknown"
    initiator_display.short_description = 'Initiated By'
    
    def status_badge(self, obj):
        """Display status with colored badge"""
        colors = {
            'OPEN': '#DC2626',
            'UNDER_REVIEW': '#F59E0B',
            'RESOLVED': '#10B981',
            'ESCALATED': '#7C3AED',
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; '
            'border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            colors.get(obj.status, '#6B7280'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def priority_badge(self, obj):
        """Display priority with colored badge"""
        priority_config = {
            1: ('Low', '#10B981'),
            2: ('Medium', '#F59E0B'),
            3: ('High', '#DC2626'),
        }
        label, color = priority_config.get(obj.priority, ('Unknown', '#6B7280'))
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 12px; font-size: 11px;">{}</span>',
            color, label
        )
    priority_badge.short_description = 'Priority'
    
    def duration_display(self, obj):
        """Display how long the dispute has been open"""
        hours = obj.duration_hours
        if hours < 1:
            return format_html('<span style="color: #10B981;">< 1 hora</span>')
        elif hours < 24:
            return format_html('<span style="color: #F59E0B;">{} horas</span>', int(hours))
        else:
            days = int(hours / 24)
            return format_html('<span style="color: #DC2626;">{} días</span>', days)
    duration_display.short_description = 'Duration'
    
    def resolution_display(self, obj):
        """Display resolution info"""
        if not obj.is_resolved:
            return format_html('<span style="color: #999;">Pending</span>')
        
        resolution_text = obj.get_resolution_type_display() if obj.resolution_type else 'Resolved'
        if obj.resolution_amount:
            resolution_text += f' (${obj.resolution_amount})'
        
        return format_html(
            '<span style="color: #10B981;">{}</span>',
            resolution_text
        )
    resolution_display.short_description = 'Resolution'
    
    def trade_details(self, obj):
        """Display detailed trade information"""
        trade = obj.trade
        return format_html("""
            <div style="background: #f5f5f5; padding: 15px; border-radius: 5px;">
                <h4 style="margin-top: 0;">Trade Information</h4>
                <p><strong>Trade ID:</strong> #{}</p>
                <p><strong>Amount:</strong> {} {} / {} {}</p>
                <p><strong>Buyer:</strong> {}</p>
                <p><strong>Seller:</strong> {}</p>
                <p><strong>Payment Method:</strong> {}</p>
                <p><strong>Trade Status:</strong> {}</p>
                <p><strong>Created:</strong> {}</p>
            </div>
        """,
            trade.id,
            trade.crypto_amount, trade.offer.token_type if trade.offer else 'N/A',
            trade.fiat_amount, trade.currency_code,
            trade.buyer_display_name,
            trade.seller_display_name,
            trade.payment_method.display_name if trade.payment_method else 'N/A',
            trade.status,
            trade.created_at.strftime('%Y-%m-%d %H:%M')
        )
    trade_details.short_description = 'Trade Details'
    
    def evidence_display(self, obj):
        """Display evidence URLs as clickable links"""
        if not obj.evidence_urls:
            return "No evidence submitted"
        
        links = []
        for i, url in enumerate(obj.evidence_urls):
            links.append(f'<a href="{url}" target="_blank">Evidence {i+1}</a>')
        
        return format_html('<br>'.join(links))
    evidence_display.short_description = 'Evidence'
    
    fieldsets = (
        ('Dispute Information', {
            'fields': ('trade', 'status', 'priority', 'reason')
        }),
        ('Initiator', {
            'fields': ('initiator_user', 'initiator_business')
        }),
        ('Evidence & Notes', {
            'fields': ('evidence_urls', 'evidence_display', 'admin_notes')
        }),
        ('Resolution', {
            'fields': ('resolution_type', 'resolution_amount', 'resolution_notes', 'resolved_by')
        }),
        ('Timestamps', {
            'fields': ('opened_at', 'resolved_at', 'last_updated', 'duration_display'),
            'classes': ('collapse',)
        }),
        ('Trade Details', {
            'fields': ('trade_details',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_under_review', 'resolve_refund_buyer', 'resolve_release_seller', 'escalate_dispute']
    
    def mark_under_review(self, request, queryset):
        """Mark disputes as under review"""
        updated = queryset.filter(status='OPEN').update(status='UNDER_REVIEW')
        self.message_user(request, f'{updated} disputes marked as under review.')
    mark_under_review.short_description = '👁️ Mark as Under Review'
    
    def resolve_refund_buyer(self, request, queryset):
        """Resolve disputes with refund to buyer"""
        from django.utils import timezone
        updated = 0
        for dispute in queryset.filter(status__in=['OPEN', 'UNDER_REVIEW']):
            dispute.status = 'RESOLVED'
            dispute.resolution_type = 'REFUND_BUYER'
            dispute.resolved_at = timezone.now()
            dispute.resolved_by = request.user
            dispute.resolution_notes = f"Resolved by {request.user.username} via admin action"
            dispute.save()
            
            # Update trade status
            dispute.trade.status = 'CANCELLED'
            dispute.trade.save()
            
            updated += 1
            
        self.message_user(request, f'{updated} disputes resolved with refund to buyer.')
    resolve_refund_buyer.short_description = '💰 Resolve - Refund Buyer'
    
    def resolve_release_seller(self, request, queryset):
        """Resolve disputes with release to seller"""
        from django.utils import timezone
        updated = 0
        for dispute in queryset.filter(status__in=['OPEN', 'UNDER_REVIEW']):
            dispute.status = 'RESOLVED'
            dispute.resolution_type = 'RELEASE_TO_SELLER'
            dispute.resolved_at = timezone.now()
            dispute.resolved_by = request.user
            dispute.resolution_notes = f"Resolved by {request.user.username} via admin action"
            dispute.save()
            
            # Update trade status
            dispute.trade.status = 'COMPLETED'
            dispute.trade.completed_at = timezone.now()
            dispute.trade.save()
            
            updated += 1
            
        self.message_user(request, f'{updated} disputes resolved with release to seller.')
    resolve_release_seller.short_description = '✅ Resolve - Release to Seller'
    
    def escalate_dispute(self, request, queryset):
        """Escalate disputes for higher level review"""
        updated = queryset.filter(status__in=['OPEN', 'UNDER_REVIEW']).update(
            status='ESCALATED',
            priority=3  # Set to high priority
        )
        self.message_user(request, f'{updated} disputes escalated.')
    escalate_dispute.short_description = '🚨 Escalate Dispute'


@admin.register(P2PDisputeTransaction)
class P2PDisputeTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'trade_link', 'dispute_link', 'transaction_type_badge', 'amount_display', 
        'recipient_display', 'status_badge', 'processed_at'
    ]
    list_filter = [
        'transaction_type', 'status', 'token_type', 'processed_at', 'created_at',
        ('processed_by', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'dispute__trade__id', 'transaction_hash', 'notes',
        'recipient_user__username', 'recipient_business__name',
        'processed_by__username'
    ]
    readonly_fields = [
        'dispute', 'trade', 'created_at', 'processed_at', 'transaction_hash',
        'block_number', 'gas_used', 'trade_details'
    ]
    
    def trade_link(self, obj):
        """Link to the related trade"""
        url = reverse('admin:p2p_exchange_p2ptrade_change', args=[obj.trade.pk])
        return format_html(
            '<a href="{}" target="_blank" style="color: #1976d2; font-weight: bold;">Trade #{}</a>',
            url,
            obj.trade.id
        )
    trade_link.short_description = 'Trade'
    
    def dispute_link(self, obj):
        """Link to the related dispute"""
        url = reverse('admin:p2p_exchange_p2pdispute_change', args=[obj.dispute.pk])
        return format_html(
            '<a href="{}" target="_blank">Dispute #{}</a>',
            url,
            obj.dispute.id
        )
    dispute_link.short_description = 'Dispute'
    
    def transaction_type_badge(self, obj):
        """Display transaction type with colored badge"""
        colors = {
            'REFUND': '#10B981',
            'RELEASE': '#3B82F6',
            'PARTIAL_REFUND': '#F59E0B',
            'SPLIT': '#8B5CF6',
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; '
            'border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            colors.get(obj.transaction_type, '#6B7280'),
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'
    
    def amount_display(self, obj):
        """Display amount with token type"""
        token_emoji = '💵' if obj.token_type == 'cUSD' else '🪙'
        return format_html(
            '<span style="font-weight: bold;">{} {} {}</span>',
            token_emoji, f'{float(obj.amount):.2f}', obj.token_type
        )
    amount_display.short_description = 'Amount'
    
    def recipient_display(self, obj):
        """Display transaction recipient"""
        if obj.recipient_user:
            return f"👤 {obj.recipient_user.username}"
        elif obj.recipient_business:
            return f"🏢 {obj.recipient_business.name}"
        return "❓ Unknown"
    recipient_display.short_description = 'Recipient'
    
    def status_badge(self, obj):
        """Display status with colored badge"""
        colors = {
            'PENDING': '#F59E0B',
            'PROCESSING': '#3B82F6',
            'COMPLETED': '#10B981',
            'FAILED': '#DC2626',
            'CANCELLED': '#6B7280',
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; '
            'border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            colors.get(obj.status, '#6B7280'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def trade_details(self, obj):
        """Display trade information"""
        trade = obj.trade
        return format_html("""
            <div style="background: #f5f5f5; padding: 15px; border-radius: 5px;">
                <h4 style="margin-top: 0;">Trade Information</h4>
                <p><strong>Trade ID:</strong> #{}</p>
                <p><strong>Amount:</strong> {} {} / {} {}</p>
                <p><strong>Buyer:</strong> {}</p>
                <p><strong>Seller:</strong> {}</p>
                <p><strong>Status:</strong> {}</p>
                <hr>
                <h4>Transaction Details</h4>
                <p><strong>Type:</strong> {}</p>
                <p><strong>Amount:</strong> {} {}</p>
                <p><strong>Recipient:</strong> {}</p>
                <p><strong>Status:</strong> {}</p>
                <p><strong>Hash:</strong> {}</p>
            </div>
        """,
            trade.id,
            trade.crypto_amount, trade.offer.token_type if trade.offer else 'N/A',
            trade.fiat_amount, trade.currency_code,
            trade.buyer_display_name,
            trade.seller_display_name,
            trade.status,
            obj.get_transaction_type_display(),
            obj.amount, obj.token_type,
            self.recipient_display(obj),
            obj.get_status_display(),
            obj.transaction_hash or 'Pending'
        )
    trade_details.short_description = 'Details'
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('dispute', 'trade', 'transaction_type', 'amount', 'token_type')
        }),
        ('Recipient', {
            'fields': ('recipient_user', 'recipient_business')
        }),
        ('Blockchain Details', {
            'fields': ('transaction_hash', 'block_number', 'gas_used'),
            'classes': ('collapse',)
        }),
        ('Processing', {
            'fields': ('status', 'processed_by', 'processed_at', 'failure_reason')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
        ('Details', {
            'fields': ('trade_details',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation - transactions are created through dispute resolution"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Allow viewing but prevent editing of processed transactions"""
        if obj and obj.status == 'COMPLETED':
            return False
        return super().has_change_permission(request, obj)

@admin.register(P2PFavoriteTrader)
class P2PFavoriteTraderAdmin(admin.ModelAdmin):
    list_display = ['user', 'favoriter_context', 'favorite_trader_display', 'trader_type', 'note_preview', 'created_at']
    list_filter = [
        'created_at',
        ('favoriter_business', admin.RelatedOnlyFieldListFilter),
        ('favorite_user', admin.RelatedOnlyFieldListFilter),
        ('favorite_business', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'user__username', 'user__email', 
        'favoriter_business__name',
        'favorite_user__username', 'favorite_business__name', 
        'note'
    ]
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['user', 'favoriter_business', 'favorite_user', 'favorite_business']
    
    def favoriter_context(self, obj):
        """Display the context from which the favorite was added"""
        if obj.favoriter_business:
            return format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 12px; font-size: 11px;">🏢 {}</span>',
                obj.favoriter_business.name
            )
        return format_html(
            '<span style="background-color: #10B981; color: white; padding: 2px 6px; border-radius: 12px; font-size: 11px;">👤 Personal</span>'
        )
    favoriter_context.short_description = 'Added From'
    
    def favorite_trader_display(self, obj):
        """Display the favorited trader with appropriate icon"""
        if obj.favorite_business:
            return format_html(
                '<span style="font-weight: bold;">🏢 {}</span>',
                obj.favorite_business.name
            )
        elif obj.favorite_user:
            name = f"{obj.favorite_user.first_name or ''} {obj.favorite_user.last_name or ''}".strip()
            display_name = name if name else obj.favorite_user.username
            return format_html(
                '<span>👤 {}</span>',
                display_name
            )
        return '-'
    favorite_trader_display.short_description = 'Favorite Trader'
    
    def trader_type(self, obj):
        """Show whether it's a user or business favorite"""
        if obj.favorite_business:
            return format_html('<span style="background-color: #3B82F6; color: white; padding: 2px 6px; border-radius: 12px; font-size: 11px;">Business</span>')
        return format_html('<span style="background-color: #10B981; color: white; padding: 2px 6px; border-radius: 12px; font-size: 11px;">Personal</span>')
    trader_type.short_description = 'Type'
    
    def note_preview(self, obj):
        """Show first 50 chars of note"""
        if obj.note:
            preview = obj.note[:50]
            if len(obj.note) > 50:
                preview += '...'
            return preview
        return '-'
    note_preview.short_description = 'Note'
    
    fieldsets = (
        ('👤 Favoriting User', {
            'fields': ('user',),
            'description': 'User who is adding this favorite'
        }),
        ('🏢 Account Context', {
            'fields': ('favoriter_business',),
            'description': 'If favoriting from a business account, select the business. Leave empty for personal account favorites.'
        }),
        ('⭐ Favorite Trader', {
            'fields': ('favorite_user', 'favorite_business'),
            'description': 'The trader being favorited - only one should be filled'
        }),
        ('📝 Details', {
            'fields': ('note',)
        }),
        ('📅 Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )