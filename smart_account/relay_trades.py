"""Hands-off chat trades, executed by the Cuenta inteligente (v2 relayTrade).

The person's exact "sí" in the chat (assistant/trades.py) makes one
SmartRelayTrade row; nothing is quoted or sent in the chat request. The
Celery task `smart_account.run_relay_trade` then, for that one row:

  1. waits until the reply that carries its status card is in the chat; a
     reply written without it (they wrote "no, cancela" meanwhile) cancels;
  2. checks the route again (hands_off.route: subscriber, v2, live Trade rule,
     not paused, the asset held / the dollars there);
  3. gets a binding quote (stocks: Ondo's signed quote; bitcoin and gold:
     the swap router with feed-bounded floors), the same builders automation
     uses (quotes.py);
  4. checks the bucket off chain (bucketOf: used + this buy <= the cap) and
     the contract's 60 s gap between relay trades;
  5. validates the exact calldata (relay_policy.check_relay_trade, the twin of
     _check_trade + the personal rail's gates);
  6. sends relayTrade from the sponsor through relayer.send_relayer_call:
     simulated first, the durable SmartAccountRelayTx row written with the
     signed hash before broadcast, idempotent on (account, kind, the row's id);
  7. after the receipt (`smart_account.finish_relay_trade`), posts the result
     in the chat. A broadcast never assumed landed: an exception after
     signing leaves the row 'unknown' and the receipt decides.
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import abi, chain, hands_off

logger = logging.getLogger(__name__)

WAD = 10 ** 18
# The reply with the status card is written right after the "sí" is read; past
# this, a reply without it means the card was withdrawn.
REPLY_WAIT = timedelta(seconds=45)
# A rule just signed on the cap card becomes live once reconcile sees it.
RULE_WAIT = timedelta(minutes=15)
MAX_ATTEMPTS = 3
_META_KEYS = ('HTTP_X_CONFIO_PLATFORM', 'HTTP_X_CONFIO_APP_VERSION', 'HTTP_CF_IPCOUNTRY', 'REMOTE_ADDR',
              'HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP')

ACTION_TYPE = 'relay_trade'


class Later(Exception):
    """Not now: run again in `seconds`."""

    def __init__(self, seconds: int, why: str = ''):
        self.seconds = max(2, int(seconds))
        super().__init__(why or f'later {seconds}s')


class Refused(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def new_nonce() -> str:
    return secrets.token_hex(12)


def kept_meta(meta, lang: str = '') -> dict:
    """Only the headers the gates read (platform, country), and the language the
    chat answered the "sí" in (`lang`: the result note is said in it)."""
    kept = {key: str(meta[key])[:200] for key in _META_KEYS if (meta or {}).get(key)}
    if lang in LANGS:
        kept['lang'] = lang
    return kept


# ── the person's language ───────────────────────────────────────────────

LANGS = ('es', 'pt', 'en')
# The person's last few messages decide (assistant/confirm.language), as the chat reads them.
LANG_WINDOW = 3


def conversation_lang(user, conversation_id=None, before=None) -> str:
    """'es' | 'pt' | 'en': the language of the person's latest chat messages (up to `before`)."""
    try:
        from assistant import confirm
        from inbox.models import SupportMessage
        found = SupportMessage.objects.filter(conversation__user=user, sender_type='USER')
        if conversation_id:
            found = found.filter(conversation_id=conversation_id)
        if before is not None:
            found = found.filter(created_at__lte=before + timedelta(seconds=5))
        texts = [body for body in found.order_by('-created_at', '-pk').values_list('body', flat=True)[:LANG_WINDOW]
                 if (body or '').strip()]
        return confirm.language(texts) if texts else 'es'
    except Exception:  # noqa: BLE001 — a note in Spanish beats no note
        logger.warning('relay: could not read the chat language of user %s', getattr(user, 'pk', None))
        return 'es'


def lang_of(row) -> str:
    """The language the row's result is told in: the one the chat answered its "sí" in, else the chat's."""
    said = str((row.meta or {}).get('lang') or '')
    if said in LANGS:
        return said
    return conversation_lang(row.user, row.conversation_id, before=row.created_at)


def said(texts: dict, lang: str) -> str:
    return texts.get(lang) or texts['es']


