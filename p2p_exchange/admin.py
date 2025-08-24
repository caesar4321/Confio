from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db import models
from django.utils import timezone
from django.contrib import messages
from config.admin_mixins import EnhancedAdminMixin, BulkUpdateMixin, InlineCountMixin
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
    P2PFavoriteTrader,
    PremiumUpgradeRequest,
    P2PDisputeEvidence
)

@admin.register(P2PPaymentMethod)
class P2PPaymentMethodAdmin(EnhancedAdminMixin, BulkUpdateMixin, admin.ModelAdmin):
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
class P2POfferAdmin(EnhancedAdminMixin, admin.ModelAdmin):
    list_display = [
        'id', 'offer_entity_display', 'exchange_type_display', 'token_type_display', 
        'country_display', 'rate_display', 'amount_range_display',
        'payment_methods_count', 'status_display', 'created_at'
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
                      'rate_display', 'amount_range_display']
    filter_horizontal = ['payment_methods']
    list_per_page = 50
    date_hierarchy = 'created_at'
    actions = ['activate_offers', 'pause_offers']
    
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
    
    # removed available amount display
    
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
    
    # removed refresh_available_amount action

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
class P2PTradeAdmin(EnhancedAdminMixin, admin.ModelAdmin):
    list_display = ['id', 'crypto_amount_display', 'country_display', 'trade_summary', 'status_display', 'escrow_status_display', 'dispute_indicator', 'time_remaining', 'created_at', 'completed_at']
    list_filter = [DisputedTradeFilter, 'status', 'created_at', 'completed_at', 'offer__token_type', 'country_code', 'payment_method']
    search_fields = [
        'id', 'buyer_user__username', 'seller_user__username', 'offer__user__username',
        'buyer_business__name', 'seller_business__name', 'payment_reference'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'crypto_amount_display', 'country_display', 'status_display', 'time_remaining', 'trade_summary', 'rating_link', 'dispute_link',
        'escrow_status_display', 'escrow_amount_display', 'escrow_token_display', 'escrow_tx_hash_display', 'escrow_released_tx_hash_display', 'escrow_escrowed_at_display', 'escrow_released_at_display',
        'onchain_escrow_sanity'
    ]
    readonly_fields = ['created_at', 'updated_at', 'crypto_amount_display', 'country_display', 'status_display', 'time_remaining', 'trade_summary', 'rating_link', 'dispute_link',
                      'escrow_status_display', 'escrow_amount_display', 'escrow_token_display', 'escrow_tx_hash_display', 'escrow_released_tx_hash_display', 'escrow_escrowed_at_display', 'escrow_released_at_display',
                      'onchain_escrow_sanity']
    list_per_page = 50
    date_hierarchy = 'created_at'
    actions = [
        'mark_as_completed',
        'mark_as_disputed',
        'resolve_dispute_refund_buyer_onchain',
        'resolve_dispute_release_seller_onchain',
    ]
    
    # Fieldsets are defined below (Spanish localized variant)

    # ===== Escrow helpers for admin =====
    def _escrow(self, obj):
        try:
            return obj.escrow
        except Exception:
            return None

    def escrow_status_display(self, obj):
        """DB-only escrow status for list views (fast)."""
        e = self._escrow(obj)
        if not e:
            return format_html('<span style="color:#6B7280; font-weight:600;">❌ Sin escrow</span>')
        if e.is_escrowed and not e.is_released:
            return format_html('<span style="color:#2563EB; font-weight:600;">🔒 En custodia</span>')
        if e.is_released:
            return format_html('<span style="color:#10B981; font-weight:600;">✅ Liberado ({})</span>', e.get_release_type_display() if hasattr(e, 'get_release_type_display') else e.release_type)
        return format_html('<span style="color:#6B7280; font-weight:600;">⏳ Pendiente</span>')
    escrow_status_display.short_description = 'Escrow'

    def escrow_amount_display(self, obj):
        e = self._escrow(obj)
        return f"{e.escrow_amount:,.2f}" if e else '-'
    escrow_amount_display.short_description = 'Monto'

    def escrow_token_display(self, obj):
        e = self._escrow(obj)
        return e.token_type if e else '-'
    escrow_token_display.short_description = 'Token'

    def escrow_tx_hash_display(self, obj):
        e = self._escrow(obj)
        if e and e.escrow_transaction_hash:
            return format_html('<code style="font-size:11px;">{}</code>', e.escrow_transaction_hash)
        return '-'
    escrow_tx_hash_display.short_description = 'Tx Escrow'

    def escrow_released_tx_hash_display(self, obj):
        e = self._escrow(obj)
        if e and e.release_transaction_hash:
            return format_html('<code style="font-size:11px;">{}</code>', e.release_transaction_hash)
        return '-'
    escrow_released_tx_hash_display.short_description = 'Tx Liberación'

    def escrow_escrowed_at_display(self, obj):
        e = self._escrow(obj)
        return e.escrowed_at.strftime('%Y-%m-%d %H:%M') if (e and e.escrowed_at) else '-'
    escrow_escrowed_at_display.short_description = 'En custodia desde'

    def escrow_released_at_display(self, obj):
        e = self._escrow(obj)
        return e.released_at.strftime('%Y-%m-%d %H:%M') if (e and e.released_at) else '-'
    escrow_released_at_display.short_description = 'Liberado en'

    # Detail-only on-chain sanity check (read-only; may incur latency)
    def onchain_escrow_sanity(self, obj):
        try:
            from django.conf import settings
            from algosdk.v2client import algod
            client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            app_id = getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', 0)
            if not app_id:
                return mark_safe('<span style="color:#6B7280;">Config sin app_id</span>')
            client.application_box_by_name(app_id, str(obj.id).encode('utf-8'))
            return mark_safe('<span style="color:#2563EB; font-weight:600;">On-chain: caja presente</span>')
        except Exception:
            return mark_safe('<span style="color:#EF4444; font-weight:600;">On-chain: sin caja</span>')
    onchain_escrow_sanity.short_description = 'Sanidad on-chain'
    
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
        ('🔒 Escrow', {
            'fields': (
                'escrow_status_display',
                ('escrow_amount_display', 'escrow_token_display'),
                ('escrow_tx_hash_display', 'escrow_released_tx_hash_display'),
                ('escrow_escrowed_at_display', 'escrow_released_at_display'),
                'onchain_escrow_sanity',
            ),
            'description': 'Estado de la custodia on-chain y detalles relacionados'
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

    def onchain_escrow_sanity(self, obj):
        try:
            from django.conf import settings
            from algosdk.v2client import algod
            client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
            app_id = getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', 0)
            if not app_id:
                return mark_safe('<span style="color:#6B7280;">Config sin app_id</span>')
            client.application_box_by_name(app_id, str(obj.id).encode('utf-8'))
            return mark_safe('<span style="color:#2563EB; font-weight:600;">On-chain: caja presente</span>')
        except Exception:
            return mark_safe('<span style="color:#EF4444; font-weight:600;">On-chain: sin caja</span>')
    onchain_escrow_sanity.short_description = 'Sanidad on-chain'
    
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
    
    # Removed legacy DB-only resolve_dispute action in favor of on-chain actions

    def _resolve_onchain(self, request, queryset, winner_side: str):
        """Backend-only on-chain dispute resolution for selected DISPUTED trades.
        winner_side: 'BUYER' or 'SELLER'
        """
        from django.utils import timezone
        from django.conf import settings
        from algosdk import mnemonic, encoding as algo_encoding
        from algosdk.v2client import algod
        from algosdk import transaction
        import base64, msgpack
        from blockchain.p2p_trade_transaction_builder import P2PTradeTransactionBuilder
        from .models import P2PDispute

        admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None)
        sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
        if not admin_mn or not sponsor_mn:
            self.message_user(request, 'Config error: missing ALGORAND_ADMIN_MNEMONIC or ALGORAND_SPONSOR_MNEMONIC', level='error')
            return

        from algosdk import account as algo_account
        admin_sk = mnemonic.to_private_key(admin_mn)
        admin_addr = algo_account.address_from_private_key(admin_sk)
        sponsor_sk = mnemonic.to_private_key(sponsor_mn)
        sponsor_addr = algo_account.address_from_private_key(sponsor_sk)

        client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
        builder = P2PTradeTransactionBuilder()

        # Preflight: verify on-chain admin and sponsor match env
        try:
            app_info = client.application_info(builder.app_id)
            gs_list = (app_info.get('params') or {}).get('global-state') or []
            def _decode_gs(lst):
                out = {}
                import base64
                for kv in lst:
                    k = base64.b64decode(kv.get('key','')).decode('utf-8', errors='ignore')
                    v = kv.get('value') or {}
                    if 'bytes' in v and v['bytes']:
                        try:
                            b = base64.b64decode(v['bytes'])
                            out[k] = algo_account.address_from_private_key(b'\x00'*32)  # placeholder
                            # Replace with actual bytes for addresses
                            out[k] = b
                        except Exception:
                            out[k] = v['bytes']
                    else:
                        out[k] = v.get('uint')
                return out
            gs = _decode_gs(gs_list)
            on_admin_b = gs.get('admin')
            on_sponsor_b = gs.get('sponsor_address')
            on_admin = None
            on_sponsor = None
            try:
                from algosdk import encoding as algo_encoding
                if isinstance(on_admin_b, (bytes, bytearray)) and len(on_admin_b) == 32:
                    on_admin = algo_encoding.encode_address(on_admin_b)
                if isinstance(on_sponsor_b, (bytes, bytearray)) and len(on_sponsor_b) == 32:
                    on_sponsor = algo_encoding.encode_address(on_sponsor_b)
            except Exception:
                on_admin = None
                on_sponsor = None
            if on_admin and admin_addr != on_admin:
                self.message_user(request, f'Admin address mismatch. Env={admin_addr[:10]}.. App={on_admin[:10]}..', level='error')
                return
            if on_sponsor and sponsor_addr != on_sponsor:
                self.message_user(request, f'Sponsor address mismatch. Env={sponsor_addr[:10]}.. App={on_sponsor[:10]}..', level='error')
                return
        except Exception as e:
            self.message_user(request, f'Preflight: unable to read app info: {e}', level='error')
            return

        successes = 0
        failures = 0
        for trade in queryset.filter(status='DISPUTED').select_related('buyer_user', 'seller_user', 'buyer_business', 'seller_business'):
            try:
                # Resolve winner address
                from users.models import Business
                def _addr_user(u):
                    from users.models import Account
                    a = Account.objects.filter(user_id=getattr(u, 'id', None), account_type='personal', deleted_at__isnull=True).order_by('account_index').first()
                    return getattr(a, 'algorand_address', None) if a else None
                def _addr_biz(biz_id):
                    from users.models import Account
                    try:
                        biz = Business.objects.get(id=biz_id)
                    except Business.DoesNotExist:
                        return None
                    a = Account.objects.filter(business=biz, account_type='business', deleted_at__isnull=True).order_by('account_index').first()
                    return getattr(a, 'algorand_address', None) if a else None
                if winner_side == 'BUYER':
                    winner_addr = _addr_biz(trade.buyer_business_id) if trade.buyer_business_id else _addr_user(trade.buyer_user)
                else:
                    winner_addr = _addr_biz(trade.seller_business_id) if trade.seller_business_id else _addr_user(trade.seller_user)
                if not winner_addr:
                    failures += 1
                    continue

                # Preflight: ensure winner is opted into asset from trade box
                try:
                    import base64 as _b64
                    bx = client.application_box_by_name(builder.app_id, str(trade.id).encode('utf-8'))
                    raw = _b64.b64decode((bx or {}).get('value',''))
                    if len(raw) < 48:
                        self.message_user(request, f'Trade {trade.id}: on-chain box incomplete', level='error')
                        failures += 1
                        continue
                    import struct
                    asset_id = struct.unpack('>Q', raw[40:48])[0]
                    try:
                        client.account_asset_info(winner_addr, asset_id)
                    except Exception:
                        self.message_user(request, f'Trade {trade.id}: winner {winner_addr[:10]}.. not opted-in to asset {asset_id}', level='error')
                        failures += 1
                        continue
                except Exception as ee:
                    self.message_user(request, f'Trade {trade.id}: preflight error {ee}', level='error')
                    failures += 1
                    continue

                res = builder.build_resolve_dispute(admin_addr, str(trade.id), winner_addr)
                if not res.success:
                    self.message_user(request, f'Trade {trade.id}: build failed: {res.error}', level='error')
                    failures += 1
                    continue

                # Sign sponsor
                parsed = res.sponsor_transactions or []
                if not parsed:
                    failures += 1
                    continue
                b0 = base64.b64decode(parsed[0].get('txn'))
                tx0 = transaction.Transaction.undictify(msgpack.unpackb(b0, raw=False))
                stx0 = tx0.sign(sponsor_sk)

                # Sign admin appcall
                app_b64 = (res.transactions_to_sign or [])[0].get('txn')
                tx1 = transaction.Transaction.undictify(msgpack.unpackb(base64.b64decode(app_b64), raw=False))
                stx1 = tx1.sign(admin_sk)

                try:
                    txid = client.send_transactions([stx0, stx1])
                except Exception as send_err:
                    self.message_user(request, f'Trade {trade.id}: submit error: {send_err}', level='error')
                    failures += 1
                    continue
                try:
                    transaction.wait_for_confirmation(client, stx1.get_txid(), 6)
                except Exception:
                    pass

                # Update local records
                try:
                    dispute = trade.dispute_details
                    dispute.status = 'RESOLVED'
                    dispute.resolution_type = 'REFUND_BUYER' if winner_side == 'BUYER' else 'RELEASE_TO_SELLER'
                    dispute.resolution_notes = f'Resolved on-chain by {request.user.username}'
                    dispute.resolved_at = timezone.now()
                    dispute.resolved_by = request.user
                    dispute.save()
                except P2PDispute.DoesNotExist:
                    pass

                # Update trade status
                if winner_side == 'BUYER':
                    trade.status = 'CANCELLED'
                else:
                    trade.status = 'COMPLETED'
                    trade.completed_at = timezone.now()
                trade.updated_at = timezone.now()
                trade.save()

                # Notify both parties about the dispute resolution result
                try:
                    from notifications.utils import create_p2p_dispute_resolution_notifications
                    resolved_type = 'REFUND_BUYER' if winner_side == 'BUYER' else 'RELEASE_TO_SELLER'
                    create_p2p_dispute_resolution_notifications(
                        trade=trade,
                        resolution_type=resolved_type,
                        resolution_amount=str(trade.crypto_amount),
                        admin_notes=f"Resuelto en cadena por {request.user.username}",
                    )
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Failed sending dispute resolution notifications')

                successes += 1
            except Exception:
                failures += 1
                continue

        self.message_user(request, f'On-chain dispute resolution completed: {successes} succeeded, {failures} failed.')

    def resolve_dispute_refund_buyer_onchain(self, request, queryset):
        return self._resolve_onchain(request, queryset, 'BUYER')
    resolve_dispute_refund_buyer_onchain.short_description = '🟢 Resolver disputa en cadena: Reembolso al comprador'

    def resolve_dispute_release_seller_onchain(self, request, queryset):
        return self._resolve_onchain(request, queryset, 'SELLER')
    resolve_dispute_release_seller_onchain.short_description = '🔵 Resolver disputa en cadena: Liberar al vendedor'

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
        'stats_entity_display', 'verification_level', 'is_verified', 'total_trades', 'completed_trades', 'success_rate', 
        'avg_rating_display', 'rating_count', 'avg_response_time'
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


@admin.register(PremiumUpgradeRequest)
class PremiumUpgradeRequestAdmin(admin.ModelAdmin):
    list_display = ['context_display', 'status_badge', 'created_at', 'reviewed_by', 'reviewed_at']
    list_filter = ['status', ('user', admin.RelatedOnlyFieldListFilter), ('business', admin.RelatedOnlyFieldListFilter)]
    search_fields = ['user__username', 'business__name', 'reason']
    readonly_fields = ['created_at', 'updated_at', 'reviewed_at']
    actions = ['approve_requests', 'reject_requests']

    fieldsets = (
        ('Context', {
            'fields': ('user', 'business'),
            'description': 'Request applies to either a personal user or a business account.'
        }),
        ('Request', {
            'fields': ('reason',)
        }),
        ('Review', {
            'fields': ('status', 'review_notes', 'reviewed_by', 'reviewed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def context_display(self, obj):
        if obj.business:
            return f"🏢 {obj.business.name}"
        if obj.user:
            return f"👤 {obj.user.username}"
        return 'Unknown'
    context_display.short_description = 'Context'

    def status_badge(self, obj):
        color = {'pending': '#F59E0B', 'approved': '#10B981', 'rejected': '#EF4444'}.get(obj.status, '#6B7280')
        label = obj.get_status_display()
        return format_html('<span style="padding:2px 6px;border-radius:10px;background:{};color:white;">{}</span>', color, label)
    status_badge.short_description = 'Status'

    def approve_requests(self, request, queryset):
        from django.utils import timezone
        approved = 0
        for req in queryset.select_related('user', 'business'):
            try:
                if req.status != 'pending':
                    continue
                # Upgrade stats to level 2 for the appropriate context
                if req.business:
                    stats, _ = P2PUserStats.objects.get_or_create(stats_business=req.business, defaults={'user': req.user or request.user})
                else:
                    stats, _ = P2PUserStats.objects.get_or_create(stats_user=req.user or request.user, defaults={'user': req.user or request.user})
                if (stats.verification_level or 0) < 2:
                    stats.verification_level = 2
                    stats.save(update_fields=['verification_level'])

                req.status = 'approved'
                req.reviewed_by = request.user
                req.reviewed_at = timezone.now()
                req.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
                approved += 1
            except Exception:
                continue
        self.message_user(request, f'Approved {approved} premium requests.')
    approve_requests.short_description = 'Approve selected requests (set level 2)'

    def reject_requests(self, request, queryset):
        from django.utils import timezone
        rejected = 0
        for req in queryset:
            if req.status != 'pending':
                continue
            req.status = 'rejected'
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
            rejected += 1
        self.message_user(request, f'Rejected {rejected} premium requests.')
    reject_requests.short_description = 'Reject selected requests'
    
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
        'evidence_code', 'duration_display', 'resolution_display', 'opened_at'
    ]
    list_filter = [
        'status', 'priority', 'resolution_type', 'opened_at', 'resolved_at',
        ('initiator_user', admin.RelatedOnlyFieldListFilter),
        ('initiator_business', admin.RelatedOnlyFieldListFilter),
        ('resolved_by', admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        'trade__id', 'reason', 'resolution_notes', 'admin_notes', 'evidence_code',
        'initiator_user__username', 'initiator_business__name'
    ]
    readonly_fields = [
        'trade', 'opened_at', 'last_updated', 'duration_display', 
        'trade_details', 'evidence_code', 'code_generated_at', 'code_expires_at'
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
        try:
            start = getattr(obj, 'opened_at', None)
            end = getattr(obj, 'resolved_at', None) or timezone.now()
            if not start:
                return format_html('<span style="color: #999;">N/A</span>')
            delta = end - start
            hours = delta.total_seconds() / 3600.0
        except Exception:
            return format_html('<span style="color: #999;">N/A</span>')
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
    
    # Legacy evidence_display removed; rely on inline evidences
    
    fieldsets = (
        ('Dispute Information', {
            'fields': ('trade', 'status', 'priority', 'reason')
        }),
        ('Initiator', {
            'fields': ('initiator_user', 'initiator_business')
        }),
        ('Notes', {
            'fields': ('evidence_code', 'code_generated_at', 'code_expires_at', 'admin_notes')
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

class P2PDisputeEvidenceInline(admin.TabularInline):
    model = P2PDisputeEvidence
    extra = 0
    readonly_fields = ['preview_link', 'uploaded_at', 'uploader_user', 'uploader_business', 'content_type', 'size_bytes', 'status']
    fields = ['preview_link', 'content_type', 'size_bytes', 'status', 'uploaded_at', 'uploader_user', 'uploader_business']

    def preview_link(self, obj):
        try:
            from security.s3_utils import key_from_url, generate_presigned_get
            from django.conf import settings
            key = obj.s3_key or key_from_url(obj.url)
            if not key:
                return '-'
            signed = generate_presigned_get(key=key, expires_in_seconds=300, bucket=getattr(settings, 'AWS_DISPUTE_BUCKET', None))
            return format_html("<a href='{}' target='_blank'>Abrir evidencia</a>", signed)
        except Exception:
            return '-'
    preview_link.short_description = 'Preview'

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

# Attach inline to dispute admin
existing_inlines = getattr(P2PDisputeAdmin, 'inlines', ())
P2PDisputeAdmin.inlines = tuple(list(existing_inlines) + [P2PDisputeEvidenceInline])


@admin.register(P2PDisputeEvidence)
class P2PDisputeEvidenceAdmin(admin.ModelAdmin):
    list_display = ['id', 'dispute_link', 'trade_link', 'uploader_user', 'uploader_business', 'content_type', 'size_bytes', 'status', 'uploaded_at']
    list_filter = ['status', 'content_type', 'uploaded_at', ('uploader_user', admin.RelatedOnlyFieldListFilter), ('uploader_business', admin.RelatedOnlyFieldListFilter)]
    search_fields = ['dispute__id', 'trade__id', 'uploader_user__username', 'uploader_business__name', 's3_key']
    readonly_fields = ['preview_link', 'signed_url_link', 'dispute', 'trade', 'uploader_user', 'uploader_business', 's3_bucket', 's3_key', 'content_type', 'size_bytes', 'sha256', 'etag', 'confio_code', 'metadata', 'source', 'status', 'uploaded_at']
    fields = ['preview_link', 'signed_url_link', 'dispute', 'trade', 'uploader_user', 'uploader_business', 'content_type', 'size_bytes', 'status', 'uploaded_at', 's3_bucket', 's3_key', 'sha256', 'etag', 'confio_code', 'source', 'metadata']

    def dispute_link(self, obj):
        url = reverse('admin:p2p_exchange_p2pdispute_change', args=[obj.dispute_id])
        return format_html("<a href='{}'>#{}</a>", url, obj.dispute_id)
    dispute_link.short_description = 'Dispute'

    def trade_link(self, obj):
        url = reverse('admin:p2p_exchange_p2ptrade_change', args=[obj.trade_id])
        return format_html("<a href='{}'>#{}</a>", url, obj.trade_id)
    trade_link.short_description = 'Trade'

    def preview_link(self, obj):
        try:
            from security.s3_utils import key_from_url, generate_presigned_get
            from django.conf import settings
            key = obj.s3_key or key_from_url(obj.url)
            if not key:
                return '-'
            signed = generate_presigned_get(key=key, expires_in_seconds=300, bucket=getattr(settings, 'AWS_DISPUTE_BUCKET', None))
            return format_html("<a href='{}' target='_blank'>Abrir evidencia</a>", signed)
        except Exception:
            return '-'
    
    def signed_url_link(self, obj):
        """Always present a temporary signed URL instead of raw URLField (private bucket)."""
        try:
            from security.s3_utils import key_from_url, generate_presigned_get
            from django.conf import settings
            key = obj.s3_key or key_from_url(obj.url)
            if not key:
                return '-'
            signed = generate_presigned_get(key=key, expires_in_seconds=300, bucket=getattr(settings, 'AWS_DISPUTE_BUCKET', None))
            return format_html("<a href='{}' target='_blank'>{}</a>", signed, 'URL (presigned)')
        except Exception:
            return '-'
    signed_url_link.short_description = 'Signed URL'



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
