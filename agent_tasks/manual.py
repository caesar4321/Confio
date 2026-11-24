"""What the person pays an order with from their own bank, read off the order's page.

For a country where Confío pays no store yet (countries.ManualRail): the
order is placed and the person pays it themselves. Nothing here comes from
the model. Only what the store prints right after one of its own payment
labels ("CBU", "Cuenta", "Código de pago", "Referencia", "Titular"...) is
kept, from the page's visible text, the same in both pictures, standing
together with the amount the person approved.

A seller writes on an order's page too (the item's title, messages): a value
found inside the item's title, or a label that shows two values, is never
chosen between. On a marketplace no account, holder or bank is ever taken,
however it is labelled: only the store's own payment reference (a Rapipago or
PagoEfectivo code). Called only on a store page the agent never read while
shopping (runner.after_checkout).
"""
import re

from .spei import fold

# Labels, folded and stripped of punctuation ("Nro. de cuenta", "Cuenta interbancaria (CCI)"), as a whole node
# or "Label: value". Each kind of identifier has its own slot: a page shows a CCI and an account number together.
_TRAIL = r'( [a-z]+){0,3}'   # "Cuenta corriente BCP Soles"
_CCI = re.compile(r'(cci|cuenta interbancaria( cci)?|codigo de cuenta interbancari[oa]( cci)?)' + _TRAIL)
_CBU = re.compile(r'(cbu|cvu)' + _TRAIL)
_ALIAS = re.compile(r'alias( cbu| cvu)?')
# Never a CCI's or a CBU's own label: those have their slots.
_ACCOUNT = re.compile(r'(?!.*\b(cci|cbu|cvu|interbancari[oa])\b)'
                      r'(numero de cuenta|nro de cuenta|n de cuenta|no de cuenta|cuenta|cuenta corriente'
                      r'|cuenta de ahorros?|cuenta bancaria|iban)' + _TRAIL)
_REFERENCE = re.compile(r'(referencia|numero de referencia|referencia de pago|codigo de pago|codigo cip|cip'
                        r'|codigo de operacion|numero de operacion|numero de pago|convenio|pin de pago'
                        r'|numero de orden de pago)')
_HOLDER = re.compile(r'(titular|a nombre de|beneficiario|razon social|nombre del beneficiario|nombre del titular)')
_BANK = re.compile(r'(banco|entidad|entidad bancaria)')
_DEADLINE = re.compile(r'(vence|vence el|vencimiento|fecha de vencimiento|fecha limite|fecha limite de pago'
                       r'|paga antes de|pagar antes de|valido hasta|expira|expira el)')
_AMOUNT = re.compile(r'(monto|importe|monto a pagar|total a pagar|importe a pagar|monto a transferir'
                     r'|importe a transferir|monto a depositar|total)')
# A bank transfer or deposit, said beside the amount: what the person pays into is an account.
_TRANSFER = re.compile(r'\b(transferencia|transferi|transfiere|deposito|deposita|cbu|cvu|cci)\b')
# How far after its label a value may stand (text nodes), and how close everything stands to the amount.
_REACH = 3
_TOGETHER = 16

# (slot, label on the card). Accounts first: on a marketplace none of these is ever taken.
ACCOUNTS = (('cci', 'CCI'), ('cbu', 'CBU/CVU'), ('alias', 'Alias'), ('account', 'Cuenta'))
LABELS = (*ACCOUNTS, ('reference', 'Referencia'), ('holder', 'Titular'), ('bank', 'Banco'),
          ('deadline', 'Paga antes de'))


def _label_fold(text):
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', fold(text)).split())


def _number(text):
    value = ' '.join(text.split())
    digits = re.sub(r'[ .-]', '', value)
    return value if digits.isdigit() and 8 <= len(digits) <= 30 else None


def _alias(text):
    value = ' '.join(text.split())
    # An Argentine alias: words joined by dots ("tienda.pagos.mp"), with letters, never a number.
    return value if re.fullmatch(r'[A-Za-z0-9-]+(\.[A-Za-z0-9-]+){1,4}', value) and 6 <= len(value) <= 20 \
        and re.search(r'[A-Za-z]', value) else None


def _reference(text):
    value = ' '.join(text.split())
    return value if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 -]{1,38}[A-Za-z0-9]', value) \
        and any(c.isdigit() for c in value) else None


def _holder(text):
    value = ' '.join(text.split())
    return value if re.fullmatch(r"[^\W\d_][^\W\d_ .,&'-]*([ .,&'-]+[^\W\d_]+){0,7}\.?", value) \
        and 3 <= len(value) <= 60 else None


def _bank(text):
    value = ' '.join(text.split())
    return value if re.fullmatch(r"[^\W\d_][\w .&'-]{1,38}", value) and not any(c.isdigit() for c in value) else None