def create(user, *, nonce: str, side: str, asset_kind: str, ticker: str, amount, sell_all: bool, meta,
           conversation_id=None, status: str = 'pending', lang: str = ''):
    """The row for one "sí". The same question's second "sí" gets the first row back."""
    from .context import own_account
    from .models import SmartRelayTrade
    defaults = dict(smart_account=own_account(user), side=side, asset_kind=asset_kind, ticker=ticker,
                    amount_usd=None if sell_all or amount is None else Decimal(amount), sell_all=bool(sell_all),
                    meta=kept_meta(meta, lang), status=status, conversation_id=conversation_id)
    try:
        with transaction.atomic():
            row, created = SmartRelayTrade.objects.get_or_create(user=user, nonce=nonce, defaults=defaults)
    except IntegrityError:
        row, created = SmartRelayTrade.objects.get(user=user, nonce=nonce), False
    if created and status == 'pending':
        schedule(row.pk, countdown=2)
    return row, created


def schedule(row_id: int, countdown: int = 2) -> None:
    def go():
        try:
            from .tasks import run_relay_trade
            run_relay_trade.apply_async(args=[row_id], countdown=countdown)
        except Exception:  # noqa: BLE001 — the sweep picks it up
            logger.exception('relay trade %s could not be scheduled', row_id)
    transaction.on_commit(go)


def resume(user, internal_id) -> object | None:
    """The cap card was signed: the trade waiting for its rule runs (it waits
    for the rule to be live). Only the owner's own waiting row."""
    from .models import SmartRelayTrade
    row = SmartRelayTrade.objects.filter(user=user, internal_id=internal_id).first()
    if row is None:
        return None
    if row.status in ('waiting_rule', 'waiting_move'):
        won = SmartRelayTrade.objects.filter(pk=row.pk, status=row.status).update(
            status='pending', updated_at=timezone.now())
        if won:
            row.status = 'pending'
            schedule(row.pk)
    return row


# ── the chat ────────────────────────────────────────────────────────────

def label(row) -> str:
    from assistant.trades import money
    what = row.ticker.removesuffix('on')
    if row.sell_all:
        return f'Vender todo {what}'
    verb = 'Comprar' if row.side == 'buy' else 'Vender'
    return f'{verb} {money(row.amount_usd)} de {what}'


def card(row) -> dict:
    # `target` carries the id to the app (AssistantActionType has no other free field).
    return {'type': ACTION_TYPE, 'trade': str(row.internal_id), 'target': str(row.internal_id), 'label': label(row)}


def _reply_state(row) -> str:
    """'shown' when the reply carrying this row's card is in the chat,
    'withdrawn' when the reply came without it, 'waiting' meanwhile."""
    from inbox.models import SupportMessage
    if row.conversation_id is None:
        return 'shown'
    later = SupportMessage.objects.filter(conversation_id=row.conversation_id, sender_type='AGENT',
                                          created_at__gte=row.created_at - timedelta(seconds=5))
    # Any card naming this row: its status card, or the cap / move card it waited on (review P2-1: a trade
    # resumed after the cap card was signed carried 'trade_cap', never 'relay_trade').
    if later.filter(metadata__actions__contains=[{'trade': str(row.internal_id)}]).exists():
        return 'shown'
    if timezone.now() - row.created_at > REPLY_WAIT:
        return 'withdrawn'
    return 'waiting'


