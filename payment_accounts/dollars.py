"""Whether the person wrote this number as that many US dollars.

Used wherever a number from a chat becomes dollars (a rule, an alert's buy, a
question the assistant asks before a card). It allows two shapes only: a
number marked as dollars ("20 dólares", "US$20"), or a plain number when no
other money is named at all in what they wrote ("envía 20 a @ana"). "500 a
@ana en bolívares", "500 bolos", "R$ 20", "20k", "20 centavos" are never
dollars, and neither is the "2000" of "tengo 5000 bolívares, envíale 2000"
or the "mejor 600" after "500 bolívares": a plain number takes the money
around it. The one exception is an alert's own level ("si pasa 50 bolívares,
compra 20"). That money counts wherever they said it (`around`): in a
question, a voice note, a photo's caption, a pasted receipt, though none of
those is where an amount is read from. What it allows is still shown as
dollars before anything is signed.
"""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

_EDGE = '.,;:!?¡¿()[]{}"\'«»“”*_·-–—'
_MARKED = frozenset({'us$', '$us', 'u$s', 'u$d', 'u$', 'usd', 'usd$', 'us'})
_DOLLARS = _MARKED | frozenset({'dolar', 'dolares', 'dollar', 'dollars', 'dolaritos', 'usdt', 'usdc', 'cusd', 'verdes'})
_OTHER_DOLLARS = frozenset({'canadienses', 'canadiense', 'australianos', 'australiano', 'canadian', 'australian',
                            'hongkoneses', 'singapurenses'})
_OTHER_DOLLAR_PLACES = frozenset({'hong', 'canada', 'australia', 'singapur', 'taiwan'})
_PEOPLE = (r'(?:venezolan|colombian|mexican|argentin|chilen|peruan|bolivian|paraguay|uruguay|dominican|brasilen|'
           r'guatemaltec)[oa]s?|brasileir[oa]s?|costarricenses?|nicaraguenses?')
_PLACES = (r'venezuela|colombia|mexico|argentina|chile|peru|bolivia|paraguay|uruguay|brasil|brazil|guatemala|'
           r'mi pais')
# Other money: in play wherever it stands, unless it names a number of its own.
_MONEY = frozenset("""bolivar bolivares bolivare bolibar bolibares bolibarez volivar volivares bolivianitos euritos quetzalitos solcitos
lps bs/ b/s bolos bolo bolivas bolitos bs bss bsf bsd bs.s bs.d bs.f b.s vef pesos peso
pesitos soles euros eur reales reais brl bolivianos boliviano guaranies guarani guaranis gs pyg quetzales quetzal gtq
colones crc lempiras lempira hnl cordobas balboas cop cops mxn m.n ars clp pen uyu dop gbp cad yenes yuanes""".split())
_SIGN = re.compile(r'r\$|^s/|€|£|₲|₡|¥|^(?!us\$|u\$)[a-z]{1,3}\$')
_PHRASE = re.compile(
    rf'(?<![\w])(?:(?:en|em) (?:bob|euro|lucas|ves|real|sol|libras|bolos|mi moneda)'
    rf'|(?:moneda|moeda|plata|dinero|dinheiro|billetes) (?:de |del |do |da )?(?:local|nacional|{_PEOPLE}|{_PLACES})'
    rf'|(?:pero|mas|son|eran|sao|digo|perdon|en|em) (?:{_PEOPLE}))(?![\w])')
