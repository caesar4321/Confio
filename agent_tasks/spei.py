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
                           r'|total a transferir|total del pedido|total de la orden|monto total|importe total'
                           r'|total de tu pedido|pago total)$')
# The order's own number, where the page prints no transfer reference (a CLABE made for that one order).
_ORDER_NUMBER = re.compile(r'\b(pedido|orden|order)\s*(n\.?\s*[oº°]\.?|no\.?|num\.?|numero|number|#)?\s*:?\s*#?\s*'
                           r'(\d{3}-\d{7}-\d{7}|\d{6,20})\b', re.I)


def order_number(text):
    """The order number a page prints ("Pedido n.º 701-1234567-1234567"), digits and spaces only, or ''."""
    found = _ORDER_NUMBER.search(' '.join(str(node) for node in (text or ())))
    return re.sub(r'[^0-9]+', ' ', found.group(3)).strip() if found else ''
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


_FIGURE = re.compile(r'(?<![\d.,])((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?![\d,]|\.\d)')
# Whole pesos ("$99"): only with their sign, so a quantity or a date is never an amount.
_WHOLE = re.compile(r'\$\s*((?:\d{1,3}(?:,\d{3})+|\d+))(?!\d)(?![.,]\d)')


def clabes_in(nodes):
    """Every valid CLABE written in those texts."""
    return {digits for node in nodes for digits in (_clabe(match.group(1)) for match in _CLABE.finditer(str(node)))
            if digits}


def _by_facts(nodes, expected, item='', before=()):
    """The order's payment page, by what is true of it and no label: one valid CLABE on the whole page (its
    check digit proves it is one), written beside the amount the person approved. Never an account a seller
    could have written: one inside the item's own name, or one already on a page before the order existed
    (the store makes this order's account after it). Which page this is was a model's reading
    (agent.payment_page) and the runner's facts (the store's own site, a page new since the order)."""
    anywhere = clabes_in(nodes)
    if len(anywhere) != 1:
        return None, 'several' if anywhere else 'code'
    clabe = next(iter(anywhere))
    if clabe in set(before or ()) or clabe in re.sub(r'\D', '', str(item or '')):
        return None, 'several'
    wanted = Decimal(expected)
    at_amount = [index for index, node in enumerate(nodes)
                 if any(Decimal(match.group(1).replace(',', '')) == wanted
                        for match in (*_FIGURE.finditer(node), *_WHOLE.finditer(node)))]
    at_clabe = [index for index, node in enumerate(nodes) if clabes_in([node])]
    if not at_amount or min(abs(a - c) for a in at_amount for c in at_clabe) > _TOGETHER:
        return None, 'code'   # the amount is not on it, or nowhere near the account
    try:
        references = {value for _, value in _labelled(nodes, _REFERENCE_LABEL, _reference)}
    except _Unreadable:
        references = set()
    return {'clabe': anywhere.pop(), 'amount': Decimal(expected),
            'reference': references.pop() if len(references) == 1 else ''}, ''


def read(text, *, reference_optional=False, expected=None, item='', before=()):
    """({'clabe', 'amount', 'reference'}, '') or (None, why): 'code' when
    something is missing, 'several' when anything is doubtful: two
    candidates, a labelled value that does not read, a numeric reference,
    dollars on the page, or values far apart. With `expected` (the amount the
    person approved) nothing is read by its label: see _by_facts."""
    if text is None:
        return None, 'several'   # too long to read whole
    nodes = [str(node) for node in text]
    folded = [fold(node) for node in nodes]
    if expected is not None:
        if any(_DOLLARS.search(node) for node in folded):
            return None, 'several'
        return _by_facts(nodes, expected, item, before)
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
    # A CLABE made for this one payment (the payment house's own ticket) needs no reference of its own.
    needed = values[:2] if reference_optional and not values[2] else values
    if not all(needed) or anywhere != values[0]:
        return None, 'code'
    positions = [position for found in (clabes, amounts, references) for position, _ in found]
    if max(positions) - min(positions) > _TOGETHER:
        return None, 'several'
    return {'clabe': values[0].pop(), 'amount': values[1].pop(),
            'reference': values[2].pop() if values[2] else ''}, ''