MESSAGES = {
    'done_buy': {'es': 'Listo: compré {what} por {spent} desde tu Cuenta inteligente. Lo tienes ahí.',
                 'pt': 'Pronto: comprei {what} por {spent} pela sua Cuenta inteligente. Já está lá.',
                 'en': 'Done: I bought {what} for {spent} from your Cuenta inteligente. It is there now.'},
    'done_sell': {'es': 'Listo: vendí {what} y recibiste {got} en tu Cuenta inteligente.',
                  'pt': 'Pronto: vendi {what} e você recebeu {got} na sua Cuenta inteligente.',
                  'en': 'Done: I sold {what} and you got {got} in your Cuenta inteligente.'},
    'market_closed': {'es': 'No compré ni vendí nada: el mercado de acciones está cerrado. Pídemelo cuando abra.',
                      'pt': 'Não comprei nem vendi nada: o mercado de ações está fechado. Peça de novo quando abrir.',
                      'en': "I didn't buy or sell anything: the stock market is closed. Ask me again when it opens."},
    'cap': {'es': 'Todavía no lo hice: esa operación supera tu límite semanal (compras y ventas cuentan). Si lo subes '
                  'con Confío Face, la hago y te aviso aquí.',
            'pt': 'Ainda não fiz: essa operação passa do seu limite semanal (compras e vendas contam). Se você '
                  'aumentar com Confío Face, eu faço e aviso aqui.',
            'en': "I haven't done it yet: that trade is above your weekly limit (buys and sells count). Raise it "
                  "with Confío Face and I'll do it and tell you here."},
    'balance': {'es': 'No compré nada: tu Cuenta inteligente no tiene dólares suficientes. Puedes recargar desde el '
                      'chat.',
                'pt': 'Não comprei nada: sua Cuenta inteligente não tem dólares suficientes. Você pode recarregar '
                      'pelo chat.',
                'en': "I didn't buy anything: your Cuenta inteligente doesn't have enough dollars. You can top up "
                      "from the chat."},
    'price_moved': {'es': 'No lo hice: el precio se movió mientras lo preparaba y no se movió nada. Inténtalo de '
                          'nuevo.',
                    'pt': 'Não fiz: o preço mudou enquanto eu preparava e nada foi movido. Tente de novo.',
                    'en': "I didn't do it: the price moved while I was preparing it, and nothing moved. Try again."},
    'reverted': {'es': 'No se hizo: la operación no pasó en la red y no se movió nada. Puedes pedírmelo otra vez.',
                 'pt': 'Não foi feito: a operação não passou na rede e nada foi movido. Pode me pedir de novo.',
                 'en': "It didn't go through: the trade failed on the network and nothing moved. You can ask me "
                       "again."},
    'failed': {'es': 'No pude hacerlo ahora y no se movió nada. Puedes pedírmelo otra vez o hacerlo tú en Invertir.',
               'pt': 'Não consegui fazer agora e nada foi movido. Pode me pedir de novo ou fazer você em Invertir.',
               'en': "I couldn't do it now and nothing moved. You can ask me again or do it yourself in Invertir."},
}
# What a sell's note says when the dollars it brought are unknown.
SOME_DOLLARS = {'es': 'los dólares', 'pt': 'os dólares', 'en': 'the dollars'}
GOLD = {'es': 'oro digital (XAUt)', 'pt': 'ouro digital (XAUt)', 'en': 'digital gold (XAUt)'}


def _post(row, key: str, **values) -> None:
    from assistant.service import post_system_note
    try:
        body = said(MESSAGES[key], lang_of(row)).format(**values)
        post_system_note(row.user, body, f'relay_trade:{row.internal_id}:{row.status}',
                         actions=[card(row)])
        from .models import SmartRelayTrade
        SmartRelayTrade.objects.filter(pk=row.pk).update(notified_at=timezone.now())
    except Exception:  # noqa: BLE001 — the card shows the state; the note is best effort
        logger.exception('relay trade %s result not posted', row.pk)


def _offer_mark(row) -> int:
    """Which raise offer this is: the time the row last moved (a resume), so a later one is a new note."""
    return int(row.updated_at.timestamp()) if row.updated_at else 0


def _offer_raise(row) -> None:
    """Beyond the weekly cap (buys and sells count): never a bare refusal. The
    trade waits for a higher cap, offered in the chat as the cap card."""
    from assistant.service import post_system_note
    from .models import SmartRelayTrade
    SmartRelayTrade.objects.filter(pk=row.pk).update(status='waiting_rule', error_code='cap',
                                                     updated_at=timezone.now())
    try:
        # One note per raise offer: a second over-cap after a raise is a new message (the tag dedupes).
        post_system_note(row.user, said(MESSAGES['cap'], lang_of(row)),
                         f'relay_trade:{row.internal_id}:cap:{_offer_mark(row)}',
                         actions=[{'type': 'trade_cap', 'trade': str(row.internal_id),
                                   'target': str(row.internal_id), 'label': 'Subir mi límite semanal'}])
    except Exception:  # noqa: BLE001 — the trade waits; asking again shows the card too
        logger.exception('relay trade %s raise offer not posted', row.pk)


