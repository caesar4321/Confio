"""What differs by country: how a checkout there is paid.

The agent, the guard and the hand-over are the same in every country. What a
country adds is a Rail: which QR on the person's screen is that country's
payment code, what a page writes beside it, which payment rail prepares the
card, and how far that rail vouches for whoever is paid. A country without a
rail that pays a store's EXACT local amount is not offered: a dollar transfer
to an account number is never the store's charge, and the order is unpaid or
paid twice.

Today: Brazil (Pix QR, Infinia), Mexico (SPEI, Infinia) and Bolivia (bank
QR, paid by the provider that decodes it; while QR Bolivia is off the order is
still placed and the person pays the store's QR from their bank: `manual`).
Argentina's fixed-amount QR and Venezuela's Pago Móvil need exact-amount
payouts first (docs/designs/ai-assistant-server-architecture.md, section 5.6).
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Rail:
    country: str           # ISO 3166 alpha-2, as on the task and the proxy
    method_id: str         # the payment_intents rail that prepares the card
    currency: str
    payees: frozenset      # payee levels a card read off a screen may carry
    name: str              # what the person picks at the store: "Pix", "QR"
    qr: str                # "el QR de Pix"
    paste: str             # where else the person can pay that code
    vouches: str           # who stands behind the card's amount and payee

    # Each rail answers these three; the rest of agent_tasks is rail-blind.
    def codes(self, texts):
        """The QR texts that are, whole, one payment code of this rail."""
        raise NotImplementedError

    def written(self, words):
        """The codes of this rail written anywhere on the page."""
        raise NotImplementedError

    def ready(self, account, identity, meta):
        """Raises PaymentAccountError when this account cannot pay it now."""
        raise NotImplementedError

    kind = 'qr'            # read as one QR on screen (runner.code_on_screen)
    can_go_manual = True   # when Confío cannot pay it, the person pays the store's own code
    opens = ''             # the local account (LocalAccountApplication) that lets Confío pay it
    numeric = ''           # ISO 4217 numeric, as an EMV code carries it (tag 53)

    def manual(self, meta):
        """True when Confío cannot pay this rail for anyone now (a switch)."""
        return False

    def pay_mode(self, account, identity, meta):
        """('confio', '') when Confío pays this rail's code for this person now. Else
        ('manual', offer): the order is still placed and the person pays the store's own
        payment data from their bank; `offer` is the local account that would let Confío
        pay it next time ('' when none can be opened for them)."""
        from payment_accounts.local_money import REGION_UNSUPPORTED_MESSAGE
        from payment_accounts.services import PaymentAccountError
        if self.manual(meta):
            return 'manual', ''
        try:
            self.ready(account, identity, meta)
        except PaymentAccountError as exc:
            return 'manual', '' if str(exc) == REGION_UNSUPPORTED_MESSAGE else self.opens
        return 'confio', ''

    def request(self, meta):
        return {'method_id': self.method_id, 'meta': dict(meta or {})}


@dataclass(frozen=True)
class PixRail(Rail):
    opens = 'br_qr'
    numeric = '986'

    def codes(self, texts):
        from payment_accounts import payment_intents
        return {text for text in texts if payment_intents.find_pix_codes(text) == [text]}

    def written(self, words):
        from payment_accounts import payment_intents
        found = set()
        for text in words:
            if '000201' in text:
                found.update(payment_intents.find_pix_codes(text))
        return found

    def ready(self, account, identity, meta):
        from payment_accounts import local_money
        local_money.require_rail(account, identity, local_money.METHODS['br_qr'])
        # What the payment card will need: an open, active local account.
        local_money._active_pair(account, 'BRA', 'BRL')


# Longest a Bolivian bank QR is read as (the provider's own limit).
_BO_MAX = 2000


@dataclass(frozen=True)
class BoliviaQrRail(Rail):
    """A Bolivian bank's QR has no public format: the paying provider decodes
    it and names its holder. So any QR that is not a link and not another
    scheme's code is a candidate, and the provider is the one that says it is
    a payment (it refuses anything else)."""

    def codes(self, texts):
        from payment_accounts import intent_rails, local_money
        found = set()
        for text in texts:
            if not 16 <= len(text) <= _BO_MAX or _link(text) or intent_rails.detect_method(text) is not None:
                continue
            # A scheme prefix ("QRSIMPLE:") may come before the EMV body: its country is read past it.
            fields = local_money.emv_fields(re.sub(r'^[^:]{1,20}:', '', text))
            if fields and fields.get('58') not in (None, 'BO'):
                continue  # another country's payment code
            found.add(text)
        return found

    def written(self, words):
        return set()  # nothing on a page can be told to be one

    numeric = '068'

    def ready(self, account, identity, meta):
        # Payable either way: by Confío when QR Bolivia is on, else by the person's own bank (manual).
        return None

    def manual(self, meta):
        from ramps import bolivia_qr
        # The switch and the build, never a tester list: open to everyone or to nobody.
        return not (bolivia_qr.enabled(bolivia_qr.SEND) and bolivia_qr.client_supports(bolivia_qr.SEND, meta))


@dataclass(frozen=True)
class SpeiRail(Rail):
    """Mexico: a store order paid by SPEI shows a CLABE, the exact pesos and
    the order's reference as text (spei.py). Paid at exactly that amount with
    that reference; the account is the store's as its checkout showed it."""
    kind = 'text'
    opens = 'mx_clabe'
    numeric = '484'

    def read(self, shots, *, reference_optional=False, expected=None, item='', before=()):
        """(clabe, request fields, '') or ('', {}, why). `expected`: the amount the person approved."""
        from . import spei
        how = {'reference_optional': reference_optional, 'expected': expected, 'item': item, 'before': before}
        details, why = spei.read(shots[0].text, **how)
        again, _ = spei.read(shots[1].text, **how)
        if why or again != details:
            return '', {}, why or 'screen'
        return details['clabe'], {'amount_local': str(details['amount']), 'reference': details['reference']}, ''

    def ready(self, account, identity, meta):
        from payment_accounts import local_money
        local_money.require_rail(account, identity, local_money.METHODS['mx_clabe'])
        local_money._active_pair(account, 'MEX', 'MXN')


