"""Which store a task may start in.

Not per-store code: a thin list of names (sites.KNOWN), for one reason. The
person types their password in the live view, so the address must not be the
model's invention, nor a copy of a store's name. A task starts at a
well-known store or at an address the person wrote themselves.
"""
import re
from difflib import SequenceMatcher

from . import guard, sites

KNOWN = sites.KNOWN
# What reads as an address, not as a typo like "azul.grande".
_ADDRESS = re.compile(r'^(https://|www\.)|\.(br|com|net|store|shop)(/|$)')
_LOOK_ALIKE = str.maketrans('01', 'ol')
# Words that only happen to hold a store's name.
_OWN_WORDS = ('amazonia', 'amazonica', 'amazonas', 'brenner', 'centauros', 'abuser', 'mainbuser')


def named(texts):
    """The known stores the person named."""
    said = ' . '.join(guard.fold(text) for text in texts)
    return {site for site, names in KNOWN.items()
            if any(re.search(rf'(?<!\w){re.escape(name)}(?!\w)', said) for name in names)}


def written(texts):
    """The addresses the person wrote themselves, letter for letter: folding
    "açaí" to "acai" would be another shop's domain."""
    found = set()
    for text in texts:
        for word in str(text or '').lower().split():
            word = word.strip('.,;:!?()"\'<>')
            if '@' in word or not _ADDRESS.search(word):
                continue
            store = sites.store(word)
            if store and not imitates(store):
                found.add(store)
    return found


def imitates(site):
    """An address that borrows or nearly spells a known store's name: where a
    pasted scam would have the person type that store's password."""
    if site in KNOWN:
        return False
    names = {name.replace(' ', '') for aliases in KNOWN.values() for name in aliases} | {'mercadopago'}

    def plain(text):
        return re.sub(r'[^a-z0-9]', '', text).translate(_LOOK_ALIKE).replace('rn', 'm').replace('vv', 'w')

    labels = site.split('.')[:-1]
    squashed = [plain(''.join(labels)), *(plain(label) for label in labels)]
    tokens = {plain(word) for label in labels for word in label.split('-')}
    for name in names:
        if name in tokens:
            return True
        if len(name) >= 8 and any(name in text for text in squashed):
            return True
        if len(name) >= 5:
            for text in squashed:
                for word in _OWN_WORDS:
                    text = text.replace(word, '-')
                if name in text:
                    return True
        if len(name) < 5:
            continue
        # A near spelling. Short names need to be nearer: "petfood" is not "ifood".
        bar = 0.88 if len(name) >= 8 else 0.92
        for text in {*squashed, *tokens}:
            if text[:1] == name[:1] and len(text) <= len(name) + 1 and SequenceMatcher(None, name, text).ratio() >= bar:
                return True
    return False


_COUNTRY_WORDS = {'MX': ('mexico', 'mexicana', 'mexicano', 'cdmx'), 'BR': ('brasil', 'brazil', 'brasileira'),
                  'BO': ('bolivia', 'boliviana', 'boliviano')}


def said_country(texts):
    """The one country the person's words name ("de México"), or ''."""
    said = ' . '.join(guard.fold(text) for text in texts)
    found = {country for country, words in _COUNTRY_WORDS.items()
             if any(re.search(rf'(?<!\w){word}(?!\w)', said) for word in words)}
    return found.pop() if len(found) == 1 else ''


def choose(pointer, texts, country=None):
    """The store for a task: the model's pointer only counts when it is the
    store the person named, or a known one when they named none. A name
    that is a store in several countries ("Mercado Libre") is the one in the
    person's own country."""
    from . import countries
    theirs = named(texts) | written(texts)
    if len(theirs) > 1 and country:
        own = {site for site in theirs if countries.country_of(site) == country}
        theirs = own or theirs
    store = sites.store(pointer) if pointer else None
    if theirs:
        if store in theirs:
            return store
        return next(iter(theirs)) if len(theirs) == 1 else None
    if store in KNOWN and country and countries.country_of(store) != country:
        return None
    return store if store in KNOWN else None
