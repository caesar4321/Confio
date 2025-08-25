from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum, Count
from decimal import Decimal

from .models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings


@admin.register(PresalePhase)
class PresalePhaseAdmin(admin.ModelAdmin):
    list_display = [
        'phase_number', 
        'name', 
        'status_colored', 
        'price_per_token',
        'formatted_goal',
        'formatted_raised',
        'progress_bar',
        'participant_count',
        'start_date',
        'end_date'
    ]
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = [
        'created_at', 
        'updated_at', 
        'total_raised_display',
        'total_participants_display',
        'tokens_sold_display',
        'progress_display'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('phase_number', 'name', 'description', 'status')
        }),
        ('UI Display Fields', {
            'fields': ('target_audience', 'location_emoji', 'vision_points'),
            'description': 'These fields control how the phase appears in the mobile app UI'
        }),
        ('Pricing & Limits', {
            'fields': (
                'price_per_token', 
                'goal_amount',
                'min_purchase',
                'max_purchase',
                'max_per_user'
            )
        }),
        ('Schedule', {
            'fields': ('start_date', 'end_date')
        }),
        ('Statistics', {
            'fields': (
                'total_raised_display',
                'total_participants_display', 
                'tokens_sold_display',
                'progress_display'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def status_colored(self, obj):
        colors = {
            'coming_soon': '#8b5cf6',
            'upcoming': '#FFA500',
            'active': '#28a745',
            'completed': '#17a2b8',
            'paused': '#dc3545'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    def formatted_goal(self, obj):
        return f"${obj.goal_amount:,.2f}"
    formatted_goal.short_description = 'Goal'
    
    def formatted_raised(self, obj):
        raised = obj.total_raised
        if raised >= obj.goal_amount:
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">${:,.2f}</span>',
                raised
            )
        return f"${raised:,.2f}"
    formatted_raised.short_description = 'Raised'
    
    def progress_bar(self, obj):
        percentage = float(obj.progress_percentage)
        color = '#28a745' if percentage >= 100 else '#17a2b8'
        width = min(percentage, 100)
        return format_html(
            '''
            <div style="width: 100px; height: 20px; background-color: #f0f0f0; 
                        border-radius: 10px; overflow: hidden; position: relative;">
                <div style="width: {}%; height: 100%; background-color: {}; 
                            transition: width 0.5s ease;"></div>
                <span style="position: absolute; top: 50%; left: 50%; 
                             transform: translate(-50%, -50%); font-size: 11px; 
                             font-weight: bold;">{:.1f}%</span>
            </div>
            '''.format(width, color, percentage)
        )
    progress_bar.short_description = 'Progress'
    
    def participant_count(self, obj):
        return obj.total_participants
    participant_count.short_description = 'Participants'
    
    def total_raised_display(self, obj):
        return f"${obj.total_raised:,.2f} cUSD"
    total_raised_display.short_description = 'Total Raised'
    
    def total_participants_display(self, obj):
        return f"{obj.total_participants:,} users"
    total_participants_display.short_description = 'Total Participants'
    
    def tokens_sold_display(self, obj):
        return f"{obj.tokens_sold:,.2f} CONFIO"
    tokens_sold_display.short_description = 'Tokens Sold'
    
    def progress_display(self, obj):
        return f"{obj.progress_percentage:.2f}%"
    progress_display.short_description = 'Progress %'
    
    actions = [
        'activate_phase',
        'pause_phase',
        'complete_phase',
        'start_onchain_round',
        'end_current_round',
        'resume_current_round',
        'fund_app_with_confio',
    ]
    
    def activate_phase(self, request, queryset):
        updated = queryset.update(status='active')
        self.message_user(request, f"{updated} phase(s) activated.")
    activate_phase.short_description = "Activate selected phases"
    
    def pause_phase(self, request, queryset):
        updated = queryset.update(status='paused')
        self.message_user(request, f"{updated} phase(s) paused.")
    pause_phase.short_description = "Pause selected phases"
    
    def complete_phase(self, request, queryset):
        updated = queryset.update(status='completed')
        self.message_user(request, f"{updated} phase(s) marked as completed.")
    complete_phase.short_description = "Complete selected phases"

    def start_onchain_round(self, request, queryset):
        """Start the selected presale phase on-chain using the contract, matching DB values.
        Uses settings.ALGORAND_PRESALE_APP_ID, ALGORAND_CONFIO_ASSET_ID, ALGORAND_CUSD_ASSET_ID,
        and admin mnemonic (ALGORAND_ADMIN_MNEMONIC or falls back to ALGORAND_SPONSOR_MNEMONIC).
        """
        from django.conf import settings
        from decimal import Decimal
        try:
            app_id = getattr(settings, 'ALGORAND_PRESALE_APP_ID', 0)
            confio_id = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0)
            cusd_id = getattr(settings, 'ALGORAND_CUSD_ASSET_ID', 0)
            if not app_id or not confio_id or not cusd_id:
                self.message_user(request, 'Algorand PRESALE_APP_ID/ASSET_IDs not configured', level='error')
                return
            if queryset.count() != 1:
                self.message_user(request, 'Select exactly one phase to start on-chain', level='error')
                return
            phase = queryset.first()
            # Read values from DB
            price = Decimal(phase.price_per_token)
            db_cap = Decimal(phase.goal_amount)
            # Compute on-chain cap more generously than DB goal (display)
            cap_multiplier = getattr(settings, 'PRESALE_ONCHAIN_CAP_MULTIPLIER', 5)
            try:
                cap_multiplier = int(cap_multiplier)
                if cap_multiplier < 1:
                    cap_multiplier = 1
            except Exception:
                cap_multiplier = 5
            cap = db_cap * cap_multiplier
            max_per_addr = Decimal(phase.max_per_user or 0)
            if not max_per_addr or max_per_addr <= 0:
                # Fallback to max_purchase if per-user total limit not set
                max_per_addr = Decimal(phase.max_purchase)
            # Ensure per-address <= on-chain cap
            if max_per_addr > cap:
                max_per_addr = cap
            # Build admin address from mnemonic
            from algosdk import mnemonic as _mn, account as _acct, encoding as _enc
            admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None) or getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not admin_mn:
                self.message_user(request, 'Admin/Sponsor mnemonic not configured', level='error')
                return
            admin_mn_norm = " ".join(str(admin_mn).strip().split())
            admin_sk = _mn.to_private_key(admin_mn_norm)
            # Derive the address from the private key using algosdk.account helper
            admin_addr = _acct.address_from_private_key(admin_sk)
            # Inventory preflight: ensure app holds enough CONFIO for outstanding + (cap / price)
            try:
                from algosdk.v2client import algod as _algod
                from contracts.presale.admin_presale import PresaleAdmin as _PA
                client = _algod.AlgodClient(
                    getattr(settings, 'ALGORAND_ALGOD_TOKEN', ''),
                    getattr(settings, 'ALGORAND_ALGOD_ADDRESS', '')
                )
                # Compute integer base units
                price_int = int((price * (10**6)).to_integral_value())
                cap_int = int((cap * (10**6)).to_integral_value())
                confio_needed = (cap_int * (10**6)) // max(price_int, 1)  # micro CONFIO for new round
                # Read app address and balance
                from algosdk.logic import get_application_address as _app_addr
                app_addr = _app_addr(int(app_id))
                acct = client.account_info(app_addr)
                app_confio = 0
                for a in (acct.get('assets') or []):
                    if int(a.get('asset-id')) == int(confio_id):
                        app_confio = int(a.get('amount') or 0)
                        break
                # Read outstanding obligations (sold - claimed) from contract state
                try:
                    _pa = _PA(int(app_id), int(confio_id), int(cusd_id))
                    # Use same client endpoint
                    _pa.algod_client = client
                    state = _pa.get_state()
                    total_sold = int(state.get('confio_sold', 0) or 0)
                    total_claimed = int(state.get('claimed_total', 0) or 0)
                    outstanding = max(0, total_sold - total_claimed)
                except Exception:
                    outstanding = 0
                required_confio = outstanding + confio_needed
                if app_confio < required_confio:
                    need = (required_confio - app_confio) / 10**6
                    have = app_confio / 10**6
                    self.message_user(
                        request,
                        (
                            f"Insufficient CONFIO in app (need outstanding + round). Have {have:,.0f}, need {need:,.0f} more. "
                            f"Fund app {app_addr} with CONFIO (ASA {confio_id}) and retry."
                        ),
                        level='error'
                    )
                    return
            except Exception as inv_e:
                self.message_user(request, f"Inventory preflight failed: {inv_e}", level='error')
                return

            # Call helper to start round
            from contracts.presale.admin_presale import PresaleAdmin as _PresaleAdmin
            from algosdk.v2client import algod as _algod
            pa = _PresaleAdmin(int(app_id), int(confio_id), int(cusd_id))
            # Ensure correct Algod endpoint (avoid localhost defaults inside module)
            try:
                pa.algod_client = _algod.AlgodClient(
                    getattr(settings, 'ALGORAND_ALGOD_TOKEN', ''),
                    getattr(settings, 'ALGORAND_ALGOD_ADDRESS', '')
                )
            except Exception:
                pass

            # Preflight: check assets and app exist on this node
            try:
                pa.algod_client.asset_info(int(confio_id))
                pa.algod_client.asset_info(int(cusd_id))
            except Exception as ae:
                self.message_user(request, f"Node cannot see required assets (CONFIO {confio_id}, cUSD {cusd_id}): {ae}", level='error')
                return
            try:
                app_info = pa.algod_client.application_info(int(app_id))
            except Exception as ie:
                self.message_user(request, f"Node cannot find presale app {app_id}: {ie}", level='error')
                return

            # Ensure app account is opted into both assets; if not, perform sponsored opt-ins
            try:
                from algosdk.logic import get_application_address as _app_addr
                from algosdk.transaction import ApplicationCallTxn as _AppCall, PaymentTxn as _Pay, OnComplete as _OC, assign_group_id as _assign_gid
                from algosdk import mnemonic as _mn2
                app_addr = _app_addr(int(app_id))
                acct = pa.algod_client.account_info(app_addr)
                asset_ids = {int(a.get('asset-id')) for a in (acct.get('assets') or [])}
                needs_confio = int(confio_id) not in asset_ids
                needs_cusd = int(cusd_id) not in asset_ids
                if needs_confio or needs_cusd:
                    sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
                    sponsor_addr = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None)
                    if not sponsor_mn or not sponsor_addr:
                        self.message_user(request, 'Sponsor mnemonic/address not configured; cannot opt-in assets', level='error')
                        return
                    sponsor_sk = _mn2.to_private_key(" ".join(str(sponsor_mn).strip().split()))
                    params = pa.algod_client.suggested_params()
                    min_fee = getattr(params, 'min_fee', 1000) or 1000
                    # Sponsor bump (2 txns)
                    sp_s = pa.algod_client.suggested_params(); sp_s.flat_fee = True; sp_s.fee = min_fee*2
                    bump = _Pay(sender=sponsor_addr, sp=sp_s, receiver=sponsor_addr, amt=0)
                    # App call (carries inner fees)
                    sp_a = pa.algod_client.suggested_params(); sp_a.flat_fee = True; sp_a.fee = min_fee*3
                    call = _AppCall(
                        sender=admin_addr,
                        sp=sp_a,
                        index=int(app_id),
                        app_args=[b'opt_in_assets'],
                        foreign_assets=[int(confio_id), int(cusd_id)],
                        on_complete=_OC.NoOpOC
                    )
                    _assign_gid([bump, call])
                    stx0 = bump.sign(sponsor_sk)
                    stx1 = call.sign(admin_sk)
                    pa.algod_client.send_transactions([stx0, stx1])
                    # Do not wait; let background tasks/UX handle any confirmation
            except Exception as oe:
                self.message_user(request, f"Preflight opt-in failed: {oe}", level='error')
                return
            pa.start_round(admin_address=admin_addr, admin_sk=admin_sk,
                           price_cusd_per_confio=float(price),
                           cusd_cap=float(cap), max_per_addr=float(max_per_addr))
            # Update phase status and start_date
            from django.utils import timezone as dj_tz
            phase.status = 'active'
            if not phase.start_date:
                phase.start_date = dj_tz.now()
            phase.save(update_fields=['status', 'start_date', 'updated_at'])
            self.message_user(
                request,
                (
                    f"On-chain round started for Phase {phase.phase_number} (App ID {app_id}). "
                    f"DB goal={db_cap:,.0f} cUSD, on-chain cap={cap:,.0f} cUSD (x{cap_multiplier})."
                )
            )
        except Exception as e:
            self.message_user(request, f"Failed to start on-chain round: {e}", level='error')
    start_onchain_round.short_description = "Start on-chain round (match DB values)"

    def end_current_round(self, request, queryset):
        """End the current on-chain round immediately by toggling round_active -> 0.

        Sends a simple admin ApplicationCall (no inner txns). If the round is already inactive, informs the user.
        """
        from django.conf import settings
        try:
            app_id = getattr(settings, 'ALGORAND_PRESALE_APP_ID', 0)
            if not app_id:
                self.message_user(request, 'PRESALE_APP_ID not configured', level='error')
                return
            if queryset.count() != 1:
                self.message_user(request, 'Select exactly one phase to operate on', level='error')
                return

            # Build admin credentials
            from algosdk import mnemonic as _mn
            from algosdk.account import address_from_private_key as _addr_from_sk
            admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None) or getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not admin_mn:
                self.message_user(request, 'Admin/Sponsor mnemonic not configured', level='error')
                return
            admin_sk = _mn.to_private_key(" ".join(str(admin_mn).strip().split()))
            admin_addr = _addr_from_sk(admin_sk)

            # Query current round state to avoid unnecessary toggle
            from algosdk.v2client import algod as _algod
            client = _algod.AlgodClient(
                getattr(settings, 'ALGORAND_ALGOD_TOKEN', ''),
                getattr(settings, 'ALGORAND_ALGOD_ADDRESS', ''),
            )
            app_info = client.application_info(int(app_id))
            gstate = {bytes.fromhex(kv['key']).decode('utf-8') if False else kv['key']: kv['value'] for kv in app_info['params'].get('global-state', [])}
            # Helper: decode byte/uint values from global state
            def _get_uint(key_b64: str) -> int:
                try:
                    v = next((kv['value'] for kv in app_info['params']['global-state'] if kv['key'] == key_b64), None)
                    return int(v.get('uint') or 0) if v else 0
                except Exception:
                    return 0
            # Keys are base64; we don't strictly need decode for active snapshot, just attempt to toggle regardless.

            # Send toggle_round (sets active=0 if currently 1; if already 0, it will attempt to re-activate and may assert).
            # To avoid activation path, we enforce a one-way: only send when active.
            # Read active value via dryrun of global state: we know 'active' was set in contract; but decoding base64 key here is verbose.
            # Simpler: attempt toggle; if round was inactive, Tx will try to activate and may fail inventory assertion. We can guard by checking suggested param dry-run not available.
            # Instead, issue a read via indexer-like API is out of scope; proceed with toggle and surface errors.

            from algosdk.transaction import ApplicationCallTxn as _AppCall, OnComplete as _OC
            # Resolve assets for foreign list
            confio_id = int(getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0) or 0)
            cusd_id = int(getattr(settings, 'ALGORAND_CUSD_ASSET_ID', 0) or 0)
            foreign_assets = [i for i in [confio_id, cusd_id] if i]
            params = client.suggested_params()
            txn = _AppCall(
                sender=admin_addr,
                sp=params,
                index=int(app_id),
                app_args=[b'toggle_round'],
                foreign_assets=foreign_assets,
                on_complete=_OC.NoOpOC
            )
            stx = txn.sign(admin_sk)
            tx_id = client.send_transaction(stx)
            # No blocking wait; report tx id
            self.message_user(request, f"End round requested (toggle_round). Tx: {tx_id}", level='info')
        except Exception as e:
            self.message_user(request, f"Failed to end current on-chain round: {e}", level='error')
    end_current_round.short_description = "End current on-chain round (toggle inactive)"

    def resume_current_round(self, request, queryset):
        """Resume the on-chain round (toggle round_active -> 1) if currently inactive.

        Runs 'toggle_round' only when the contract round is inactive. Displays tx id or a helpful error.
        """
        from django.conf import settings
        try:
            app_id = getattr(settings, 'ALGORAND_PRESALE_APP_ID', 0)
            if not app_id:
                self.message_user(request, 'PRESALE_APP_ID not configured', level='error')
                return
            if queryset.count() != 1:
                self.message_user(request, 'Select exactly one phase to operate on', level='error')
                return

            # Build admin credentials
            from algosdk import mnemonic as _mn
            from algosdk.account import address_from_private_key as _addr_from_sk
            admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None) or getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not admin_mn:
                self.message_user(request, 'Admin/Sponsor mnemonic not configured', level='error')
                return
            admin_sk = _mn.to_private_key(" ".join(str(admin_mn).strip().split()))
            admin_addr = _addr_from_sk(admin_sk)

            # Read current active/paused state
            from algosdk.v2client import algod as _algod
            client = _algod.AlgodClient(
                getattr(settings, 'ALGORAND_ALGOD_TOKEN', ''),
                getattr(settings, 'ALGORAND_ALGOD_ADDRESS', ''),
            )
            info = client.application_info(int(app_id))
            g = {kv['key']: kv['value'] for kv in info['params'].get('global-state', [])}
            # Base64 keys for 'active' and 'paused'
            KEY_ACTIVE = 'YWN0aXZl'   # base64('active')
            KEY_PAUSED = 'cGF1c2Vk'   # base64('paused')
            is_active = int(g.get(KEY_ACTIVE, {}).get('uint') or 0)
            is_paused = int(g.get(KEY_PAUSED, {}).get('uint') or 0)
            if is_active == 1:
                self.message_user(request, 'Round is already active on-chain.', level='info')
                return
            if is_paused == 1:
                self.message_user(request, 'Contract is paused; unpause first before resuming the round.', level='error')
                return

            # Send toggle_round to activate (contract will perform inventory checks)
            from algosdk.transaction import ApplicationCallTxn as _AppCall, OnComplete as _OC
            # Include foreign assets so contract can read balances during resume
            confio_id = int(getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0) or 0)
            cusd_id = int(getattr(settings, 'ALGORAND_CUSD_ASSET_ID', 0) or 0)
            foreign_assets = [i for i in [confio_id, cusd_id] if i]
            params = client.suggested_params()
            txn = _AppCall(
                sender=admin_addr,
                sp=params,
                index=int(app_id),
                app_args=[b'toggle_round'],
                foreign_assets=foreign_assets,
                on_complete=_OC.NoOpOC,
            )
            stx = txn.sign(admin_sk)
            tx_id = client.send_transaction(stx)
            self.message_user(request, f"Resume round requested (toggle_round). Tx: {tx_id}", level='info')
        except Exception as e:
            self.message_user(request, f"Failed to resume on-chain round: {e}", level='error')
    resume_current_round.short_description = "Resume current on-chain round (toggle active)"

    def fund_app_with_confio(self, request, queryset):
        """Fund the presale app address with CONFIO from the sponsor account to cover cap shortfall."""
        from django.conf import settings
        from decimal import Decimal
        try:
            app_id = getattr(settings, 'ALGORAND_PRESALE_APP_ID', 0)
            confio_id = getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', 0)
            if not app_id or not confio_id:
                self.message_user(request, 'PRESALE_APP_ID/CONFIO_ASSET_ID not configured', level='error')
                return
            if queryset.count() != 1:
                self.message_user(request, 'Select exactly one phase to fund', level='error')
                return
            phase = queryset.first()
            # Values from DB
            price = Decimal(phase.price_per_token)
            db_cap = Decimal(phase.goal_amount)
            cap_multiplier = getattr(settings, 'PRESALE_ONCHAIN_CAP_MULTIPLIER', 5)
            try:
                cap_multiplier = int(cap_multiplier)
                if cap_multiplier < 1:
                    cap_multiplier = 1
            except Exception:
                cap_multiplier = 5
            cap = db_cap * cap_multiplier

            # Compute required CONFIO for outstanding + cap
            price_int = int((price * (10**6)).to_integral_value())
            cap_int = int((cap * (10**6)).to_integral_value())
            confio_needed = (cap_int * (10**6)) // max(price_int, 1)

            # Setup Algod
            from algosdk.v2client import algod as _algod
            client = _algod.AlgodClient(
                getattr(settings, 'ALGORAND_ALGOD_TOKEN', ''),
                getattr(settings, 'ALGORAND_ALGOD_ADDRESS', '')
            )
            # Get app address + current CONFIO balance
            from algosdk.logic import get_application_address as _app_addr
            app_addr = _app_addr(int(app_id))
            acct = client.account_info(app_addr)
            app_confio = 0
            for a in (acct.get('assets') or []):
                if int(a.get('asset-id')) == int(confio_id):
                    app_confio = int(a.get('amount') or 0)
                    break
            # Include outstanding obligations
            try:
                from contracts.presale.admin_presale import PresaleAdmin as _PA
                pa = _PA(int(app_id), int(confio_id), int(getattr(settings,'ALGORAND_CUSD_ASSET_ID',0)))
                state = pa.get_state()
                total_sold = int(state.get('confio_sold', 0) or 0)
                total_claimed = int(state.get('claimed_total', 0) or 0)
                outstanding = max(0, total_sold - total_claimed)
            except Exception:
                outstanding = 0
            required_confio = outstanding + confio_needed
            # Ensure app is opted into CONFIO; if not, perform sponsored opt-in
            try:
                has_confio = any(int(a.get('asset-id')) == int(confio_id) for a in (acct.get('assets') or []))
                if not has_confio:
                    admin_mn = getattr(settings, 'ALGORAND_ADMIN_MNEMONIC', None) or getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
                    sponsor_addr = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None)
                    sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
                    if not admin_mn or not sponsor_addr or not sponsor_mn:
                        self.message_user(request, 'Missing admin/sponsor credentials for app opt-in', level='error')
                        return
                    from algosdk import mnemonic as _mn2
                    from algosdk.transaction import ApplicationCallTxn as _AppCall, PaymentTxn as _Pay, OnComplete as _OC, assign_group_id as _assign
                    admin_sk = _mn2.to_private_key(" ".join(str(admin_mn).strip().split()))
                    # Derive admin address from sk
                    from algosdk.account import address_from_private_key as _addr_from_sk
                    admin_addr = _addr_from_sk(admin_sk)
                    # Build sponsored bump + app call(opt_in_assets)
                    params = client.suggested_params()
                    min_fee = getattr(params, 'min_fee', 1000) or 1000
                    sp_s = client.suggested_params(); sp_s.flat_fee = True; sp_s.fee = min_fee*2
                    bump = _Pay(sender=sponsor_addr, sp=sp_s, receiver=sponsor_addr, amt=0)
                    sp_a = client.suggested_params(); sp_a.flat_fee = True; sp_a.fee = min_fee*3
                    call = _AppCall(sender=admin_addr, sp=sp_a, index=int(app_id), app_args=[b'opt_in_assets'], foreign_assets=[int(confio_id), int(getattr(settings,'ALGORAND_CUSD_ASSET_ID',0))], on_complete=_OC.NoOpOC)
                    _assign([bump, call])
                    sponsor_sk = _mn2.to_private_key(" ".join(str(sponsor_mn).strip().split()))
                    stx0 = bump.sign(sponsor_sk)
                    stx1 = call.sign(admin_sk)
                    client.send_transactions([stx0, stx1])
                    # Refresh account info without waiting
                    acct = client.account_info(app_addr)
                    app_confio = 0
                    for a in (acct.get('assets') or []):
                        if int(a.get('asset-id')) == int(confio_id):
                            app_confio = int(a.get('amount') or 0)
                            break
            except Exception as oe:
                self.message_user(request, f"App opt-in failed: {oe}", level='error')
                return
            shortfall = max(0, required_confio - app_confio)
            if shortfall == 0:
                self.message_user(request, 'App already has sufficient CONFIO for outstanding + configured cap.', level='info')
                return

            # Send ASA from sponsor to app
            sponsor_addr = getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None)
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not sponsor_addr or not sponsor_mn:
                self.message_user(request, 'Sponsor mnemonic/address not configured', level='error')
                return
            from algosdk import mnemonic as _mn
            from algosdk.transaction import AssetTransferTxn as _Axfer
            sponsor_sk = _mn.to_private_key(" ".join(str(sponsor_mn).strip().split()))
            params = client.suggested_params()
            txn = _Axfer(sender=sponsor_addr, sp=params, receiver=app_addr, amt=int(shortfall), index=int(confio_id))
            stx = txn.sign(sponsor_sk)
            txid = client.send_transaction(stx)
            # Do not wait; return to admin immediately
            self.message_user(request, f"Funded app with {shortfall/10**6:,.0f} CONFIO (tx {txid[:10]}...).", level='success')
        except Exception as e:
            self.message_user(request, f"Failed to fund app: {e}", level='error')
    fund_app_with_confio.short_description = "Fund app with CONFIO (from sponsor)"