@dataclass(frozen=True)
class ManualRail(Rail):
    """A country where Confío pays no store yet: the agent still buys, with a way to pay
    that is never a card (a transfer, a deposit, cash at a shop, a bank QR), and the
    person pays it from their bank with the store's own data off the order's page."""
    kind = 'manual'

    def pay_mode(self, account, identity, meta):
        return 'manual', ''

    def ready(self, account, identity, meta):
        return None

    def codes(self, texts):
        # Any QR that is not a link and not another country's code: the person's bank reads it.
        from payment_accounts import local_money
        found = set()
        for text in texts:
            if not 16 <= len(text) <= _BO_MAX or _link(text):
                continue
            fields = local_money.emv_fields(re.sub(r'^[^:]{1,20}:', '', text))
            if fields and fields.get('58') not in (None, self.country):
                continue
            found.add(text)
        return found

    def written(self, words):
        return set()


# ISO 4217 numeric of each country's own currency, as an EMV code writes it (tag 53).
_NUMERIC = {'AR': '032', 'CL': '152', 'CO': '170', 'PE': '604', 'EC': '840', 'UY': '858', 'PY': '600', 'VE': '928',
            'GT': '320', 'CR': '188', 'PA': '590', 'DO': '214', 'SV': '840', 'HN': '340', 'NI': '558'}


@dataclass(frozen=True)
class _Manual(ManualRail):
    numeric: str = ''


def manual_rail(country):
    return _Manual(
        numeric=_NUMERIC.get(country, ''),
        country=country, method_id='', currency='', payees=frozenset(), name='un pago sin tarjeta',
        qr='los datos de pago', paste='paga el pedido desde tu banco con los datos que muestra la tienda',
        vouches='Son los datos que mostró la tienda en tu pedido; nadie verificó a quién pertenece la cuenta.')


def _link(text):
    head = text.strip().lower()
    if head.startswith(('www.', 'begin:vcard', 'begin:vevent', '{', '[')):
        return True
    # Known non-bank schemes only: a bank's own format may well start "XYZ:".
    return bool(re.match(r'^(https?|mailto|tel|sms|smsto|mms|mmsto|wifi|geo|market|intent|data|javascript|file|ftp'
                         r'|bitcoin|ethereum|lightning|litecoin|tron|solana|upi|otpauth|matmsg|mecard|fido):', head))


RAILS = {
    'BR': PixRail(
        country='BR', method_id='br_qr', currency='BRL', name='Pix', qr='el QR de Pix',
        # Decided 2026-11-22 (A): a payee the payment institution signs, by name or by amount.
        payees=frozenset({'holder_verified', 'institution_charge', 'institution_amount'}),
        paste='abre el pedido en tu celular y pégame el código Pix aquí',
        vouches=('Una institución de pago conocida firma el monto; el nombre de quien cobra puede venir del propio '
                 'código y no estar verificado.')),
    'BO': BoliviaQrRail(
        country='BO', method_id='bo_qr', currency='BOB', name='QR', qr='el QR de pago',
        # The provider decodes the bank's QR and names its holder and bank.
        payees=frozenset({'provider_named'}),
        paste='abre el pedido en tu celular, guarda el QR y págalo desde Pagar',
        vouches=('El proveedor de pago leyó ese QR con el banco y nombra a quien cobra; el monto es el del QR.')),
    'MX': SpeiRail(
        country='MX', method_id='mx_clabe', currency='MXN', name='transferencia SPEI',
        qr='la CLABE, el monto y la referencia de la transferencia',
        # Decided 2026-11-23: the store's CLABE as its own checkout shows it, holder not looked up.
        payees=frozenset({'store_checkout'}),
        paste='págalo desde tu banco con esa CLABE, el monto exacto y la referencia, o elige otro medio en la tienda',
        vouches=('La CLABE, el monto y la referencia son los que mostró la tienda; nadie verificó a quién pertenece '
                 'la CLABE. Pagas exactamente el monto del pedido y lo que sobre del cambio queda en tu cuenta en '
                 'pesos.')),
}
# Store addresses that say their country.
_TLD = {'br': 'BR', 'bo': 'BO', 'mx': 'MX'}


def rail(country):
    """The country's rail; a country Confío pays no store in yet, where the person pays (manual)."""
    from . import conf
    code = str(country or '').upper()
    if code in RAILS:
        return RAILS[code]
    return manual_rail(code) if code in conf.get('AGENT_TASKS_MANUAL_COUNTRIES') else None


def country_of(store, user=None):
    """Where a store sells, from its own address only: its country domain.
    Never the person's country: a Brazilian store on ".com" bought from
    Bolivia would be handed to a rail that cannot pay its QR. '' when the
    address does not say (refused)."""
    tld = str(store or '').rsplit('.', 1)[-1].lower()
    if tld in _TLD:
        return _TLD[tld]
    return tld.upper() if tld.isalpha() and len(tld) == 2 else ''