def _end(row, status: str, code: str = '', note: str | None = 'failed', **values) -> None:
    from .models import SmartRelayTrade
    SmartRelayTrade.objects.filter(pk=row.pk).update(status=status, error_code=code[:60], updated_at=timezone.now())
    row.status, row.error_code = status, code
    if note:
        _post(row, note, **values)


# ── building the trade ──────────────────────────────────────────────────

def stock_key(ticker: str):
    """(registry symbol, token address) of a listed stock, or None."""
    from .assets import stock_registry
    registry = stock_registry()
    for key in (ticker, f'{ticker}on'):
        meta = registry.get(key)
        if meta and meta.get('address'):
            return key, meta['address'].lower()
    return None


def asset_token(asset_kind: str, ticker: str) -> str:
    if asset_kind == 'stock':
        found = stock_key(ticker)
        return found[1] if found else ''
    from cusd_plus import crypto_catalog
    token = crypto_catalog.by_symbol(ticker)
    return token.address.lower() if token is not None else ''


def _held(own, token: str):
    from . import assets as assets_mod
    for asset in assets_mod.assets_of(own.contract_address):
        if asset.address.lower() == token:
            return asset
    return None


def build(row, own, rule) -> dict:
    """The venue call for this trade, quoted now. Raises QuoteUnavailable / Refused."""
    from cusd_plus import crypto_catalog
    from cusd_plus.crypto_policy import DOLLAR, DOLLAR_PLUS
    from . import quotes
    token = asset_token(row.asset_kind, row.ticker)
    if not token:
        raise Refused('bad_asset')
    plus = chain.cusd_plus_address()
    if row.side == 'buy':
        amount = Decimal(row.amount_usd)
        if row.asset_kind == 'stock':
            limit = chain.balance_of(plus, own.contract_address)
            built = quotes.stock_buy_call(stock_key(row.ticker)[0], quotes.stock_buy_notional(amount), limit)
        else:
            crypto = crypto_catalog.by_symbol(row.ticker)
            in_plus = (rule.token_in or '').lower() == plus
            amount_wei = int(amount * WAD)
            amount_in = quotes.shares_ceil(amount_wei, chain.p_plus_wad()) if in_plus else amount_wei
            built = quotes.crypto_buy_call(crypto, DOLLAR_PLUS if in_plus else DOLLAR, amount_in)
        return built['call']
    asset = _held(own, token)
    if asset is None or not asset.units:
        raise Refused('nothing_to_sell')
    value = Decimal(asset.value_usd or 0)
    if row.asset_kind == 'stock':
        notional = value if row.sell_all else min(Decimal(row.amount_usd), value)
        if notional <= 0:
            raise Refused('nothing_to_sell')
        return quotes.stock_sell_call(asset.key.split(':', 1)[1], notional.quantize(Decimal('0.01'), ROUND_DOWN))['call']
    crypto = crypto_catalog.by_symbol(row.ticker)
    units = int(asset.units)
    if not row.sell_all:
        if value <= 0:
            raise Refused('nothing_to_sell')
        units = min(units, int(Decimal(units) * Decimal(row.amount_usd) / value))
    if units <= 0:
        raise Refused('nothing_to_sell')
    # Proceeds land in the account's dollar of the rule (cUSD+ needs savings eligibility: trade_gate).
    dollar = DOLLAR_PLUS if (rule.token_in or '').lower() == plus else DOLLAR
    return quotes.crypto_sell_call(crypto, dollar, units)['call']


# A sell's proceeds can beat its floor (minOut); the bucket counts what arrives.
SELL_COUNT_MARGIN = Decimal('1.03')


def counted_usd(params: dict) -> Decimal:
    """What the contract will count in the bucket: a buy's dollars in (upper
    bound: maxIn); a sell's dollars out (its floor, with a margin above)."""
    if params['kind'].endswith('buy'):
        return hands_off.dollar_usd(params['token_in'], int(params['max_in']))
    return hands_off.dollar_usd(params['token_out'], int(params['min_out'])) * SELL_COUNT_MARGIN


# ── the task's body ─────────────────────────────────────────────────────

