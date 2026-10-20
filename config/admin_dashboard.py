"""
Custom Admin Dashboard for Confío
Today (needs attention / money / growth) plus one page per area; the
section builders live in config/admin_dashboard_sections.py.
"""
import time

from django.contrib import admin
from two_factor.admin import AdminSiteOTPRequired
from django.urls import path, reverse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Count, Sum, Q, F, Avg
from django.db.models.functions import Cast, TruncDate
from django.db.models import DecimalField
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.html import format_html
from django.contrib import messages
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from users.models import User, Account, Business, Country, Bank, BankInfo, WalletPepper, WalletDerivationPepper
from security.models import IdentityVerification, DeviceFingerprint
from achievements.admin_views import achievement_dashboard
from achievements.models import (
    UserAchievement,
    ReferralWithdrawalLog,
    ConfioRewardTransaction,
    UserReferral,
    ReferralRewardEvent,
)
from p2p_exchange.models import P2POffer, P2PTrade, P2PUserStats, P2PDispute
from send.models import SendTransaction
from payments.models import PaymentTransaction
from inbox.models import ContentPlatformClick
from config import admin_dashboard_sections as sections
from config.admin_dashboard_sections import get_fcm_reachability_metrics  # noqa: F401 — re-exported for tests


class ConfioAdminSite(AdminSiteOTPRequired):
    """Custom admin site with enhanced dashboard"""
    site_header = 'Confío Admin Panel'
    site_title = 'Confío Admin'
    index_title = 'Welcome to Confío Administration'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('', self.admin_view(self.dashboard_view), name='index'),
            path('dashboard/', self.admin_view(self.dashboard_view), name='dashboard'),
            # Django's own model index, shadowed at '' by the dashboard.
            path('models/', self.admin_view(self.index), name='app_list_index'),
            *[
                path(f'dashboard/{key}/', self.admin_view(self._dash_view(key)), name=f'dash_{key}')
                for key, *_ in self.DASH_PAGES if key != 'today'
            ],
            path('p2p-analytics/', self.admin_view(self.p2p_analytics_view), name='p2p_analytics'),
            path('user-analytics/', self.admin_view(self.user_analytics_view), name='user_analytics'),
            path('transaction-analytics/', self.admin_view(self.transaction_analytics_view), name='transaction_analytics'),
            path('blockchain-analytics/', self.admin_view(self.blockchain_analytics_view), name='blockchain_analytics'),
            path('blockchain-analytics/scan-now/', self.admin_view(self.blockchain_scan_now_view), name='blockchain_scan_now'),
            path('achievements/', self.admin_view(self.achievement_dashboard_view), name='achievement_dashboard'),
            path('icp-rating-analytics/', self.admin_view(self.icp_rating_analytics_view), name='icp_rating_analytics'),
        ]
        return custom_urls + urls
    
    # ── Dashboard pages ──────────────────────────────────────────────────
    # Each page lists the section builders it needs and the partials that
    # render them; nothing is computed for a page that does not show it.

    def _dash_tabs(self):
        tabs = []
        for key, label, _builders, _partials, _opts in self.DASH_PAGES:
            tabs.append({
                'key': key,
                'label': label,
                'url': reverse('confio_admin:dashboard' if key == 'today' else f'confio_admin:dash_{key}'),
                'gap': key == 'archive',
            })
        tabs.append({'key': 'models', 'label': 'Models', 'url': reverse('confio_admin:app_list_index')})
        return tabs

    def _dash_render(self, request, key):
        page = next(p for p in self.DASH_PAGES if p[0] == key)
        _key, label, builders, partials, opts = page
        started = time.perf_counter()
        w = sections.Window.current()
        refresh = request.GET.get('refresh') == '1'
        context = dict(self.each_context(request), title=label)
        # The model sidebar would take a third of the width; the full model
        # list stays one click away under the "Models" tab.
        context['is_nav_sidebar_enabled'] = False
        for build in builders:
            context.update(build(w, request, refresh))
        query = request.GET.copy()
        query['refresh'] = '1'
        context.update({
            'dash_active': key,
            'dash_heading': opts.get('heading', label),
            'dash_tabs': self._dash_tabs(),
            'dash_partials': partials,
            'dash_intro': opts.get('intro', ''),
            'dash_tools': [
                {'label': tool_label, 'url': url}
                for tool_label, name, q in opts.get('tools', ())
                if (url := sections._url(name, q))
            ],
            'dash_has_chain': opts.get('chain', False),
            'dash_refresh_query': query.urlencode(),
            'dash_as_of_label': w.now.astimezone(sections.ARG_TZ).strftime('%a %-d %b, %H:%M'),
            'dash_build_ms': (time.perf_counter() - started) * 1000,
        })
        if 'metrics_trend' in context:
            context['metrics_trend_chart'] = sections.trend_chart(context['metrics_trend'])
        return render(request, opts.get('template', 'admin/dash/page.html'), context)

    def dashboard_view(self, request):
        return self._dash_render(request, 'today')

    def _dash_view(self, key):
        def view(request):
            return self._dash_render(request, key)
        return view

    def p2p_analytics_view(self, request):
        """Detailed P2P trading analytics"""
        context = dict(
            self.each_context(request),
            title="P2P Trading Analytics",
        )
        
        # Get date range from request
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Trading volume by day
        daily_trades = P2PTrade.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(p2p_exchange_p2ptrade.created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            cusd_volume=Sum('crypto_amount', filter=Q(offer__token_type='cUSD')),
            confio_volume=Sum('crypto_amount', filter=Q(offer__token_type='CONFIO'))
        ).order_by('day')
        
        context['daily_trades'] = list(daily_trades)
        
        # Top traders
        top_traders = P2PUserStats.objects.select_related(
            'stats_user', 'stats_business'
        ).annotate(
            success_ratio=F('success_rate')
        ).order_by('-total_trades')[:20]
        
        context['top_traders'] = top_traders
        
        # Payment method popularity
        payment_methods = P2PTrade.objects.filter(
            created_at__gte=start_date
        ).values(
            'payment_method__display_name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        context['payment_methods'] = payment_methods
        
        # Country performance
        country_performance = P2PTrade.objects.filter(
            created_at__gte=start_date
        ).values('country_code').annotate(
            trade_count=Count('id'),
            avg_completion_time=Avg(
                F('completed_at') - F('created_at'),
                filter=Q(status='COMPLETED')
            ),
            dispute_rate=Count('id', filter=Q(status='DISPUTED')) * 100.0 / Count('id')
        ).order_by('-trade_count')
        
        context['country_performance'] = country_performance
        
        return render(request, 'admin/p2p_analytics.html', context)
    
    def user_analytics_view(self, request):
        """User growth and engagement analytics"""
        context = dict(
            self.each_context(request),
            title="User Analytics",
        )
        
        # User growth by day
        from django.db.models.functions import TruncDate

        # User growth by day (Argentina Time)
        tz = ZoneInfo('America/Argentina/Buenos_Aires')
        days = int(request.GET.get('days', 30))
        
        # Calculate start date in Argentina time (midnight 30 days ago)
        now_arg = timezone.now().astimezone(tz)
        start_date_arg = (now_arg - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_date_utc = start_date_arg.astimezone(dt_timezone.utc)
        
        daily_signups = User.objects.exclude(is_platform_test_account=True).filter(
            phone_number__isnull=False,
            created_at__gte=start_date_utc
        ).annotate(
            day=TruncDate('created_at', tzinfo=tz)
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
        context['daily_signups'] = list(daily_signups)
        
        # Verification funnel
        context['users_total'] = User.objects.exclude(is_platform_test_account=True).filter(phone_number__isnull=False).count()
        from security.identity_status import PERSONAL, verified_user_ids
        context['users_with_verification'] = IdentityVerification.all_documents.filter(PERSONAL).values(
            'user'
        ).distinct().count()
        context['users_verified'] = verified_user_ids().count()
        context['verification_completion_rate'] = (
            context['users_verified'] / context['users_with_verification'] * 100
            if context['users_with_verification'] else 0
        )
        
        # Account type distribution
        account_types = Account.objects.values(
            'account_type'
        ).annotate(
            count=Count('id')
        ).order_by('account_type')
        
        context['account_types'] = account_types
        
        # User activity metrics (using centralized last_activity_at)
        # All activity periods now use the same consistent method
        active_ranges = [
            ('Last 24h', 1),
            ('Last 7 days', 7),
            ('Last 30 days', 30),
            ('Last 90 days', 90),
        ]

        activity_metrics = []
        for label, days in active_ranges:
            cutoff = timezone.now() - timedelta(days=days)
            count = User.objects.exclude(is_platform_test_account=True).filter(phone_number__isnull=False, last_activity_at__gte=cutoff).count()
            activity_metrics.append({
                'label': label,
                'count': count,
                'percentage': (count / context['users_total'] * 100) if context['users_total'] > 0 else 0
            })

        context['activity_metrics'] = activity_metrics
        
        return render(request, 'admin/user_analytics.html', context)
    
    def transaction_analytics_view(self, request):
        """Transaction flow analytics"""
        context = dict(
            self.each_context(request),
            title="Transaction Analytics",
        )
        
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Send transactions by day
        daily_sends = SendTransaction.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(send_sendtransaction.created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            # SendTransaction.TOKEN_TYPES stores 'CUSD', not 'cUSD' — the
            # lowercase filter this used matched nothing and reported a flat
            # zero cUSD column for the life of the page.
            cusd_count=Count('id', filter=Q(token_type='CUSD')),
            cusd_plus_count=Count('id', filter=Q(token_type='CUSD_PLUS')),
            usdt_count=Count('id', filter=Q(token_type='USDT')),
            confio_count=Count('id', filter=Q(token_type='CONFIO')),
            failed_count=Count('id', filter=Q(status='FAILED'))
        ).order_by('day')

        context['daily_sends'] = list(daily_sends)

        # Payment transactions by day
        daily_payments = PaymentTransaction.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(payments_paymenttransaction.created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            cusd_count=Count('id', filter=Q(token_type='CUSD')),
            cusd_plus_count=Count('id', filter=Q(token_type='CUSD_PLUS')),
            usdt_count=Count('id', filter=Q(token_type='USDT')),
            confio_count=Count('id', filter=Q(token_type='CONFIO'))
        ).order_by('day')

        context['daily_payments'] = list(daily_payments)

        # Rail split. `token_type` is what actually moved on-chain, so this
        # is the migration read-out: how much of the volume has left the
        # Algorand rail for BSC.
        from conversion.models import Conversion

        def _rail_split(queryset):
            totals = queryset.aggregate(
                algorand=Count('id', filter=Q(token_type__in=['CUSD', 'USDC', 'ALGO'])),
                bsc=Count('id', filter=Q(token_type__in=['CUSD_PLUS', 'USDT'])),
                confio=Count('id', filter=Q(token_type='CONFIO')),
            )
            counted = totals['algorand'] + totals['bsc'] + totals['confio']
            # CONFIO trades on both chains, so it is reported on its own
            # rather than folded into either rail's share.
            dollar_total = totals['algorand'] + totals['bsc']
            totals['bsc_pct'] = (totals['bsc'] / dollar_total * 100) if dollar_total else 0
            totals['unclassified'] = queryset.count() - counted
            return totals

        context['send_rail_split'] = _rail_split(
            SendTransaction.objects.filter(created_at__gte=start_date).exclude(status='FAILED')
        )
        context['payment_rail_split'] = _rail_split(
            PaymentTransaction.objects.filter(created_at__gte=start_date).exclude(status='FAILED')
        )

        # Transaction types breakdown
        transaction_types = {
            'P2P Trades': P2PTrade.objects.filter(
                created_at__gte=start_date,
                status__in=['COMPLETED', 'CRYPTO_RELEASED']
            ).count(),
            'Direct Sends': SendTransaction.objects.filter(
                created_at__gte=start_date
            ).exclude(status='FAILED').count(),
            'Merchant Payments': PaymentTransaction.objects.filter(
                created_at__gte=start_date
            ).exclude(status='FAILED').count(),
            'Algorand Conversions': Conversion.objects.filter(
                created_at__gte=start_date, is_deleted=False,
            ).exclude(conversion_type__in=Conversion.SAVINGS_TYPES).count(),
            'cUSD+ Savings Sagas': Conversion.objects.filter(
                created_at__gte=start_date, is_deleted=False,
                conversion_type__in=Conversion.SAVINGS_TYPES,
            ).count(),
        }

        context['transaction_types'] = transaction_types

        # Success rates
        send_total = SendTransaction.objects.filter(created_at__gte=start_date).count()
        send_success = SendTransaction.objects.filter(
            created_at__gte=start_date,
            status='CONFIRMED'
        ).count()
        
        payment_total = PaymentTransaction.objects.filter(created_at__gte=start_date).count()
        payment_success = PaymentTransaction.objects.filter(
            created_at__gte=start_date,
            status='CONFIRMED'
        ).count()
        
        context['send_success_rate'] = (send_success / send_total * 100) if send_total > 0 else 0
        context['payment_success_rate'] = (payment_success / payment_total * 100) if payment_total > 0 else 0
        
        return render(request, 'admin/transaction_analytics.html', context)
    
    def achievement_dashboard_view(self, request):
        """Achievement system dashboard - delegate to the dedicated view"""
        from achievements.admin_views import achievement_dashboard as dashboard_func
        return dashboard_func(request)
    
    def blockchain_analytics_view(self, request):
        """Blockchain integration analytics (event/log tracking removed)"""
        from blockchain.models import (
            Balance, IndexerAssetCursor, ProcessedIndexerTransaction, SponsoredBatch,
        )

        context = dict(
            self.each_context(request),
            title="Blockchain Analytics",
        )
        
        # Get date range from request
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Balance cache metrics
        context['total_cached_balances'] = Balance.objects.count()
        context['stale_balances'] = Balance.objects.filter(is_stale=True).count()
        context['recently_synced'] = Balance.objects.filter(
            last_synced__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        # Token distribution
        token_balances = Balance.objects.values('token').annotate(
            count=Count('id'),
            total_amount=Sum('amount'),
            avg_amount=Avg('amount')
        ).order_by('token')
        
        context['token_balances'] = token_balances

        # Processing performance removed — no TransactionProcessingLog

        # Balance freshness distribution
        now = timezone.now()
        freshness_ranges = [
            ('< 5 min', timedelta(minutes=5)),
            ('< 30 min', timedelta(minutes=30)),
            ('< 1 hour', timedelta(hours=1)),
            ('< 6 hours', timedelta(hours=6)),
            ('< 24 hours', timedelta(hours=24)),
            ('> 24 hours', None),
        ]
        
        freshness_stats = []
        for label, delta in freshness_ranges:
            if delta:
                count = Balance.objects.filter(
                    last_synced__gte=now - delta
                ).count()
            else:
                count = Balance.objects.filter(
                    last_synced__lt=now - timedelta(hours=24)
                ).count()
            
            freshness_stats.append({
                'label': label,
                'count': count,
                'percentage': (count / context['total_cached_balances'] * 100) if context['total_cached_balances'] > 0 else 0
            })
        
        context['freshness_stats'] = freshness_stats
        
        # Network health check
        from django.conf import settings
        context['network'] = getattr(settings, 'ALGORAND_NETWORK', 'Unknown')
        context['algod_url'] = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', 'Not configured')
        context['indexer_url'] = getattr(settings, 'ALGORAND_INDEXER_ADDRESS', 'Not configured')
        # Try to fetch live health from Algod and Indexer
        algod_health = {'ok': False}
        indexer_health = {'ok': False}
        try:
            from algosdk.v2client import indexer as _indexer
            from blockchain.algorand_client import get_algod_client
            algod_client = get_algod_client()
            status = algod_client.status()
            algod_health = {
                'ok': True,
                'last_round': status.get('last-round'),
                'catchup_time': status.get('catchup-time')
            }
        except Exception:
            pass
        try:
            from blockchain.algorand_client import get_indexer_client
            idx_client = get_indexer_client()
            h = idx_client.health()
            indexer_health = {'ok': True, 'round': h.get('round')}
        except Exception:
            pass
        context['algod_health'] = algod_health
        context['indexer_health'] = indexer_health
        current_round = (indexer_health.get('round') if isinstance(indexer_health, dict) else None) or (
            algod_health.get('last_round') if isinstance(algod_health, dict) else None
        ) or 0
        context['current_round'] = current_round
        
        # Recent blockchain events removed — no RawBlockchainEvent model

        # Indexer cursor status (per asset)
        from django.conf import settings as _settings
        assets = []
        asset_map = [
            ('USDC', getattr(_settings, 'ALGORAND_USDC_ASSET_ID', None)),
            ('cUSD', getattr(_settings, 'ALGORAND_CUSD_ASSET_ID', None)),
            ('CONFIO', getattr(_settings, 'ALGORAND_CONFIO_ASSET_ID', None)),
        ]
        for name, asset_id in asset_map:
            if not asset_id:
                continue
            cursor = IndexerAssetCursor.objects.filter(asset_id=asset_id).first()
            assets.append({
                'token': name,
                'asset_id': asset_id,
                'last_scanned_round': getattr(cursor, 'last_scanned_round', 0),
                'lag': max(0, current_round - (getattr(cursor, 'last_scanned_round', 0) or 0)),
                'updated_at': getattr(cursor, 'updated_at', None),
            })
        context['indexer_cursors'] = assets

        # Recent processed inbound markers count
        context['processed_markers_recent'] = ProcessedIndexerTransaction.objects.filter(
            created_at__gte=start_date
        ).count()
        context['recent_processed'] = ProcessedIndexerTransaction.objects.order_by('-created_at')[:20]

        # ── BNB Smart Chain (cUSD+ rail) ──────────────────────────────────
        # Everything above this line is Algorand. The BSC rail has no
        # Balance cache and no indexer (balances are read from the chain per
        # request), so its health is a different set of numbers: scanner
        # cursor lag, sponsor fuel, vault collateral, and the sponsored-batch
        # outcome ledger.
        from cusd_plus.metrics import (
            get_bsc_scanner_health,
            get_cusd_plus_platform_metrics,
            get_sponsor_balance,
            get_sponsorship_stats,
        )
        context['bsc_scanner'] = get_bsc_scanner_health()
        context['bsc_sponsor'] = get_sponsor_balance()
        context['cusd_plus_metrics'] = get_cusd_plus_platform_metrics()
        context['bsc_sponsorship_stats'] = get_sponsorship_stats(since=start_date)
        context['recent_sponsored_batches'] = SponsoredBatch.objects.select_related(
            'user'
        ).order_by('-created_at')[:20]

        return render(request, 'admin/blockchain_analytics.html', context)

    def blockchain_scan_now_view(self, request):
        """Trigger an immediate indexer scan via Celery (and update address cache)."""
        from blockchain.tasks import update_address_cache, scan_inbound_deposits
        if request.method == 'POST':
            try:
                update_address_cache.delay()
                scan_inbound_deposits.delay()
                messages.success(request, 'Scan triggered. Check back in a moment for updated rounds.')
            except Exception:
                # As a fallback, attempt synchronous execution (may take time)
                try:
                    update_address_cache()
                    scan_inbound_deposits()
                    messages.warning(request, 'Celery unavailable; ran scan synchronously.')
                except Exception as e:
                    messages.error(request, f'Failed to trigger scan: {e}')
        return redirect('admin:blockchain_analytics')

    def icp_rating_analytics_view(self, request):
        """ICP capture + Rating modal analytics.

        Renders four sections:
          - Headline counters
          - Free-text inbox (ICP "Otra razón" + Rating feedback), newest first
          - Rating cross-tab (star × action)
          - ICP tag distribution (per country) + co-occurrence matrix
        """
        from collections import Counter

        now = timezone.now()

        # Headline counters
        icp_captured = User.objects.filter(confio_icp_captured_at__isnull=False).count()
        icp_skipped = User.objects.filter(
            confio_icp_captured_at__isnull=False, confio_icp_tags=[]
        ).count()
        icp_with_tags = icp_captured - icp_skipped
        rating_prompted = User.objects.filter(confio_rating_prompted_at__isnull=False).count()
        rating_with_stars = User.objects.filter(
            confio_rating_prompted_at__isnull=False, confio_rating_star_count__isnull=False
        ).count()

        # Free-text inbox — union of two sources, sorted newest-first
        icp_freetext = list(
            User.objects.filter(confio_icp_other_text__isnull=False)
            .exclude(confio_icp_other_text='')
            .values('id', 'username', 'first_name', 'last_name', 'phone_country',
                    'confio_icp_captured_at', 'confio_icp_other_text', 'confio_icp_tags')
        )
        for row in icp_freetext:
            row['source'] = 'ICP'
            row['ts'] = row['confio_icp_captured_at']
            row['text'] = row['confio_icp_other_text']
        rating_freetext = list(
            User.objects.filter(confio_rating_feedback_text__isnull=False)
            .exclude(confio_rating_feedback_text='')
            .values('id', 'username', 'first_name', 'last_name', 'phone_country',
                    'confio_rating_prompted_at', 'confio_rating_feedback_text',
                    'confio_rating_star_count')
        )
        for row in rating_freetext:
            row['source'] = 'Rating'
            row['ts'] = row['confio_rating_prompted_at']
            row['text'] = row['confio_rating_feedback_text']
        feedback_inbox = sorted(
            icp_freetext + rating_freetext, key=lambda r: r['ts'] or now, reverse=True
        )[:200]

        # Rating cross-tab: rows = star count (1..5), cols = action (FEEDBACK/STORE/SKIP)
        cross_qs = (
            User.objects
            .filter(confio_rating_prompted_at__isnull=False, confio_rating_star_count__isnull=False)
            .values('confio_rating_star_count', 'confio_rating_action')
            .annotate(n=Count('id'))
        )
        rating_actions = ['FEEDBACK', 'STORE', 'SKIP']
        rating_cross = {s: {a: 0 for a in rating_actions} for s in range(1, 6)}
        for row in cross_qs:
            s = row['confio_rating_star_count']
            a = row['confio_rating_action'] or 'SKIP'
            if s in rating_cross and a in rating_cross[s]:
                rating_cross[s][a] = row['n']
        rating_cross_rows = [
            {'stars': s, 'cells': [rating_cross[s][a] for a in rating_actions], 'total': sum(rating_cross[s].values())}
            for s in range(1, 6)
        ]
        rating_cross_totals = [
            sum(rating_cross[s][a] for s in range(1, 6)) for a in rating_actions
        ]

        # ICP tag distribution per country (flatten the ArrayField)
        tag_labels = {
            'proteger_ahorros': 'Proteger ahorros',
            'generar_rendimiento': 'Generar rendimiento',
            'comprar_confio': 'Comprar CONFIO',
            'enviar_recibir_pagos': 'Enviar/recibir pagos',
            'importacion_exportacion': 'Importación/exportación',
            'otra': 'Otra razón',
        }
        country_tag_counts = {}
        global_tag_counts = Counter()
        for u in User.objects.filter(confio_icp_captured_at__isnull=False).only(
            'phone_country', 'confio_icp_tags'
        ):
            country = u.phone_country or 'UNK'
            country_tag_counts.setdefault(country, Counter())
            for tag in (u.confio_icp_tags or []):
                country_tag_counts[country][tag] += 1
                global_tag_counts[tag] += 1
        # Build a stable column order based on overall popularity
        tag_columns = [t for t, _ in global_tag_counts.most_common()]
        if not tag_columns:
            tag_columns = list(tag_labels.keys())
        country_rows = []
        for country, counts in sorted(country_tag_counts.items(), key=lambda kv: -sum(kv[1].values())):
            country_rows.append({
                'country': country,
                'cells': [counts.get(t, 0) for t in tag_columns],
                'total': sum(counts.values()),
            })

        # ICP co-occurrence matrix (square, ordered by global tag popularity)
        co_counts = {a: Counter() for a in tag_columns}
        for u in User.objects.filter(confio_icp_captured_at__isnull=False).only('confio_icp_tags'):
            tags = sorted(set(u.confio_icp_tags or []))
            for a in tags:
                if a not in co_counts:
                    continue
                for b in tags:
                    if b in co_counts[a]:
                        co_counts[a][b] += 1
                    else:
                        co_counts[a][b] = 1
        cooc_rows = []
        for a in tag_columns:
            cooc_rows.append({
                'tag': a,
                'label': tag_labels.get(a, a),
                'cells': [co_counts.get(a, {}).get(b, 0) for b in tag_columns],
            })

        context = dict(
            self.each_context(request),
            title='ICP + Rating Analytics',
            icp_captured=icp_captured,
            icp_skipped=icp_skipped,
            icp_with_tags=icp_with_tags,
            icp_response_rate=(icp_with_tags / icp_captured * 100) if icp_captured else 0,
            rating_prompted=rating_prompted,
            rating_with_stars=rating_with_stars,
            feedback_inbox=feedback_inbox,
            rating_actions=rating_actions,
            rating_cross_rows=rating_cross_rows,
            rating_cross_totals=rating_cross_totals,
            tag_labels=tag_labels,
            tag_columns=tag_columns,
            tag_column_labels=[tag_labels.get(t, t) for t in tag_columns],
            country_rows=country_rows,
            cooc_rows=cooc_rows,
        )
        return render(request, 'admin/icp_rating_analytics.html', context)


# Create custom admin site instance
def _w(fn):
    """Adapt a builder that only needs the window."""
    return lambda w, request, refresh: fn(w)


def _chain(fn):
    """Adapt a builder that reads the chain (honours ?refresh=1)."""
    return lambda w, request, refresh: fn(w, refresh=refresh)


ConfioAdminSite.DASH_PAGES = [
    ('today', 'Today', [
        lambda w, request, refresh: {'attention': sections.needs_attention(w, request, refresh=refresh)},
        _chain(sections.today_money),
        _w(sections.today_growth),
    ], [], {'template': 'admin/dash/today.html', 'chain': True, 'heading': 'Today'}),
    ('money', 'Money & rails', [
        _chain(sections.cusd_bsc),
        lambda w, request, refresh: sections.infinia(request),
        lambda w, request, refresh: sections.koywe(w, request),
        _w(sections.guardarian),
    ], [
        'admin/dash/_cusd_bsc.html',
        'admin/dash/_fee_revenue.html',
        'admin/_infinia_dashboard.html',
        'admin/dash/_koywe.html',
        'admin/dash/_guardarian.html',
    ], {'chain': True, 'tools': (
        ('Ramp transactions', 'ramps_ramptransaction_changelist', ''),
        ('Infinia transfers', 'payment_accounts_infiniajourney_changelist', ''),
        ('Conversions', 'conversion_conversion_changelist', ''),
        ('Transaction analytics', 'transaction_analytics', ''),
    )}),
    ('savings', 'Savings & investing', [
        _chain(sections.cusd_plus),
        _chain(sections.stocks),
        _w(sections.crypto),
    ], [
        'admin/dash/_cusd_plus.html',
        'admin/dash/_stocks.html',
        'admin/dash/_crypto.html',
    ], {'chain': True, 'tools': (
        ('Stock trades', 'blockchain_ondostocktrade_changelist', ''),
        ('Crypto swaps', 'blockchain_cryptoswaptrade_changelist', ''),
        ('Stock holdings', 'blockchain_stockholdings_changelist', ''),
    )}),
    ('growth', 'Growth', [
        _w(sections.users_core),
        _w(sections.os_stats),
        _w(sections.content),
    ], [
        'admin/dash/_users.html',
        'admin/dash/_os.html',
        'admin/dash/_content.html',
    ], {'tools': (
        ('User analytics', 'user_analytics', ''),
        ('Daily metrics', 'users_dailymetrics_changelist', ''),
        ('Country metrics', 'users_countrymetrics_changelist', ''),
        ('ICP + ratings', 'icp_rating_analytics', ''),
        ('Achievements', 'achievement_dashboard', ''),
    )}),
    ('funnels', 'Funnels', [
        _w(sections.funnels),
        _w(sections.referral_program),
    ], [
        'admin/dash/_send_invite_funnel.html',
        'admin/dash/_referral_funnel.html',
        'admin/dash/_referral_program.html',
    ], {'intro': 'Argentina calendar days. Completed days come from the nightly rollup; today and any unrolled day from raw events.',
        'tools': (
            ('Raw funnel events', 'users_funnelevent_changelist', ''),
            ('Daily rollups', 'users_funneldailyrollup_changelist', ''),
            ('Rail waitlist', 'users_localrailwaitlistentry_changelist', ''),
            ('Product waitlist', 'users_productwaitlistentry_changelist', ''),
        )}),
    ('risk', 'Identity & risk', [
        _w(sections.verifications),
        _w(sections.reward_security),
    ], [
        'admin/dash/_verifications.html',
        'admin/dash/_reward_security.html',
    ], {'tools': (
        ('Unfinished + in review', 'security_identityverification_changelist', 'status__exact=pending'),
        ('Suspicious activity', 'security_suspiciousactivity_changelist', ''),
        ('Bans', 'security_userban_changelist', ''),
    )}),
    ('platform', 'Platform', [
        _w(sections.sponsorship),
        _w(sections.messaging),
        _w(sections.balance_cache),
    ], [
        'admin/dash/_sponsorship.html',
        'admin/dash/_messaging.html',
        'admin/dash/_balance_cache.html',
    ], {'tools': (
        ('Sponsored batches', 'blockchain_sponsoredbatch_changelist', ''),
        ('Send broadcast', 'notifications_notification_broadcast', ''),
        ('Push stats', 'notifications_notification_stats', ''),
        ('Blockchain analytics', 'blockchain_analytics', ''),
    )}),
    ('archive', 'Archive', [
        _w(sections.disputes),
        _w(sections.legacy_cusd),
        _w(sections.legacy_conversions),
        _w(sections.presale),
        _w(sections.v2_security),
    ], [
        'admin/dash/_disputes.html',
        'admin/dash/_legacy_cusd.html',
        'admin/dash/_presale.html',
        'admin/dash/_v2_security.html',
    ], {'chain': True,
        'intro': 'Retired or paused products: P2P, a-cUSD on Algorand, the v1 presale and the V2 keyless migration.',
        'tools': (
            ('P2P analytics', 'p2p_analytics', ''),
            ('P2P disputes', 'p2p_exchange_p2pdispute_changelist', ''),
            ('Presale settings', 'presale_presalesettings_changelist', ''),
        )}),
]


confio_admin_site = ConfioAdminSite(name='confio_admin')

# Re-register all models with the custom admin site
from django.contrib.auth.models import Group
from users.admin import (
    UserAdmin, AccountAdmin, BusinessAdmin, CountryAdmin, BankAdmin, 
    BankInfoAdmin, UnifiedTransactionAdmin, BusinessEmployeeAdmin, 
    EmployeeInvitationAdmin, WalletPepperAdmin, WalletDerivationPepperAdmin
)
from security.admin import IdentityVerificationAdmin, SuspiciousActivityAdmin
from p2p_exchange.admin import (
    P2PPaymentMethodAdmin, P2POfferAdmin, P2PTradeAdmin, 
    P2PMessageAdmin, P2PUserStatsAdmin, P2PEscrowAdmin,
    P2PTradeRatingAdmin, P2PDisputeAdmin, P2PDisputeTransactionAdmin, P2PDisputeEvidenceAdmin,
    P2PFavoriteTraderAdmin, PremiumUpgradeRequestAdmin
)
from payments.admin import PaymentTransactionAdmin, InvoiceAdmin
from send.admin import SendTransactionAdmin, PhoneInviteAdmin
from conversion.admin import ConversionAdmin
from payroll.admin import PayrollRunAdmin, PayrollItemAdmin, PayrollRecipientAdmin
from payroll.models import PayrollRun, PayrollItem, PayrollRecipient
from inbox.models import (
    Channel,
    ChannelMembership,
    ActivityShareIntent,
    ActivityShareImpression,
    CommunityActivityShare,
    CommunityBlock,
    CommunityComment,
    CommunityFollow,
    CommunityProfileSettings,
    CommunityCommentReaction,
    CommunityCommentReport,
    CommunityPostReport,
    CommunityPostReview,
    CommunityRulesAcceptance,
    ProfilePictureSubmission,
    PublicObject,
    ContentItem,
    ContentPlatformClick,
    ContentPlatformClickDailyStat,
    ContentReadState,
    ContentReaction,
    ContentSurface,
    ReactionType,
    SupportConversation,
    SupportConversationState,
    SupportMessage,
)
from inbox.admin import (
    ChannelAdmin,
    ChannelMembershipAdmin,
    ActivityShareIntentAdmin,
    ActivityShareImpressionAdmin,
    CommunityActivityShareAdmin,
    CommunityBlockAdmin,
    CommunityFollowAdmin,
    CommunityProfileSettingsAdmin,
    CommunityCommentAdmin,
    CommunityCommentReactionAdmin,
    CommunityCommentReportAdmin,
    CommunityPostReportAdmin,
    CommunityPostReviewAdmin,
    CommunityRulesAcceptanceAdmin,
    ContentItemAdmin,
    ContentPlatformClickAdmin,
    ContentPlatformClickDailyStatAdmin,
    ContentReadStateAdmin,
    ContentReactionAdmin,
    ContentSurfaceAdmin,
    ProfilePictureSubmissionAdmin,
    PublicObjectAdmin,
    ReactionTypeAdmin,
    SupportConversationAdmin,
    SupportConversationStateAdmin,
    SupportMessageAdmin,
)

# Register with custom admin site
confio_admin_site.register(Group)
confio_admin_site.register(User, UserAdmin)
confio_admin_site.register(Account, AccountAdmin)
confio_admin_site.register(Business, BusinessAdmin)
# Security models
confio_admin_site.register(IdentityVerification, IdentityVerificationAdmin)
from security.models import SuspiciousActivity, UserBan, IPAddress, UserSession, DeviceFingerprint, UserDevice, AMLCheck, IntegrityVerdict
from security.admin import UserBanAdmin, IPAddressAdmin, UserSessionAdmin, DeviceFingerprintAdmin, UserDeviceAdmin, AMLCheckAdmin, IntegrityVerdictAdmin
confio_admin_site.register(SuspiciousActivity, SuspiciousActivityAdmin)
confio_admin_site.register(UserBan, UserBanAdmin)
confio_admin_site.register(IPAddress, IPAddressAdmin)
confio_admin_site.register(UserSession, UserSessionAdmin)
confio_admin_site.register(DeviceFingerprint, DeviceFingerprintAdmin)
confio_admin_site.register(UserDevice, UserDeviceAdmin)
confio_admin_site.register(AMLCheck, AMLCheckAdmin)
confio_admin_site.register(IntegrityVerdict, IntegrityVerdictAdmin)
from security.models import FaceReference, FaceCheck
from security.admin import FaceReferenceAdmin, FaceCheckAdmin
confio_admin_site.register(FaceReference, FaceReferenceAdmin)
confio_admin_site.register(FaceCheck, FaceCheckAdmin)
from security.models import DiditFaceBlocklistEntry
from security.admin import DiditFaceBlocklistEntryAdmin
confio_admin_site.register(DiditFaceBlocklistEntry, DiditFaceBlocklistEntryAdmin)
from security.models import AppVersionPolicy
from security.admin import AppVersionPolicyAdmin
confio_admin_site.register(AppVersionPolicy, AppVersionPolicyAdmin)
confio_admin_site.register(Country, CountryAdmin)
confio_admin_site.register(Bank, BankAdmin)
confio_admin_site.register(BankInfo, BankInfoAdmin)
confio_admin_site.register(WalletPepper, WalletPepperAdmin)
confio_admin_site.register(WalletDerivationPepper, WalletDerivationPepperAdmin)

# Payroll
confio_admin_site.register(PayrollRun, PayrollRunAdmin)
confio_admin_site.register(PayrollItem, PayrollItemAdmin)
confio_admin_site.register(PayrollRecipient, PayrollRecipientAdmin)

# Employee models
from users.models_employee import BusinessEmployee, EmployeeInvitation
confio_admin_site.register(BusinessEmployee, BusinessEmployeeAdmin)
confio_admin_site.register(EmployeeInvitation, EmployeeInvitationAdmin)

# CONFIO Reward models
from achievements.models import (
    ConfioRewardBalance,
    ConfioRewardTransaction,
    AchievementType,
    UserAchievement,
    UserReferral,
    ReferralWithdrawalLog,
    TikTokViralShare,
    ConfioGrowthMetric,
)
# Achievement models are now registered below

# Achievement models
from achievements.admin import (
    RewardProgramAdmin,
    UserRewardAdmin,
    UserReferralAdmin,
    ReferralRewardEventAdmin,
    SocialReferralShareAdmin,
    RewardWalletAdmin,
    RewardLedgerEntryAdmin,
    ReferralWithdrawalLogAdmin,
    ConfioGrowthMetricAdmin,
)
confio_admin_site.register(ConfioRewardBalance, RewardWalletAdmin)
confio_admin_site.register(ConfioRewardTransaction, RewardLedgerEntryAdmin)
confio_admin_site.register(AchievementType, RewardProgramAdmin)
confio_admin_site.register(UserAchievement, UserRewardAdmin)
confio_admin_site.register(UserReferral, UserReferralAdmin)
confio_admin_site.register(ReferralRewardEvent, ReferralRewardEventAdmin)
confio_admin_site.register(ReferralWithdrawalLog, ReferralWithdrawalLogAdmin)
confio_admin_site.register(TikTokViralShare, SocialReferralShareAdmin)
confio_admin_site.register(ConfioGrowthMetric, ConfioGrowthMetricAdmin)

# Ambassador models
from achievements.models import InfluencerAmbassador, AmbassadorActivity, PioneroBetaTracker
from achievements.admin import ReferralAmbassadorAdmin, ReferralAmbassadorActivityAdmin, PioneroBetaTrackerAdmin
confio_admin_site.register(InfluencerAmbassador, ReferralAmbassadorAdmin)
confio_admin_site.register(AmbassadorActivity, ReferralAmbassadorActivityAdmin)
confio_admin_site.register(PioneroBetaTracker, PioneroBetaTrackerAdmin)

# Unified Transaction Tables
from users.models_unified import UnifiedTransactionTable
from usdc_transactions.models_unified import UnifiedUSDCTransactionTable
from usdc_transactions.admin import UnifiedUSDCTransactionAdmin
confio_admin_site.register(UnifiedTransactionTable, UnifiedTransactionAdmin)

# Month summary ("Tu mes") spending categories
from users.models_cashflow import (
    CounterpartyRule, MovementOverride, CounterpartyPromptState, CusdPlusPriceSnapshot, CusdPlusHoldingSnapshot,
)
from users.admin_cashflow import (
    CounterpartyRuleAdmin, MovementOverrideAdmin, CounterpartyPromptStateAdmin,
    CusdPlusPriceSnapshotAdmin, CusdPlusHoldingSnapshotAdmin,
)
confio_admin_site.register(CounterpartyRule, CounterpartyRuleAdmin)
confio_admin_site.register(MovementOverride, MovementOverrideAdmin)
confio_admin_site.register(CounterpartyPromptState, CounterpartyPromptStateAdmin)
confio_admin_site.register(CusdPlusPriceSnapshot, CusdPlusPriceSnapshotAdmin)
confio_admin_site.register(CusdPlusHoldingSnapshot, CusdPlusHoldingSnapshotAdmin)
confio_admin_site.register(UnifiedUSDCTransactionTable, UnifiedUSDCTransactionAdmin)

# Analytics models
from users.models_analytics import DailyMetrics, CountryMetrics, FunnelEvent, FunnelDailyRollup
from users.admin_analytics import DailyMetricsAdmin, CountryMetricsAdmin, FunnelEventAdmin, FunnelDailyRollupAdmin
confio_admin_site.register(DailyMetrics, DailyMetricsAdmin)
confio_admin_site.register(CountryMetrics, CountryMetricsAdmin)
confio_admin_site.register(FunnelEvent, FunnelEventAdmin)
confio_admin_site.register(FunnelDailyRollup, FunnelDailyRollupAdmin)
from users.models_rail_waitlist import LocalRailWaitlistEntry
from users.admin_analytics import LocalRailWaitlistEntryAdmin
confio_admin_site.register(LocalRailWaitlistEntry, LocalRailWaitlistEntryAdmin)
from users.models_product_waitlist import ProductWaitlistEntry
from users.admin_analytics import ProductWaitlistEntryAdmin
confio_admin_site.register(ProductWaitlistEntry, ProductWaitlistEntryAdmin)

# P2P models
from p2p_exchange.models import (
    P2PPaymentMethod, P2POffer, P2PTrade, P2PMessage, 
    P2PUserStats, P2PEscrow, P2PTradeRating, P2PDispute, P2PDisputeEvidence,
    P2PDisputeTransaction, P2PFavoriteTrader, PremiumUpgradeRequest
)
confio_admin_site.register(P2PPaymentMethod, P2PPaymentMethodAdmin)
confio_admin_site.register(P2POffer, P2POfferAdmin)
confio_admin_site.register(P2PTrade, P2PTradeAdmin)
confio_admin_site.register(P2PMessage, P2PMessageAdmin)
confio_admin_site.register(P2PUserStats, P2PUserStatsAdmin)
confio_admin_site.register(P2PEscrow, P2PEscrowAdmin)
confio_admin_site.register(P2PTradeRating, P2PTradeRatingAdmin)
confio_admin_site.register(P2PDispute, P2PDisputeAdmin)
confio_admin_site.register(P2PDisputeTransaction, P2PDisputeTransactionAdmin)
confio_admin_site.register(P2PDisputeEvidence, P2PDisputeEvidenceAdmin)
confio_admin_site.register(P2PFavoriteTrader, P2PFavoriteTraderAdmin)
confio_admin_site.register(PremiumUpgradeRequest, PremiumUpgradeRequestAdmin)

# Payment models
from payments.models import Invoice, PaymentTransaction
confio_admin_site.register(Invoice, InvoiceAdmin)
confio_admin_site.register(PaymentTransaction, PaymentTransactionAdmin)

# Send models
from send.models import SendTransaction, PhoneInvite
confio_admin_site.register(SendTransaction, SendTransactionAdmin)
confio_admin_site.register(PhoneInvite, PhoneInviteAdmin)

# Conversion models
from conversion.models import Conversion
confio_admin_site.register(Conversion, ConversionAdmin)

# Exchange rate models
from exchange_rates.models import DailyRateSnapshot, ExchangeRate, RateFetchLog
from exchange_rates.admin import DailyRateSnapshotAdmin, ExchangeRateAdmin, RateFetchLogAdmin
confio_admin_site.register(ExchangeRate, ExchangeRateAdmin)
confio_admin_site.register(RateFetchLog, RateFetchLogAdmin)
confio_admin_site.register(DailyRateSnapshot, DailyRateSnapshotAdmin)

# Ramp models
from ramps.models import KoyweBankInfo, RampPaymentMethod, RampTransaction, RampUserAddress, RampWebhookEvent
from ramps.admin import KoyweBankInfoAdmin, RampPaymentMethodAdmin, RampTransactionAdmin, RampUserAddressAdmin, RampWebhookEventAdmin
confio_admin_site.register(KoyweBankInfo, KoyweBankInfoAdmin)
confio_admin_site.register(RampPaymentMethod, RampPaymentMethodAdmin)
confio_admin_site.register(RampTransaction, RampTransactionAdmin)
confio_admin_site.register(RampUserAddress, RampUserAddressAdmin)
confio_admin_site.register(RampWebhookEvent, RampWebhookEventAdmin)

# Persistent provider accounts and named/omnibus money flows
from payment_accounts.admin import (
    ThirdPartyPayinSwitchAdmin,
    PayinAdmissionAdmin,
    PaymentBridgeQuoteAdmin,
    PaymentBridgeTransferAdmin,
    EligibilityPolicyAdmin,
    FinancialAccountAdmin,
    MoneyFlowAdmin,
    MoneyOperationAdmin,
    ProviderProfileAdmin,
)
from payment_accounts.models import (
    ThirdPartyPayinSwitch,
    PayinAdmission,
    PaymentBridgeQuote,
    PaymentBridgeTransfer,
    AccountCapability,
    EligibilityDecision,
    EligibilityPolicy,
    FinancialAccount,
    FundingInstruction,
    LedgerEntry,
    MoneyFlow,
    MoneyOperation,
    PayoutDestination,
    ProviderProfile,
    ProviderWebhookEvent,
)

confio_admin_site.register(EligibilityPolicy, EligibilityPolicyAdmin)
confio_admin_site.register(ProviderProfile, ProviderProfileAdmin)
confio_admin_site.register(ThirdPartyPayinSwitch, ThirdPartyPayinSwitchAdmin)
confio_admin_site.register(PayinAdmission, PayinAdmissionAdmin)
confio_admin_site.register(FinancialAccount, FinancialAccountAdmin)
confio_admin_site.register(MoneyFlow, MoneyFlowAdmin)
confio_admin_site.register(PaymentBridgeQuote, PaymentBridgeQuoteAdmin)
confio_admin_site.register(PaymentBridgeTransfer, PaymentBridgeTransferAdmin)
confio_admin_site.register(MoneyOperation, MoneyOperationAdmin)
confio_admin_site.register(FundingInstruction)
confio_admin_site.register(AccountCapability)
confio_admin_site.register(LedgerEntry)
confio_admin_site.register(ProviderWebhookEvent)
confio_admin_site.register(EligibilityDecision)
confio_admin_site.register(PayoutDestination)

# USDC Transaction models
from usdc_transactions.models import USDCDeposit, USDCWithdrawal, GuardarianTransaction
from usdc_transactions.admin import USDCDepositAdmin, USDCWithdrawalAdmin, GuardarianTransactionAdmin
confio_admin_site.register(USDCDeposit, USDCDepositAdmin)
confio_admin_site.register(USDCWithdrawal, USDCWithdrawalAdmin)
confio_admin_site.register(GuardarianTransaction, GuardarianTransactionAdmin)

# Presale models
from presale.models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings, PresaleWaitlist, PresaleMigrationCredit
from presale.admin import PresalePhaseAdmin, PresalePurchaseAdmin, PresaleStatsAdmin, UserPresaleLimitAdmin, PresaleSettingsAdmin, PresaleWaitlistAdmin, PresaleMigrationCreditAdmin
confio_admin_site.register(PresaleSettings, PresaleSettingsAdmin)
confio_admin_site.register(PresalePhase, PresalePhaseAdmin)
confio_admin_site.register(PresalePurchase, PresalePurchaseAdmin)
confio_admin_site.register(PresaleStats, PresaleStatsAdmin)
confio_admin_site.register(UserPresaleLimit, UserPresaleLimitAdmin)
confio_admin_site.register(PresaleWaitlist, PresaleWaitlistAdmin)
confio_admin_site.register(PresaleMigrationCredit, PresaleMigrationCreditAdmin)

# Humanitarian aid models
from humanitarian.models import HumanitarianCampaign, HumanitarianDonation, HumanitarianProofLink, HumanitarianRelease, HumanitarianVolunteerApplication
from humanitarian.admin import HumanitarianCampaignAdmin, HumanitarianDonationAdmin, HumanitarianProofLinkAdmin, HumanitarianReleaseAdmin, HumanitarianVolunteerApplicationAdmin
confio_admin_site.register(HumanitarianCampaign, HumanitarianCampaignAdmin)
confio_admin_site.register(HumanitarianDonation, HumanitarianDonationAdmin)
confio_admin_site.register(HumanitarianVolunteerApplication, HumanitarianVolunteerApplicationAdmin)
confio_admin_site.register(HumanitarianRelease, HumanitarianReleaseAdmin)
confio_admin_site.register(HumanitarianProofLink, HumanitarianProofLinkAdmin)

# Notification models
from notifications.models import Notification, NotificationPreference, FCMDeviceToken
from notifications.admin import NotificationAdmin, NotificationPreferenceAdmin, FCMDeviceTokenAdmin
confio_admin_site.register(Notification, NotificationAdmin)
confio_admin_site.register(NotificationPreference, NotificationPreferenceAdmin)
confio_admin_site.register(FCMDeviceToken, FCMDeviceTokenAdmin)

# Inbox / editorial content models
confio_admin_site.register(Channel, ChannelAdmin)
confio_admin_site.register(ContentItem, ContentItemAdmin)
confio_admin_site.register(ContentSurface, ContentSurfaceAdmin)
confio_admin_site.register(ChannelMembership, ChannelMembershipAdmin)
confio_admin_site.register(ContentReadState, ContentReadStateAdmin)
confio_admin_site.register(ReactionType, ReactionTypeAdmin)
confio_admin_site.register(ContentReaction, ContentReactionAdmin)
confio_admin_site.register(CommunityPostReview, CommunityPostReviewAdmin)
confio_admin_site.register(CommunityPostReport, CommunityPostReportAdmin)
confio_admin_site.register(CommunityComment, CommunityCommentAdmin)
confio_admin_site.register(CommunityCommentReport, CommunityCommentReportAdmin)
confio_admin_site.register(CommunityCommentReaction, CommunityCommentReactionAdmin)
confio_admin_site.register(ProfilePictureSubmission, ProfilePictureSubmissionAdmin)
confio_admin_site.register(PublicObject, PublicObjectAdmin)
confio_admin_site.register(CommunityBlock, CommunityBlockAdmin)
confio_admin_site.register(CommunityFollow, CommunityFollowAdmin)
confio_admin_site.register(CommunityActivityShare, CommunityActivityShareAdmin)
confio_admin_site.register(CommunityProfileSettings, CommunityProfileSettingsAdmin)
confio_admin_site.register(ActivityShareIntent, ActivityShareIntentAdmin)
confio_admin_site.register(ActivityShareImpression, ActivityShareImpressionAdmin)
confio_admin_site.register(CommunityRulesAcceptance, CommunityRulesAcceptanceAdmin)
confio_admin_site.register(ContentPlatformClick, ContentPlatformClickAdmin)
confio_admin_site.register(ContentPlatformClickDailyStat, ContentPlatformClickDailyStatAdmin)
confio_admin_site.register(SupportConversation, SupportConversationAdmin)
confio_admin_site.register(SupportMessage, SupportMessageAdmin)
confio_admin_site.register(SupportConversationState, SupportConversationStateAdmin)

# Blockchain models (events and processing logs removed); add indexer cursor + processed markers
from blockchain.models import Balance, ProcessedIndexerTransaction, IndexerAssetCursor
from blockchain.admin import BalanceAdmin, ProcessedIndexerTransactionAdmin, IndexerAssetCursorAdmin, StockHoldingsAdmin
from blockchain.models import StockHoldings
confio_admin_site.register(Balance, BalanceAdmin)
confio_admin_site.register(StockHoldings, StockHoldingsAdmin)
from blockchain.admin import StockRiskAcknowledgementAdmin
from blockchain.models import StockRiskAcknowledgement
confio_admin_site.register(StockRiskAcknowledgement, StockRiskAcknowledgementAdmin)
confio_admin_site.register(ProcessedIndexerTransaction, ProcessedIndexerTransactionAdmin)
confio_admin_site.register(IndexerAssetCursor, IndexerAssetCursorAdmin)

# SMS Verification
from sms_verification.models import SMSVerification
from sms_verification.admin import SMSVerificationAdmin
confio_admin_site.register(SMSVerification, SMSVerificationAdmin)

# Telegram Verification
from telegram_verification.models import TelegramVerification
from telegram_verification.admin import TelegramVerificationAdmin
confio_admin_site.register(TelegramVerification, TelegramVerificationAdmin)

# Internal content ingestion
from content_ingestion.models import AIContextDocument, MediaAsset, TelegramChat
from content_ingestion.admin import AIContextDocumentAdmin, MediaAssetAdmin, TelegramChatAdmin
confio_admin_site.register(TelegramChat, TelegramChatAdmin)
confio_admin_site.register(MediaAsset, MediaAssetAdmin)
confio_admin_site.register(AIContextDocument, AIContextDocumentAdmin)

# Financieras directory
from financieras.models import Financiera, FinancieraReview, FinancieraReport
from financieras.admin import FinancieraAdmin, FinancieraReviewAdmin, FinancieraReportAdmin
confio_admin_site.register(Financiera, FinancieraAdmin)
confio_admin_site.register(FinancieraReview, FinancieraReviewAdmin)
confio_admin_site.register(FinancieraReport, FinancieraReportAdmin)

# EVM sponsorship ledger + cross-rail auto-swap queue. PendingAutoSwap was
# never registered, which left the BSC 'BNB' rows — the authoritative
# allowlist for outbound native BNB — with no admin surface at all.
from blockchain.models import CryptoSwapTrade, OndoStockTrade, PendingAutoSwap, SponsoredBatch
from blockchain.admin import (
    CryptoSwapTradeAdmin, OndoStockTradeAdmin, PendingAutoSwapAdmin, SponsoredBatchAdmin,
)
confio_admin_site.register(SponsoredBatch, SponsoredBatchAdmin)
confio_admin_site.register(OndoStockTrade, OndoStockTradeAdmin)
confio_admin_site.register(CryptoSwapTrade, CryptoSwapTradeAdmin)
confio_admin_site.register(PendingAutoSwap, PendingAutoSwapAdmin)

# Institutional collections pilot. Financial rows are read-only; operators
# can inspect each milestone and explicitly retry institution application.
from billing.admin import (
    BillingObligationAdmin,
    BillingPaymentAdmin,
    BillingScheduleAdmin,
    CipSandboxApplicationReceiptAdmin,
    CipSandboxMemberAdmin,
    InstitutionApplicationAdmin,
    InstitutionConnectionAdmin,
    ObligationSubjectAdmin,
    PaymentEffectAdmin, PaymentAllocationEntryAdmin, SettlementLegAdmin,
)
from billing.models import (
    BillingObligation,
    BillingPayment,
    BillingSchedule,
    CipSandboxApplicationReceipt,
    CipSandboxMember,
    InstitutionApplication,
    InstitutionConnection,
    ObligationSubject,
    PaymentEffect, PaymentAllocationEntry, SettlementLeg,
)

confio_admin_site.register(ObligationSubject, ObligationSubjectAdmin)
confio_admin_site.register(PaymentEffect, PaymentEffectAdmin)
confio_admin_site.register(PaymentAllocationEntry, PaymentAllocationEntryAdmin)
confio_admin_site.register(SettlementLeg, SettlementLegAdmin)
confio_admin_site.register(BillingSchedule, BillingScheduleAdmin)
confio_admin_site.register(BillingObligation, BillingObligationAdmin)
confio_admin_site.register(BillingPayment, BillingPaymentAdmin)
confio_admin_site.register(InstitutionConnection, InstitutionConnectionAdmin)
confio_admin_site.register(InstitutionApplication, InstitutionApplicationAdmin)
confio_admin_site.register(CipSandboxMember, CipSandboxMemberAdmin)
confio_admin_site.register(
    CipSandboxApplicationReceipt, CipSandboxApplicationReceiptAdmin)

from payment_accounts.models import InfiniaJourney
from payment_accounts.admin import InfiniaJourneyAdmin
confio_admin_site.register(InfiniaJourney, InfiniaJourneyAdmin)

from payment_accounts.models import AutomaticPayin
from payment_accounts.admin import AutomaticPayinAdmin
confio_admin_site.register(AutomaticPayin, AutomaticPayinAdmin)

from payment_accounts.models import CobreJourney
from payment_accounts.admin import CobreJourneyAdmin
confio_admin_site.register(CobreJourney, CobreJourneyAdmin)

from payment_accounts.models import LimitIncreaseRequest
from payment_accounts.admin import LimitIncreaseRequestAdmin
confio_admin_site.register(LimitIncreaseRequest, LimitIncreaseRequestAdmin)

from payment_accounts.models import AccountActivation
from payment_accounts.admin import AccountActivationAdmin
confio_admin_site.register(AccountActivation, AccountActivationAdmin)

from payment_accounts.models import BrebLocationCheck
from payment_accounts.admin import BrebLocationCheckAdmin
confio_admin_site.register(BrebLocationCheck, BrebLocationCheckAdmin)

from assistant.models import AssistantProfile, AssistantThreadState, AssistantTurn
from assistant.admin import AssistantProfileAdmin, AssistantThreadStateAdmin, AssistantTurnAdmin
confio_admin_site.register(AssistantTurn, AssistantTurnAdmin)
confio_admin_site.register(AssistantThreadState, AssistantThreadStateAdmin)
confio_admin_site.register(AssistantProfile, AssistantProfileAdmin)
from assistant.models import ProbeAnswer
from assistant.admin import ProbeAnswerAdmin
confio_admin_site.register(ProbeAnswer, ProbeAnswerAdmin)
from assistant.models import AssistantNeed
from assistant.admin import AssistantNeedAdmin
confio_admin_site.register(AssistantNeed, AssistantNeedAdmin)


# Wallet recovery diagnostics: what a device saw when sign-in recovery failed.
# Read-only on purpose. These rows are evidence, not something to edit.
from users.models import WalletRecoveryDiagnostic


class WalletRecoveryDiagnosticAdmin(admin.ModelAdmin):
    list_display = (
        'created_at', 'user', 'code', 'found_any', 'found_decryptable',
        'candidate_count',
    )
    list_filter = ('code', 'found_any', 'found_decryptable')
    search_fields = ('user__email', 'user__username')
    ordering = ('-created_at',)
    readonly_fields = tuple(f.name for f in WalletRecoveryDiagnostic._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


confio_admin_site.register(WalletRecoveryDiagnostic, WalletRecoveryDiagnosticAdmin)