def _deadline(text):
    value = ' '.join(text.split())
    return value if 3 <= len(value) <= 40 and any(c.isdigit() for c in value) else None


def _amount(text):
    from .operate import amount_of
    # "S/ 120.00 (incluye S/ 18.31 IGV)": what is in brackets is not the amount.
    value = ' '.join(re.sub(r'\([^)]{0,40}\)', ' ', text).split())
    return amount_of(value) if re.fullmatch(r'[A-Za-z$/. ]{0,6}\d[\d.,]*\d?[A-Za-z. ]{0,6}', value) else None


_READ = {'cci': (_CCI, _number), 'cbu': (_CBU, _number), 'alias': (_ALIAS, _alias), 'account': (_ACCOUNT, _number),
         'reference': (_REFERENCE, _reference), 'holder': (_HOLDER, _holder), 'bank': (_BANK, _bank),
         'deadline': (_DEADLINE, _deadline), 'amount': (_AMOUNT, _amount)}


def _labelled(nodes, label, read):
    """[(node index, value)]: a value right after a node that is that label, or in the same node
    after "Label:". A label whose value does not read is skipped, never filled in from elsewhere."""
    found = []
    for index, node in enumerate(nodes):
        head, colon, rest = node.partition(':')
        if colon and label.fullmatch(_label_fold(head)) and rest.strip():
            value = read(rest.strip())
            if value is not None:
                found.append((index, value))
            continue
        if not label.fullmatch(_label_fold(node)):
            continue
        for offset, item in enumerate(nodes[index + 1:index + 1 + _REACH], start=1):
            if item.strip() in (':', '-', ''):
                continue
            value = read(item.strip())
            if value is not None:
                found.append((index + offset, value))
            break   # only the first thing after the label
    return found


def _digits(text):
    return re.sub(r'\D', '', str(text or ''))


def _in_the_item(value, nodes, title):
    """The value is written in the item's own words (its title, wherever the page prints it)."""
    words = [word for word in fold(title).split() if len(word) >= 4][:6]
    places = [fold(title)] + [fold(node) for node in nodes
                              if words and sum(word in fold(node) for word in words) >= min(2, len(words))]
    digits = _digits(value)
    return any((len(digits) >= 6 and digits in _digits(place)) or (len(fold(value)) >= 3 and fold(value) in place)
               for place in places)


def _one_picture(text, approved, title, marketplace):
    """(details, '') or (None, why) for one picture's visible text."""
    if text is None:
        return None, 'several'   # too long to read whole
    nodes = [str(node) for node in text if str(node).strip()]
    found = {key: _labelled(nodes, label, read) for key, (label, read) in _READ.items()}
    anchors = [index for index, value in found.pop('amount') if value == approved]
    if not anchors:
        return None, 'code'
    # The whole page, not just near the amount: a second account or code anywhere (a seller's,
    # printed above the store's own block) is never chosen between.
    for key in ('cci', 'cbu', 'alias', 'account', 'reference'):
        if len({value for _, value in found[key]}) > 1:
            return None, 'several'
    details = []
    for key, label in LABELS:
        if marketplace and key in (*dict(ACCOUNTS), 'holder', 'bank'):
            continue   # a seller writes on a marketplace's order page: no account is ever taken there
        near = {value for index, value in found[key] if any(abs(index - anchor) <= _TOGETHER for anchor in anchors)}
        if len(near) > 1:
            return None, 'several'
        if not near:
            continue
        value = near.pop()
        if _in_the_item(value, nodes, title):
            if key in (*dict(ACCOUNTS), 'reference'):
                return None, 'several'   # a seller's title carries it: never taken
            continue
        details.append((label, value))
    labels = {label for label, _ in details}
    accounts = labels & {label for _, label in ACCOUNTS}
    near_text = [fold(nodes[index]) for anchor in anchors
                 for index in range(max(0, anchor - _TOGETHER), min(len(nodes), anchor + _TOGETHER + 1))]
    if any(_TRANSFER.search(node) for node in near_text) and not accounts:
        return None, 'code'   # a transfer with no account to pay into: back to the agent to find it
    if not accounts and 'Referencia' not in labels:
        return None, 'code'
    return details, ''


def read(shots, approved, title, *, marketplace):
    """(details, '') or (None, why), why in 'code' (not shown), 'several' (doubtful), 'amount'
    (another amount: the order is not this one), 'screen' (the two pictures differ)."""
    results = [_one_picture(getattr(shot, 'text', None), approved, title, marketplace) for shot in shots]
    first = results[0]
    if any(result != first for result in results[1:]):
        return None, 'screen'
    return first