# Right after the number only: elsewhere these are names and everyday words (Sol, Real, "si ves").
_AFTER = _MONEY | frozenset("""sol real euro ves bol mn barras libra libras luca lucas palo palos melon melones mango mangos varo
varos conto contos pila pilas k m mm kk lks mil miles millon millones milhao milhoes thousand million cien cientos
centavo centavos cent cents centimos accion acciones acao acoes share shares unidad unidades token tokens titulo titulos
papeles sats satoshis satoshi btc bitcoins eth bnb confio bob col mx r reis mexicanos colombianos chilenos argentinos
uruguayos dominicanos""".split())
_AFTER_BRIDGE = _MONEY | frozenset({'mil', 'k', 'millon', 'millones', 'bob', 'ves', 'euro', 'lucas', 'sol', 'libras'})
_UNIT_PEOPLE = re.compile(rf'(?:{_PEOPLE})')
_PERCENT = frozenset({'%', 'porciento', 'percent'})
# "no 50", "no son 50", "no envíes 50": the denied number. Never "no, 20" nor "no máximo 20".
_DENIES = frozenset({'son', 'eran', 'seran', 'envies', 'mandes', 'compres', 'pagues', 'vendas', 'quiero'})
# What arrives, not what is sent: "20 dólares", "le llegan en bolívares".
_ARRIVES = re.compile(r'\b(lleg\w*|recib\w*|cheg\w*|receb\w*)')
_CORRECTS = re.compile(r'\b(no(?! importa)|nao|not|eran|son|perdon|digo|desculpa|mejor(?! por))\b')
_MONTHS = frozenset("""enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre
diciembre""".split())
_TOKEN = re.compile(r'(?P<pre>[^0-9]*)(?P<number>[0-9](?:[0-9.,]*[0-9])?)(?P<post>[^0-9]*)')
_EACH = re.compile(r'/(?:mes|semana|dia|quincena|month|week|ano)(?![\w])')


def _tokens(text):
    """(word, punctuation follows it) for each word, folded, with symbols and emoji gone."""
    from .payment_intents import _fold, _normalized
    text = re.sub(r'(?<![A-Za-z])VES(?![A-Za-z])', ' VEF ', _normalized(str(text or '')))   # the code, never "si ves"
    text = _EACH.sub(' ', _fold(text))
    text = re.sub(r'[+^]|(?<=[a-z][a-z])/(?=[a-z])', ' ', text)     # "bolívares/pago móvil", never "s/20"
    text = ''.join(' ' if unicodedata.category(ch) == 'So' or '\U0001F3FB' <= ch <= '\U0001F3FF' or ch == '\ufe0f'
                   else ch for ch in text)
    out = []
    for raw in text.split():
        word = raw.strip(_EDGE)
        if word:
            out.append((word, raw[-1] in ',.;:!?'))
    return out


def _numbers(word):
    from .payment_intents import _amount_values
    match = _TOKEN.fullmatch(word)
    if not match:
        return None
    try:
        return _amount_values(match.group('number'))
    except ArithmeticError:
        return set()


def _joined(text):
    return ' '.join(word for word, _punct in _tokens(text))


def other_money(text, amount=None, level=None):
    """Another currency is named in this text. With `amount`, not where it is
    the unit of some other number; with `level`, not where it is that number's."""
    words = [word for word, _punct in _tokens(text)]
    if _PHRASE.search(' '.join(words)):
        return True
    for index, word in enumerate(words):
        match = _TOKEN.fullmatch(word)
        glued = bool(match) and any(mark in _MONEY or _SIGN.search(mark) for mark in match.group('pre', 'post') if mark)
        if not (glued or word in _MONEY or _SIGN.search(word)):
            continue
        back = index - 2 if index >= 2 and words[index - 1] == 'de' else index - 1
        near = ([index] if glued else []) + [at for at in (back, index + 1) if 0 <= at < len(words) and not glued]
        values = next((found for found in (_numbers(words[at]) for at in near) if found), None)
        if values and ((amount is not None and amount not in values) or (level is not None and level in values)):
            continue                    # that number's unit
        return True
    return False