def run(row_id: int) -> None:
    """One pass for one row. Raises Later to be run again; every other end is final and told in the chat."""
    from . import quotes, relayer
    from .context import own_account
    from .models import SmartRelayTrade
    row = SmartRelayTrade.objects.select_related('user').filter(pk=row_id).first()
    if row is None or row.status != 'pending':
        return
    state = _reply_state(row)
    if state == 'waiting':
        raise Later(3, 'reply not written yet')
    if state == 'withdrawn':
        return _end(row, 'cancelled', 'withdrawn', note=None)
    if row.asset_kind == 'crypto':
        from cusd_plus.perps_risk import _is_ios
        if _is_ios(row.meta):
            return _end(row, 'failed', 'ios_no_crypto')
    user = row.user
    token = asset_token(row.asset_kind, row.ticker)
    route = hands_off.route(user, side=row.side, asset_kind=row.asset_kind, token=token, amount=row.amount_usd,
                            sell_all=row.sell_all)
    # From the resume (updated_at): the rule signed on the cap card turns live once reconcile sees it.
    if route.code in ('no_rule', 'move') and timezone.now() - row.updated_at < RULE_WAIT:
        raise Later(15, 'rule or moved dollars not live yet')
    if route.code == 'cap':
        return _offer_raise(row)
    if route.code == 'topup':
        return _end(row, 'failed', 'balance', note='balance')
    if route.code != 'go':
        return _end(row, 'failed', f'route_{route.code}')
    own, rule = route.own, route.rule
    wait = hands_off.gap_wait_seconds(own, rule)
    if wait:
        raise Later(wait + 1, 'min gap between relay trades')

    try:
        venue_call = build(row, own, rule)
    except Refused as exc:
        return _end(row, 'failed', exc.code)
    except quotes.QuoteUnavailable as exc:
        if exc.code == 'market_closed':
            return _end(row, 'failed', exc.code, note='market_closed')
        if row.attempts + 1 < MAX_ATTEMPTS:
            SmartRelayTrade.objects.filter(pk=row.pk).update(attempts=row.attempts + 1)
            raise Later(10, exc.code)
        return _end(row, 'failed', exc.code)

    from cusd_plus.sponsor_7702 import PolicyError
    from . import relay_policy
    from .services import trade_parameters
    try:
        params = trade_parameters(venue_call)
        calldata = abi.relay_trade_call(int(rule.onchain_id), params['venue'],
                                        bytes.fromhex(venue_call['data'][2:]), params['max_in'], params['min_out'])
        params = relay_policy.check_relay_trade(own, rule, calldata, user, row.meta)
    except PolicyError as exc:
        return _end(row, 'failed', getattr(exc, 'code', '') or str(exc))
    # Buys and sells both count in the bucket (audit): never send one the contract would refuse.
    used, _last = hands_off.bucket_of(own.contract_address, int(rule.onchain_id))
    cap_wei = int(chain.account_rule(own.contract_address, int(rule.onchain_id))['amount_usd_wei'])
    if used + int(counted_usd(params) * WAD) > cap_wei:
        return _offer_raise(row)

    def claim(tx_hash):
        # Inside the transaction that writes the durable relay row: the trade row is 'unknown' with that hash
        # until the broadcast is known to have left.
        won = SmartRelayTrade.objects.filter(pk=row.pk, status='pending').update(
            status='unknown', tx_hash=tx_hash, updated_at=timezone.now())
        if not won:
            raise relayer.RelayError('claim_busy', 'trade row moved on')

    gas = abi.RELAY_TRADE_GAS['stock' if row.asset_kind == 'stock' else 'crypto']
    try:
        relay_row, _created = relayer.send_relayer_call(own, calldata, abi.RELAY_TRADE_KIND, str(row.internal_id),
                                                        gas=gas, claim=claim)
    except relayer.RelayError as exc:
        # Nothing was broadcast.
        reverted = abi.v2_revert_error(exc.detail) if exc.code == 'simulation_reverted' else None
        if reverted == 'CapExceeded':
            return _offer_raise(row)
        if reverted == 'BelowFeed':
            # The price moved between the quote and now: quoted again once, then said honestly.
            if row.attempts < 1:
                SmartRelayTrade.objects.filter(pk=row.pk, status='pending').update(attempts=row.attempts + 1)
                raise Later(3, 'below feed: re-quote')
            return _end(row, 'failed', 'below_feed', note='price_moved')
        if exc.code in ('sponsor_busy', 'claim_busy', 'gas_price_too_high', 'simulation_unreadable') \
                and row.attempts + 1 < MAX_ATTEMPTS:
            SmartRelayTrade.objects.filter(pk=row.pk, status='pending').update(attempts=row.attempts + 1)
            raise Later(10, exc.code)
        row.refresh_from_db()
        if row.status == 'pending':
            return _end(row, 'failed', exc.code)
        # Signed and recorded before the refusal (sponsor_lock_lost): the receipt decides.
        return schedule_finish(row.pk)
    except Exception:  # noqa: BLE001 — signed, broadcast unknown: the receipt decides (row stays 'unknown')
        logger.exception('relay trade %s broadcast outcome unknown', row.pk)
        relay_row = relayer.live_tx(own, abi.RELAY_TRADE_KIND, str(row.internal_id))
        if relay_row is None:
            row.refresh_from_db()
            if row.status == 'pending':
                # Nothing was signed and recorded (the claim and the durable row are one transaction):
                # an error before signing, tried again a bounded number of times (review P2-2).
                return _retry_or_fail(row)
    if relay_row is not None:
        SmartRelayTrade.objects.filter(pk=row.pk).update(
            relay_tx=relay_row, tx_hash=relay_row.signed_tx_hash,
            status='sent' if relay_row.status == 'sent' else 'unknown', updated_at=timezone.now())
    schedule_finish(row.pk)


