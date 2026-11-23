"""A Mexican store's SPEI payment details, read off its own checkout page.

After the person confirms an order paid by SPEI, the store shows a CLABE, the
exact amount and the order's reference. There is no signed code: what is read
is the page's text, so every value must stand right after its own label, all
three must be there, and each must be the only one of its kind on the page.
Anything less is not guessed: the person is told what was not seen.

Called only on a store page the agent never read (runner.after_checkout), so
nothing a seller wrote on a product page is on it. A seller's text that does
reach the order page (a product title) and carries a labelled CLABE makes two
CLABEs: refused. The card says the account is the store's as its checkout
showed it, unverified (payee level store_checkout).
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

# Labels, folded (no accents, lower case), as Mexican checkouts write them. No bare "Total": a cart's
# total is not what is transferred, and a seller's text can say it.
_CLABE_LABEL = re.compile(r'^(clabe( interbancaria)?|cuenta clabe|clabe spei|numero de clabe)$')
_AMOUNT_LABEL = re.compile(r'^(monto|importe|total a pagar|monto a pagar|monto a transferir|monto exacto'
                           r'|importe a pagar|importe a transferir|cantidad a transferir|cantidad a pagar'
                           r'|total a transferir)$')
_REFERENCE_LABEL = re.compile(r'^(referencia|numero de referencia|referencia de pago|concepto|concepto de pago'
                              r'|referencia/concepto)$')
# A "referencia numérica" is a SPEI field of its own, which the payout cannot fill (it sends a concepto): refused.
_CLABE = re.compile(r'(?<![\d])(\d(?:[ -]?\d){17})(?![\d])')
_AMOUNT = re.compile(r'^(?:mxn|mx)?\s*\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?)\s*(?:mxn|m\.n\.|pesos)?$')
_REFERENCE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ]{0,38}[A-Za-z0-9]$|^[A-Za-z0-9]$')
_DOLLARS = re.compile(r'\b(usd|dolares|dollars?)\b|\bus ?\$|\bu\$s')
# How far after its label a value may stand (text nodes): "Monto", ":", "$", "1,249.00".
_REACH = 3
# How close the three must stand to each other: one ticket, not three corners of a page.
_TOGETHER = 16


def fold(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return ' '.join(text.replace(':', ' ').split())


def clabe_valid(digits):
    from payment_accounts.local_money import clabe_valid as valid
    return valid(digits)


class _Unreadable(Exception):
    """A label whose value cannot be read: never filled in from elsewhere."""


def _labelled(nodes, label, read):
    """[(node index, value)] right after a node that is that label, or written
    in the same node after it ("Referencia: 4021"). A label whose value does
    not read raises _Unreadable."""
    found = []
    for index, node in enumerate(nodes):
        head, colon, rest = node.partition(':')
        if colon and label.fullmatch(fold(head)) and rest.strip():
            value = read(rest.strip(), nodes[index + 1:index + 2])
            if value is None:
                raise _Unreadable
            found.append((index, value))
            continue
        if not label.fullmatch(fold(node)):
            continue
        following, prefix = nodes[index + 1:index + 1 + _REACH], ''
        value, position = None, index
        for offset, item in enumerate(following, start=1):
            if item.strip() in (':', '-', ''):
                continue
            if item.strip() == '$':
                prefix = '$'
                continue
            value, position = read(prefix + item.strip(), nodes[index + offset + 1:index + offset + 2]), index + offset
            break  # only the first thing after the label
        if value is None:
            raise _Unreadable
        found.append((position, value))
    return found


def _clabe(text, after=()):
    match = _CLABE.fullmatch(text.strip())
    digits = re.sub(r'\D', '', match.group(1)) if match else ''
    return digits if len(digits) == 18 and clabe_valid(digits) else None


def _amount(text, after=()):
    match = _AMOUNT.fullmatch(fold(text))
    if not match:
        return None
    # Cents drawn apart ("$1,249" then a superscript "50") are never read as whole pesos.
    if after and re.fullmatch(r'\.?\d{1,2}', after[0].strip()):
        return None
    try:
        value = Decimal(match.group(1).replace(',', ''))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _reference(text, after=()):
    value = ' '.join(text.split())
    # A reference carries a digit: "Pendiente" or "Ver detalle" is not one.
    return value if _REFERENCE.fullmatch(value) and any(c.isdigit() for c in value) else None


def read(text):
    """({'clabe', 'amount', 'reference'}, '') or (None, why): 'code' when
    something is missing, 'several' when anything is doubtful: two
    candidates, a labelled value that does not read, a numeric reference,
    dollars on the page, or values far apart."""
    if text is None:
        return None, 'several'   # too long to read whole
    nodes = [str(node) for node in text]
    folded = [fold(node) for node in nodes]
    if not any('clabe' in node for node in folded):
        return None, 'code'
    if any(_DOLLARS.search(node) for node in folded) or any(node.startswith('referencia numerica') for node in folded):
        return None, 'several'
    try:
        clabes = _labelled(nodes, _CLABE_LABEL, _clabe)
        amounts = _labelled(nodes, _AMOUNT_LABEL, _amount)
        references = _labelled(nodes, _REFERENCE_LABEL, _reference)
    except _Unreadable:
        return None, 'several'
    # Every valid CLABE written anywhere: a second one, labelled or not, is never chosen past.
    anywhere = {digits for node in nodes for digits in (_clabe(match.group(1)) for match in _CLABE.finditer(node))
                if digits}
    values = [{value for _, value in found} for found in (clabes, amounts, references)]
    if any(len(found) > 1 for found in values) or len(anywhere) > 1:
        return None, 'several'
    if not all(values) or anywhere != values[0]:
        return None, 'code'
    positions = [position for found in (clabes, amounts, references) for position, _ in found]
    if max(positions) - min(positions) > _TOGETHER:
        return None, 'several'
    return {'clabe': values[0].pop(), 'amount': values[1].pop(), 'reference': values[2].pop()}, ''