def _how(text, amount):
    """How this text writes the amount: 'dollars', 'plain', 'other', or None when it doesn't."""
    tokens, seen = _tokens(text), set()
    words = [word for word, _punct in tokens]
    for index, word in enumerate(words):
        match = _TOKEN.fullmatch(word)
        if not match:
            continue
        pre, _number, post = match.group('pre', 'number', 'post')
        if '@' in pre or '/' in post or sum(ch.isalpha() for ch in pre) > 3:
            continue                    # part of a name or a handle
        if amount not in (_numbers(word) or ()):
            continue
        before, after = words[max(0, index - 3):index], words[index + 1:index + 4]
        if post in _PERCENT or after[:1] and after[0] in _PERCENT or after[:2] == ['por', 'ciento']:
            continue                    # a share of something, not an amount
        if before[-1:] and before[-1] in ('no', 'nao', 'not') and not tokens[index - 1][1]:
            continue                    # "no 50"
        if (len(before) >= 2 and before[-2] in ('no', 'nao', 'not') and not tokens[index - 2][1]
                and before[-1] in _DENIES) or before[-2:] in (['vez', 'de'], ['lugar', 'de']):
            continue                    # "no son 50", "en vez de 50"
        if after[:1] == ['de'] and after[1:2] and after[1] in _MONTHS:
            continue                    # a date
        if (index and not pre and not tokens[index - 1][1] and re.fullmatch(r'[0-9]{3}', word)
                and re.fullmatch(r'[$]?[0-9]{1,3}', words[index - 1])):
            seen.add('other')           # "2 500": half of a number
            continue
        glued = {mark for mark in (pre, post) if mark and mark != '$'}
        if glued - _DOLLARS:
            seen.add('other')           # "20k", "r$20", "20bs": a unit we don't read is never dollars
            continue
        last, following = (before[-1] if before else ''), list(after)
        if last in _MONEY or last in ('r$', 's/', '€', '£', '₲', '%', 'bob') or (
                last.endswith('$') and last not in _MARKED and last != '$'):
            seen.add('other')
            continue
        bridged = following[:1] in (['de'], ['en'], ['em'], ['in'])
        if bridged:
            following = following[1:]
            if following[:1] in (['los'], ['las']):
                following = following[1:]
        unit = following[0] if following else ''
        if unit in (_AFTER_BRIDGE if bridged else _AFTER) or _UNIT_PEOPLE.fullmatch(unit) and not bridged:
            seen.add('other')
            continue
        if re.fullmatch(r'[0-9]{3}', unit) and not bridged:
            seen.add('other')           # "20 000": half of a number
            continue
        if unit in _DOLLARS and following[1:2] and (
                following[1] in _OTHER_DOLLARS or following[1] == 'de' and following[2:3]
                and following[2] in _OTHER_DOLLAR_PLACES):
            seen.add('other')
            continue
        seen.add('dollars' if glued or last in _MARKED or unit in _DOLLARS else 'plain')
    return next((how for how in ('other', 'dollars', 'plain') if how in seen), None)


def _without_denied(text):
    """The text without the money they rule out: "no 20 bolívares", "no en pesos". Never "no, bolívares"."""
    tokens, out, index = _tokens(text), [], 0
    while index < len(tokens):
        word, punct = tokens[index]
        if word in ('no', 'nao', 'not') and not punct:
            end = index + 1
            while end < len(tokens) and end - index <= 3 and not tokens[end][1] and (
                    tokens[end][0] in ('en', 'em', 'de', 'son') or _numbers(tokens[end][0])):
                end += 1
            if end < len(tokens) and tokens[end][0] in _MONEY:
                index = end + 1
                continue
        out.append(word + (',' if punct else ''))
        index += 1
    return ' '.join(out)


def _after(text, amount):
    """What they wrote after this amount, in the same message."""
    raw = str(text or '').split()
    for index, part in enumerate(raw):
        words = _tokens(part)
        if any(amount in (_numbers(word) or ()) for word, _punct in words):
            return ' '.join(raw[index + 1:])
    return ''


def said_dollars(texts, amount, *, level=None, around=()):
    """The person wrote `amount` as US dollars. `texts`: their requests, newest first, where the amount is read.
    `around`: everything they said meanwhile, where other money may be named. `level`: an alert's own."""
    try:
        amount = Decimal(str(amount))
        level = Decimal(str(level)) if level not in (None, '') else None
    except (InvalidOperation, TypeError, ValueError):
        return False
    if level == amount:
        level = None
    texts = [str(text or '') for text in texts]
    for index, text in enumerate(texts):
        how = _how(text, amount)
        if how is None:
            continue
        if how == 'other':
            return False
        if how == 'plain':
            return not any(other_money(any_text, level=level) for any_text in [*texts, *around])
        tail = _without_denied(_after(text, amount))
        if _CORRECTS.search(_joined(tail)) and other_money(tail, level=level):
            return False                # "500 dólares, perdón, bolívares"
        # Marked as dollars: a newer message takes that back when it corrects to other money, or names it
        # otherwise than as what arrives or as another number's unit.
        for newer in texts[:index]:
            said = _joined(newer)
            if _CORRECTS.search(said) and other_money(newer, level=level):
                return False
            if other_money(newer, amount, level) and not _ARRIVES.search(said):
                return False
        return True
    return False