# ── never stranded (review P2-2) ────────────────────────────────────────

# Unexpected errors one row may hit before it is told as failed.
MAX_ERRORS = 5
# A 'pending' row nobody moved for this long is run again; a 'sent'/'unknown' one is resolved again.
STALE = timedelta(minutes=20)
# A row still 'pending' this long after it was asked is told as failed.
GIVE_UP = timedelta(hours=6)


def _retry_or_fail(row):
    from .models import SmartRelayTrade
    attempts = row.attempts + 1
    SmartRelayTrade.objects.filter(pk=row.pk).update(attempts=attempts)
    if attempts < MAX_ERRORS:
        raise Later(10, 'error before signing')
    row.attempts = attempts
    return _end(row, 'failed', 'error')


def on_error(row_id: int) -> bool:
    """The task hit an unexpected error (not Later): True to try again; False once the row was told as failed.
    A row no longer 'pending' is left to its own path (the receipt decides a claimed one)."""
    from .models import SmartRelayTrade
    row = SmartRelayTrade.objects.select_related('user').filter(pk=row_id).first()
    if row is None or row.status != 'pending':
        return False
    try:
        _retry_or_fail(row)
    except Later:
        return True
    return False


def sweep() -> dict:
    """Beat: rows a lost schedule (broker outage) or a dead worker left behind. 'pending' ones run again
    (or, past GIVE_UP, are told as failed); 'sent'/'unknown' ones have their receipt read again."""
    from .models import SmartRelayTrade
    now, out = timezone.now(), {'rerun': 0, 'gave_up': 0, 'finish': 0}
    for row in SmartRelayTrade.objects.select_related('user').filter(
            status='pending', updated_at__lt=now - STALE).order_by('updated_at')[:100]:
        if row.created_at < now - GIVE_UP:
            _end(row, 'failed', 'stale')
            out['gave_up'] += 1
            continue
        SmartRelayTrade.objects.filter(pk=row.pk, status='pending').update(updated_at=now)
        schedule(row.pk, countdown=1)
        out['rerun'] += 1
    for row_id in SmartRelayTrade.objects.filter(status__in=('sent', 'unknown'),
                                                 updated_at__lt=now - STALE).values_list('pk', flat=True)[:100]:
        SmartRelayTrade.objects.filter(pk=row_id).update(updated_at=now)
        schedule_finish(row_id, countdown=1)
        out['finish'] += 1
    return out


def schedule_finish(row_id: int, countdown: int = 5) -> None:
    try:
        from .tasks import finish_relay_trade
        finish_relay_trade.apply_async(args=[row_id], countdown=countdown)
    except Exception:  # noqa: BLE001
        logger.exception('relay trade %s finish could not be scheduled', row_id)