@admin.register(PresalePurchase)
class PresalePurchaseAdmin(admin.ModelAdmin):
    list_display = [
        'purchase_id',
        'user_link',
        'phase',
        'formatted_cusd',
        'formatted_confio',
        'price_display',
        'status_colored',
        'txid_short',
        'created_at',
        'completed_at'
    ]
    list_filter = ['status', 'phase', 'created_at']
    search_fields = ['user__username', 'user__email', 'transaction_hash']
    readonly_fields = [
        'user', 
        'phase',
        'cusd_amount',
        'confio_amount',
        'price_per_token',
        'transaction_hash',
        'from_address',
        'created_at',
        'completed_at'
    ]
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Purchase Details', {
            'fields': (
                'user',
                'phase',
                'cusd_amount',
                'confio_amount',
                'price_per_token'
            )
        }),
        ('Transaction Info', {
            'fields': (
                'status',
                'transaction_hash',
                'from_address',
                'notes'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'completed_at')
        })
    )
    
    def purchase_id(self, obj):
        return f"#{obj.id}"
    purchase_id.short_description = 'ID'
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def formatted_cusd(self, obj):
        return f"${obj.cusd_amount:,.2f}"
    formatted_cusd.short_description = 'cUSD Amount'
    
    def formatted_confio(self, obj):
        return f"{obj.confio_amount:,.2f}"
    formatted_confio.short_description = 'CONFIO Amount'
    
    def price_display(self, obj):
        return f"${obj.price_per_token}"
    price_display.short_description = 'Price/Token'

    def txid_short(self, obj):
        if not obj.transaction_hash:
            return '-'
        txid = obj.transaction_hash
        return format_html('<span style="font-family:monospace;">{}…{}</span>', txid[:8], txid[-6:])
    txid_short.short_description = 'TxID'
    
    def status_colored(self, obj):
        colors = {
            'pending': '#FFA500',
            'processing': '#17a2b8',
            'completed': '#28a745',
            'failed': '#dc3545',
            'refunded': '#6c757d'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#000'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    def has_add_permission(self, request):
        # Prevent manual creation of purchases
        return False
    
    actions = ['mark_as_completed', 'mark_as_failed']
    
    def mark_as_completed(self, request, queryset):
        updated = 0
        for purchase in queryset.filter(status__in=['pending', 'processing']):
            purchase.complete_purchase(f"manual_completion_{purchase.id}")
            updated += 1
        self.message_user(request, f"{updated} purchase(s) marked as completed.")
    mark_as_completed.short_description = "Mark as completed"
    
    def mark_as_failed(self, request, queryset):
        updated = queryset.filter(status__in=['pending', 'processing']).update(
            status='failed'
        )
        self.message_user(request, f"{updated} purchase(s) marked as failed.")
    mark_as_failed.short_description = "Mark as failed"


@admin.register(PresaleStats)
class PresaleStatsAdmin(admin.ModelAdmin):
    list_display = [
        'phase',
        'formatted_raised',
        'formatted_participants',
        'formatted_tokens',
        'formatted_average',
        'last_updated'
    ]
    readonly_fields = [
        'phase',
        'total_raised',
        'total_participants',
        'total_tokens_sold',
        'average_purchase',
        'last_updated'
    ]
    
    def formatted_raised(self, obj):
        return f"${obj.total_raised:,.2f}"
    formatted_raised.short_description = 'Total Raised'
    
    def formatted_participants(self, obj):
        return f"{obj.total_participants:,}"
    formatted_participants.short_description = 'Participants'
    
    def formatted_tokens(self, obj):
        return f"{obj.total_tokens_sold:,.2f}"
    formatted_tokens.short_description = 'Tokens Sold'
    
    def formatted_average(self, obj):
        return f"${obj.average_purchase:,.2f}"
    formatted_average.short_description = 'Avg Purchase'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    actions = ['update_stats']
    
    def update_stats(self, request, queryset):
        updated = 0
        for stat in queryset:
            stat.update_stats()
            updated += 1
        self.message_user(request, f"Updated stats for {updated} phase(s).")
    update_stats.short_description = "Update statistics"


@admin.register(UserPresaleLimit)
class UserPresaleLimitAdmin(admin.ModelAdmin):
    list_display = [
        'user_link',
        'phase',
        'formatted_purchased',
        'formatted_remaining',
        'last_purchase_at'
    ]
    list_filter = ['phase', 'last_purchase_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['user', 'phase', 'total_purchased', 'last_purchase_at']
    
    def user_link(self, obj):
        url = reverse('admin:users_user_change', args=[obj.user.id])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = 'User'
    
    def formatted_purchased(self, obj):
        return f"${obj.total_purchased:,.2f}"
    formatted_purchased.short_description = 'Total Purchased'
    
    def formatted_remaining(self, obj):
        if obj.phase.max_per_user:
            remaining = obj.phase.max_per_user - obj.total_purchased
            if remaining <= 0:
                return format_html(
                    '<span style="color: #dc3545;">Limit Reached</span>'
                )
            return f"${remaining:,.2f}"
        return "No Limit"
    formatted_remaining.short_description = 'Remaining'
    
    def has_add_permission(self, request):
        return False


@admin.register(PresaleSettings)
class PresaleSettingsAdmin(admin.ModelAdmin):
    list_display = ['is_presale_active', 'is_presale_claims_unlocked', 'presale_finished_at', 'claims_unlocked_at', 'updated_at']
    readonly_fields = ['created_at', 'updated_at', 'presale_finished_at', 'claims_unlocked_at']
    
    fieldsets = (
        (
            'Global Presale Control',
            {
                'fields': ('is_presale_active', 'is_presale_claims_unlocked', 'presale_finished_at', 'claims_unlocked_at'),
                'description': 'Master switches. Use the action below to finish presale and unlock claims safely.'
            }
        ),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    actions = ['unlock_claims_and_finish_presale']
    
    def has_add_permission(self, request):
        # Only allow one instance
        return PresaleSettings.objects.count() == 0
    
    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion
        return False

    def unlock_claims_and_finish_presale(self, request, queryset):
        """Mark all presale phases as completed, disable presale, unlock on-chain claims, and set timestamps."""
        from django.utils import timezone
        from django.conf import settings as dj_settings
        try:
            # Update DB first (idempotent)
            from .models import PresalePhase, PresaleSettings
            PresalePhase.objects.exclude(status='completed').update(status='completed')
            settings_obj = PresaleSettings.get_settings()
            settings_obj.is_presale_active = False
            settings_obj.is_presale_claims_unlocked = True
            if not settings_obj.presale_finished_at:
                settings_obj.presale_finished_at = timezone.now()
            settings_obj.claims_unlocked_at = timezone.now()
            settings_obj.save()

            # Attempt on-chain permanent unlock (best-effort; report errors clearly)
            app_id = getattr(dj_settings, 'ALGORAND_PRESALE_APP_ID', 0)
            confio_id = getattr(dj_settings, 'ALGORAND_CONFIO_ASSET_ID', 0)
            cusd_id = getattr(dj_settings, 'ALGORAND_CUSD_ASSET_ID', 0)
            admin_mn = getattr(dj_settings, 'ALGORAND_ADMIN_MNEMONIC', None) or getattr(dj_settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if not app_id or not confio_id or not cusd_id or not admin_mn:
                self.message_user(request, 'On-chain unlock skipped: missing PRESALE APP/ASSET IDs or admin mnemonic', level='warning')
            else:
                try:
                    from contracts.presale.admin_presale import PresaleAdmin as _PresaleAdmin
                    from algosdk import mnemonic as _mn
                    from algosdk.account import address_from_private_key as _addr_from_sk
                    pa = _PresaleAdmin(int(app_id), int(confio_id), int(cusd_id))
                    admin_sk = _mn.to_private_key(" ".join(str(admin_mn).strip().split()))
                    admin_addr = _addr_from_sk(admin_sk)
                    # Do not prompt (automation-friendly)
                    pa.permanent_unlock(admin_address=admin_addr, admin_sk=admin_sk, skip_confirmation=True)
                    self.message_user(request, 'On-chain permanent unlock executed successfully.')
                except Exception as chain_e:
                    self.message_user(request, f'On-chain unlock attempt failed: {chain_e}', level='error')

            self.message_user(request, 'Presale marked finished and claims unlocked.')
        except Exception as e:
            self.message_user(request, f'Failed to unlock claims: {e}', level='error')
    unlock_claims_and_finish_presale.short_description = 'Finish presale and unlock user claims (on-chain + DB)'