def finish(row_id: int) -> None:
    """After the broadcast: the receipt decides; the result goes to the chat. Raises Later while unknown."""
    from cusd_plus import crypto_catalog
    from . import relayer
    from .models import SmartAccountRelayTx, SmartRelayTrade
    row = SmartRelayTrade.objects.select_related('user', 'smart_account').filter(pk=row_id).first()
    if row is None or row.status not in ('sent', 'unknown'):
        return
    relay_row = row.relay_tx or (SmartAccountRelayTx.objects.filter(signed_tx_hash=row.tx_hash).first()
                                 if row.tx_hash else None)
    if relay_row is None:
        raise Later(10, 'no relay row yet')
    if relay_row.status in ('signed', 'sent'):
        relayer.resolve_receipt(relay_row)
        if relay_row.status == 'sent':
            relayer.drop_if_nonce_passed(relay_row)
    if relay_row.status in ('signed', 'sent'):
        raise Later(10, 'receipt pending')
    if relay_row.status != 'confirmed':
        return _end(row, 'failed', relay_row.status, note='reverted')
    receipt = chain.receipt(relay_row.signed_tx_hash) or {}
    event = None
    for log in receipt.get('logs') or []:
        if (log.get('address') or '').lower() != row.smart_account.contract_address.lower():
            continue
        event = abi.decode_relay_traded(log)
        if event:
            break
    from assistant.trades import money
    lang = lang_of(row)
    values = {'what': row.ticker.removesuffix('on'), 'spent': '', 'got': ''}
    if event:
        SmartRelayTrade.objects.filter(pk=row.pk).update(
            amount_in=event['amountIn'], amount_out=event['amountOut'], usd_counted=event['usdCounted'])
        dollar_in = event['tokenIn'] in (chain.cusd_plus_address(), chain.cusd_address())
        if dollar_in:
            values['spent'] = money(hands_off.dollar_usd(event['tokenIn'], int(event['amountIn'])), lang)
        else:
            values['got'] = money(hands_off.dollar_usd(event['tokenOut'], int(event['amountOut'])), lang)
    if not values['spent'] and row.amount_usd is not None:
        values['spent'] = money(row.amount_usd, lang)
    if not values['got']:
        values['got'] = said(SOME_DOLLARS, lang)
    if row.asset_kind == 'crypto':
        token = crypto_catalog.by_symbol(row.ticker)
        values['what'] = said(GOLD, lang) if row.ticker == 'XAUT' else (token.symbol if token else row.ticker)
    _end(row, 'done', '', note='done_buy' if row.side == 'buy' else 'done_sell', **values)


def result_text(row, prefix: str = 'relay_trade') -> str:
    """The result note posted for this finished trade ("Listo: vendí AAPL y recibiste US$1…"), '' before it is.
    The card's title becomes it: the detail is on the card itself, whether or not the open chat has reloaded
    (founder, 2026-11-25: "Hecho. Te dejé el detalle en el chat." and no detail in sight)."""
    if row.status not in ('done', 'failed'):
        return ''
    from inbox.models import SupportMessage
    try:
        note = (SupportMessage.objects.filter(conversation__user_id=row.user_id, sender_type='SYSTEM',
                                              metadata__notice=f'{prefix}:{row.internal_id}:{row.status}')
                .values_list('body', flat=True).first())
    except Exception:  # noqa: BLE001 - the plain label then
        logger.warning('relay trade %s result note unreadable', row.pk, exc_info=True)
        return ''
    return (note or '').strip()


def status_of(user, internal_id) -> dict | None:
    """The card's view of one trade (assistantRelayTrade)."""
    from .models import SmartRelayTrade
    try:
        row = SmartRelayTrade.objects.filter(user=user, internal_id=internal_id).first()
    except (TypeError, ValueError):
        row = None
    if row is None:
        return None
    shown = {'waiting_rule': 'waiting_rule', 'waiting_move': 'waiting_move', 'pending': 'pending',
             'sent': 'pending', 'unknown': 'pending'}
    out = {'status': shown.get(row.status, row.status), 'tx_hash': row.tx_hash or '',
           'label': result_text(row) or label(row), 'error_code': row.error_code or '',
           'asset_kind': row.asset_kind}
    if row.status == 'waiting_rule':
        # The cap card's figures: the choices, the one preselected, the cap today (when raising).
        rule = hands_off.trade_rule(row.smart_account)
        current = Decimal(rule.amount) if rule is not None else Decimal(0)
        out.update(mode='raise' if rule is not None else 'new',
                   choices=[str(c) for c in hands_off.CAP_CHOICES],
                   current_cap=str(current) if rule is not None else None,
                   preselected=str(hands_off.suggested_cap(user, current + Decimal(row.amount_usd or 0))))
    if row.status == 'waiting_move':
        route = move_route(row)
        out['move_amount'] = format(route.facts['move'], 'f') if route.code == 'move' else None
    return out


def move_route(row):
    """The route of a trade waiting for dollars moved in (its move amount is the server's)."""
    from .context import personal_account
    personal = personal_account(row.user)
    return hands_off.route(row.user, side=row.side, asset_kind=row.asset_kind,
                           token=asset_token(row.asset_kind, row.ticker), amount=row.amount_usd,
                           sell_all=row.sell_all, personal_address=getattr(personal, 'bsc_address', '') or '')


# ── every RelayTraded the reconciler sees (audit M1/M2) ─────────────────

def _asset_name(address: str) -> str:
    from cusd_plus import crypto_catalog
    from .assets import stock_by_address
    stock = stock_by_address(address)
    if stock is not None:
        return stock[0].removesuffix('on')
    token = crypto_catalog.by_address(address, include_unlisted=True)
    return token.symbol if token is not None else address[:10]


TRADED_TITLE = {
    'buy': {'es': 'Tu Cuenta inteligente compró {asset}', 'pt': 'Sua Cuenta inteligente comprou {asset}',
            'en': 'Your Cuenta inteligente bought {asset}'},
    'sell': {'es': 'Tu Cuenta inteligente vendió {asset}', 'pt': 'Sua Cuenta inteligente vendeu {asset}',
             'en': 'Your Cuenta inteligente sold {asset}'},
}
FOR_VALUE = {'es': ' por {value}', 'pt': ' por {value}', 'en': ' for {value}'}
NOT_ASKED = {'es': ' No lo pediste en el chat: si no reconoces esta operación, escríbenos aquí ahora.',
             'pt': ' Você não pediu isso no chat: se não reconhece esta operação, escreva aqui agora.',
             'en': " You didn't ask for it in the chat: if you don't recognize this trade, write to us here now."}


def on_relay_traded(account, event) -> None:
    """The owner hears of every hands-off trade at once: a push always, and a
    chat note unless the chat trade's own result note covers it. A trade no
    chat proposal asked for (no SmartRelayTrade row) is also sent to ops."""
    from config.ops_alerts import send_ops_alert
    from .models import SmartRelayTrade
    from .notifications import _send, safe
    args = event.args or {}
    tx = (event.tx_hash or '').lower()
    row = SmartRelayTrade.objects.filter(tx_hash__iexact=tx).first()
    dollars = (chain.cusd_plus_address(), chain.cusd_address())
    buy = str(args.get('tokenIn') or '').lower() in dollars
    asset = _asset_name(str(args.get('tokenOut' if buy else 'tokenIn') or ''))
    dollar_token, units = (args.get('tokenIn'), args.get('amountIn')) if buy else (args.get('tokenOut'),
                                                                                  args.get('amountOut'))
    user = account.owner_user
    lang = lang_of(row) if row is not None else conversation_lang(user)
    try:
        from assistant.trades import money
        value = money(hands_off.dollar_usd(str(dollar_token).lower(), int(units or 0)), lang)
    except Exception:  # noqa: BLE001 — the alert goes out without the figure
        value = ''
    title = said(TRADED_TITLE['buy' if buy else 'sell'], lang).format(asset=asset)
    body = title + (said(FOR_VALUE, lang).format(value=value) if value else '') + '.'
    if row is None:
        body += said(NOT_ASKED, lang)
    safe(_send, user, title, body, kind='relay_traded', account=account,
         security=row is None, data={'tx_hash': tx})
    if row is None:
        try:
            from assistant.service import post_system_note
            post_system_note(user, body, f'relay_traded:{tx}:{event.log_index}')
        except Exception:  # noqa: BLE001
            logger.exception('unexpected relay trade note not posted for %s', tx)
        send_ops_alert(f'Cuenta inteligente: relayTrade sin pedido en el chat. Cuenta {account.contract_address}, '
                       f'usuario {account.owner_user_id}, tx {tx}, regla {args.get("id")}.',
                       dedupe_key=f'relay_trade_unasked_{tx}_{event.log_index}', dedupe_seconds=86400)
