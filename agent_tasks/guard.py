"""What the agent may do. Code, not prompt: a short list of what is allowed.

A person's store account can hold a saved card, so the agent never orders,
never pays and never works inside a checkout. The person does the checkout
and presses the store's final button themselves, in the live view.

Until then the agent has three verbs:

  - search: words typed into a search box, sent only as a search (GET);
  - follow a link: its address is opened by GET, whole, and only when no
    part of it acts (path, any query name or value, an address inside it).
    The link itself is never clicked;
  - add to cart: a submit button of a form that posts to a cart's own address.
    The form is sent as a browser sends it, never clicked, so no script of the
    page or of a seller's markup runs on it.

Anything else is refused, whatever the page or the model says. Once the
checkout is handed over there is no agent at all (runner.py).

Every function here is pure: page facts in, a decision out.
"""
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from . import sites

MAX_SEARCH_CHARS = 100


def fold(text):
    text = unicodedata.normalize('NFKD', str(text or '').casefold())
    text = ''.join(' ' if unicodedata.category(ch) in ('Zs', 'Zl', 'Zp', 'Cc') else ch
                   for ch in text if not unicodedata.combining(ch) and unicodedata.category(ch) != 'Cf')
    return ' '.join(text.split())


def clean(text, limit):
    """Third-party text made safe to show: one line, no invisible characters."""
    text = ''.join(' ' if unicodedata.category(ch) in ('Cc', 'Cf', 'Co', 'Cn', 'Cs', 'Zl', 'Zp') else ch
                   for ch in str(text or ''))
    return ' '.join(text.split())[:limit]


def unquoted(text):
    """Percent-decoding until nothing changes, so "%2570ay" is still "pay"."""
    for _ in range(4):
        plain = unquote(text)
        if plain == text:
            break
        text = plain
    return text


def _parts(element):
    """The distinct wordings of a control: its text, aria label, title..."""
    parts = (fold(part).strip(' .!>:+→›') for part in str(element.get('label') or '').split('|'))
    return [part for part in parts if part]


# The buttons the agent may press. A whole label, pt / es / en.
_ADD_TO_CART = re.compile(
    r'(adicionar|adicione|agregar|anadir|add|colocar|incluir|por) '
    r'((ao|a|no|na|al|a la|en el|to|in|ao meu|no meu|to your|ao seu) )?'
    r'(carrinho|carrinho de compras|carrito|carrito de compras|sacola|cesta|cart|shopping cart|bag|basket)')

# A whole segment: "cartao" is a card, not a cart.
_CART = re.compile(r'((add(to)?|adicionar(ao|no)?|agregar(al)?|gz)?'
                   r'(cart|carts|carrinho|carrito|sacola|cesta|basket|bag))(add|adicionar|agregar|items?)?'
                   r'|addto(cart|bag|basket)|handlebuybox')

# An address that acts or is a checkout. Whole path segments, compared without
# separators: "/checkout" and "/placeOrderNow" act; a product called
# "fone-noise-cancel" or "maquina-de-pagamento" does not.
_CHECKOUT_SEGMENT = re.compile(
    r'checkouts?(v?\d+|steps?|onepage)?|onepage(checkout)?|paymentstep|carrinhoidentificacao|pagos?|onestepcheckout|expresscheckout|buyingflow|buy|payments?'
    r'|pagamentos?|pagar|purchase|finalizar(compra|pedido)?|fechamento|fecharpedido|placeorder|revisarpedido'
    r'|confirmar(pedido|compra)?|confirmacao|confirmation|orderreview')
_ACT_SEGMENT = re.compile(
    r'buynow|buyitnow|fastorder|realizarpedido|pedidocriar|comprarahora|oneclick(buy)?|1click(buy)?|expressbuy|instantbuy|pay|paynow|processpayment'
    r'|placeorder(now)?|placeyourorder\d*|confirm(order|purchase|payment|buy|ado)?|confirmapagamento|confirma'
    r'|finalize(order|purchase)?|finalise|submitorder|createorder|cancel(ar|led|order|arpedido)?|comprar(agora)?'
    r'|subscribe|subscriptions?|membersignup|signup|register|cadastro|assinar|assinaturas?|logout|signout'
    r'|sair|delete|remove|excluir|eliminar|withdraw|cancellation|clearcart|repetir|reactivate|ativar|termsaccept'
    r'|pedidocriar|carrinhoidentificacao')
_ACT_PREFIX = re.compile(
    r'(setdefault|deletepayment|addpayment|changepayment|cancelorder|cancelsubscription|placeorder|confirmorder'
    r'|confirmpurchase|changesubscription|unsubscribe|aceitartermos|finalizarcompra|finalizarpedido)')
_ACT_KEYS = re.compile(r'action|act|step|op|do|cmd|mode|event|task')
# A redirect that carries one of these is a signed action, not a page.
_SIGNED = re.compile(r'(wp)?nonce|csrf(token)?|xsrf(token)?|formkey|authenticitytoken')
# Ordinary words that act only beside what they act on: "?sort=default" is a
# view, "/address/7/default" sets one.
_ACT_WITH = (
    (re.compile(r'default|principal|primary|padrao'),
     re.compile(r'address|addresses|endereco|enderecos|paymentmethods?|cards?|cartao|cartoes|tarjetas?')),
    (re.compile(r'clear|empty|esvaziar'), re.compile(r'cart|carrinho|carrito|basket|bag')),
    (re.compile(r'create|criar'), re.compile(r'account|accounts|customer|conta|cuenta|order|orders|pedido|pedidos')),
    (re.compile(r'accept|aceitar|aceite'),
     re.compile(r'terms|termos|termosdeuso|terminos|policy|politica|consent|cookies?|oferta|offer')),
    (re.compile(r'identificacao'), re.compile(r'carrinho')),
)
# What someone searched is words, unless it is written as a path.
_SEARCH_KEYS = frozenset('q k s query search keywords keyword busca term asword'.split())
_CHECKOUT_HOST = re.compile(r'(checkout|seguro|payment|payments|pagamento|pay)\.')
# A link whose words are an act, not a place.
_ACT_WORDS = re.compile(
    r'^(comprar|compre (agora|ja|com)|compra (agora|ahora)|buy|pagar|pay|pague agora|finalizar|finalize|confirm\w*'
    r'|concluir|checkout|fechar (pedido|compra)|assinar|assine|subscribe|reservar|pedir|fazer (o |meu |seu )?pedido'
    r'|aceitar|aceito|aceptar|acepto|accept|concordo|ativar|excluir|cancelar|doar|criar conta|cadastre-se|alugar)\b'
    r'|\b(comprar (agora|ahora|ja|com|con)|buy (now|with)|pagar (com|con|agora)|pay (now|with)'
    r'|1[ -]?(clique|clic|click)|teste gratis|free trial|(entrar|continuar|sign in) (com|con|with) '
    r'(o |a )?(google|apple|facebook))\b')

# A button that only a cart's end or a checkout has. Free page text is no
# signal: a seller can write "revise seu pedido".
_FINAL_BUTTON = re.compile(
    r'(confirmar|fazer|realizar|concluir|efetuar|enviar|place|confirm|hacer|submit) '
    r'((a|o|la|el|seu|meu|sua|minha|tu|mi|your|the) )?(compra|pedido|order|purchase|pagamento|pago)'
    r'|confirmar e pagar|place order|pay now|pagar agora|pagar ahora|pagar pedido|pagar com pix|pagar con qr|pagar r\$ ?[\d.,]+|pagar bs\.? ?[\d.,]+'
    # Not "Finalizar compra": a cart's way into the checkout, not its last button.
    r'|pagar \$ ?[\d.,]+|pagar con (spei|transferencia)')
# Wider than _FINAL_BUTTON (which decides what a checkout is): anything that reads as the last press.
_FINAL_WORDS = re.compile(r'\b(realiza(r)? (tu |el |seu |o )?pedido|comprar ahora|comprar agora|buy now|'
                          r'confirmar (compra|pedido|pago)|place (your )?order)\b')
_LOGIN_URL = re.compile(
    r'(/login\b|/signin\b|/sign-in\b|/registration\b|/identification\b|/lgz/|/authentication\b|/account-verification\b'
    # Amazon's sign-in and its verification steps.
    r'|/ap/(signin|cvf|mfa)\b)',
    re.I)
_BLOCKED_PAGE = re.compile(
    r'\b(acesso negado|access denied|acceso denegado|unusual traffic|trafego incomum|you have been blocked'
    r'|request blocked|pardon our interruption)\b')


def _compact(text):
    return re.sub(r'[^a-z0-9]', '', re.sub(r'\.(html?|php|aspx?|jsp|do|action|json|xml)$', '', text.lower()))


def _segments(parts, *, fragment=True):
    path = unquoted(f'{parts.path}/{parts.fragment.split("?")[0]}' if fragment else parts.path)
    return [_compact(segment) for segment in re.split(r'[/;]', path) if segment]


# ── the agent's own checkout (operate.py) ──
# What a control says decides whether a model may press it. On a checkout page
# only what is on this list: any other button there may be the one that buys.
_MAY_PRESS = re.compile(
    r'\b(continuar|continue|siguiente|next|seguir|prosseguir|avancar|cambiar|change|alterar|trocar|editar|edit|elegir'
    r'|escolher|seleccionar|selecionar|select|usar|use|enviar a|entregar|deliver|ver|mostrar|show|otro|otra|outro'
    r'|other|no,? gracias|nao,? obrigado|no thanks|omitir|pular|skip|cerrar|fechar|close|eliminar|remover|quitar'
    r'|remove|carrito|carrinho|cart|cesta|proceder|proceed|aceptar|aceitar|accept|entendido|ok)\b')
# Outside a checkout page, the ways into one.
_ENTER_CHECKOUT = re.compile(
    r'\b(comprar ahora|comprar agora|buy now|finalizar compra|proceder al pago|proceed to checkout|ir a pagar'
    r'|ir al pago|ir para o pagamento|checkout|continuar( compra)?|carrito|carrinho|cart|cesta)\b')
# Never, in any phase: what would change the person's account or buy something else.
_NEVER = re.compile(
    r'\b(cancelar (el |o )?(pedido|compra|orden)|cancel (the )?order|volver a comprar|comprar de nuevo'
    r'|comprar novamente|buy (it )?again|reorder|eliminar (la |mi )?(direccion|cuenta|tarjeta)|excluir (endereco|conta)'
    r'|delete (address|account)|cerrar sesion|sair|log ?out|sign ?out|prime|meli\+|suscri\w*|subscri\w*|assin\w*'
    r'|gift ?card|tarjeta de regalo|vale[- ]presente|1[- ]clic\w*)\b')
_ACCOUNT_PATH = re.compile(r'/(logout|signout|sign-out|cancel\w*|delete\w*|unsubscribe|subscri\w*|prime|membership'
                           r'|gift-?cards?)(/|$)')
# A button that reads as the last one of a checkout.
_FINAL_LOOK = re.compile(r'\b(confirmar|confirma|realizar|realiza|hacer|haz|fazer|finalizar|finaliza|completar|completa'
                         r'|concluir|place|submit|complete|pagar|paga|pay|comprar|compra|buy|gerar|generar)\b')
_CONFIRMED = re.compile(
    r'pedido (realizado|confirmado|recibido|registrado)|gracias por (tu|su) (compra|pedido)|tu pedido (fue|ha sido)'
    r'|order (placed|confirmed|received)|thank you.{0,20}order|pedido (efetuado|feito|recebido)'
    r'|obrigado pela (sua )?compra|compra (realizada|confirmada)')
# A whole path segment that names an order's own page. Never a substring: a seller names
# a product "Compra Fácil" and its slug would read as an order.
_ORDER_SEGMENT = re.compile(
    r'(your)?orders?(details?|status|summary|confirmation|confirmed|completed?|history|view)?|ordenes|pedidos?'
    r'(detalhes?|detalle|realizado|confirmado)?|minhascompras|miscompras|compras?|purchases?|pagamentos?|payments?'
    r'|pagos?|thankyou|thanks|gracias|obrigado|congrats|confirmacao|confirmation|orderconfirmation')
# A product's page, whatever else its path says: a seller writes its title, its pictures and its text.
_PRODUCT_SEGMENT = re.compile(r'dp|product|products|produto|produtos|producto|productos|p|item|itm|ml[a-z]\d+[a-z0-9]*')
_PRODUCT_WORD = re.compile(r'^(producto|produto|product|articulo|item|categoria|category|categorias|catalogo)')
_PRODUCT_HOST = re.compile(r'(produto|articulo|produtos|articulos)\.')
# A seller's, a brand's or a search's page: they name themselves what they like.
_SELLER_HOST = re.compile(r'(lista|listado|perfil|perfiles|eshops?)\.')
_SELLER_SEGMENT = re.compile(r'perfil|profile|loja|lojas|tienda|tiendas|stores?|shops?|seller|sellers|vendedor'
                             r'|vendedores|sp|s|brand|marca|search|busca|buscar|b|l|listado|lista|pagina|page|pages')
# The stores we know, by their own order and checkout paths.
_KNOWN_ORDER_PATHS = (
    (re.compile(r'(^|\.)amazon\.com(\.[a-z]{2})?$|(^|\.)amazon\.[a-z]{2}$'),
     re.compile(r'/(gp/buy/|gp/css/order|gp/your-account/order|your-orders/|checkout/|cpe/yourpayments/)')),
    (re.compile(r'(^|\.)mercadoli(vre|bre)\.(com(\.[a-z]{2})?|[a-z]{2})$'),
     re.compile(r'/(gz/checkout/|checkout/|compras?/\d|my_purchases/|my-purchases/|purchases/\d)')),
)
_CARD = re.compile(r'\b(tarjeta|cartao|card|credito|debito|credit|debit|visa|mastercard|amex|american express'
                   r'|terminada en|final \d{4}|meses sin intereses|parcel\w*|cuotas)\b|\*{2,} ?\d{4}')


def may_press(element, *, on_checkout):
    """A control a checkout model may click: a choice, a link, or a button whose words are on the list."""
    parts = _parts(element)
    if any(_NEVER.search(part) for part in parts):
        return False
    # A label for the final button, or a tab or option that holds it, presses that button.
    # A radio or checkbox submits nothing: "Pagar con SPEI" there is the method, chosen.
    tick = (element.get('tag') == 'input' and element.get('type') in ('radio', 'checkbox')) \
        or element.get('role') in ('radio', 'checkbox')
    if not tick and any(_FINAL_BUTTON.fullmatch(part) or _FINAL_WORDS.search(part) for part in parts):
        return False
    if element.get('tag') in ('label', 'select') or element.get('role') in ('radio', 'checkbox', 'option', 'tab') \
            or (element.get('tag') == 'input' and element.get('type') in ('radio', 'checkbox')):
        return True
    if element.get('tag') == 'a':
        # An anchor dressed as the final button is that button, whatever its tag.
        if any(_FINAL_LOOK.search(part) or _FINAL_BUTTON.fullmatch(part) or _FINAL_WORDS.search(part)
               for part in parts):
            return False
        return not _ACCOUNT_PATH.search(urlsplit(element.get('href') or '').path.lower())
    if not parts:
        return False
    allowed = _MAY_PRESS if on_checkout else _ENTER_CHECKOUT
    if not on_checkout and any(_FINAL_BUTTON.fullmatch(p) or _FINAL_WORDS.search(p) for p in parts):
        return False   # a final button on a page not recognised as a checkout is still a final button
    return all(allowed.search(part) for part in parts) and not (on_checkout and any(_FINAL_LOOK.search(p) for p in parts))


def final_looking(element):
    """A control that could be the one that places the order (named, never pressed, by a model)."""
    return (element.get('tag') in ('button', 'a') or element.get('role') == 'button'
            or (element.get('tag') == 'input' and element.get('type') in ('button', 'submit'))) \
        and any(_FINAL_LOOK.search(part) for part in _parts(element)) \
        and not any(_NEVER.search(part) for part in _parts(element))


def account_address(url):
    """An address that acts on the person's account: never opened, in any phase."""
    return bool(_ACCOUNT_PATH.search(urlsplit(url or '').path.lower()))


def order_placed(page):
    return bool(_CONFIRMED.search(fold(page.text[:20000])))


def order_address(url):
    """An order's or a checkout's own page: where its payment data may be read."""
    parts = urlsplit(url or '')
    host = (parts.hostname or '').lower()
    path = parts.path.lower()
    # The stores we know: their own order and checkout paths, nothing else (a seller names a
    # profile, a brand store or a search "pagamentos" too).
    for known, allowed in _KNOWN_ORDER_PATHS:
        if known.search(host):
            return bool(allowed.match(path)) and not _SELLER_HOST.match(host)
    segments = _segments(parts, fragment=False)
    # A product's, a seller's, a brand's or a search's page, whatever else its address says
    # ("/producto/checkout/1", "/@vendedor/pedidos"): a seller picks those words.
    if _PRODUCT_HOST.match(host) or _SELLER_HOST.match(host) \
            or any(_SELLER_SEGMENT.fullmatch(segment) or _PRODUCT_SEGMENT.fullmatch(segment)
                   or _PRODUCT_WORD.search(segment) for segment in segments) \
            or re.search(r'/(@|~|u/)', path):
        return False
    # The fragment is never read here: a page's own anchor is anything its writer wants.
    if checkout_address(urlunsplit(parts._replace(fragment=''))):
        return True
    # Elsewhere an order's word AND an order's number: "/pedido/123", never "/loja/compras".
    return any(_ORDER_SEGMENT.fullmatch(segment) for segment in segments) \
        and any(re.search(r'\d', segment) for segment in segments)


def login_address(url):
    return bool(_LOGIN_URL.search(urlsplit(url or '').path))


def card_words(text):
    return bool(_CARD.search(fold(text)))


def final_button(element):
    """A control whose words place an order or pay it: never pressed by a model."""
    return any(_FINAL_BUTTON.fullmatch(part) or _FINAL_WORDS.search(part) for part in _parts(element))


def checkout_address(url):
    parts = urlsplit(url)
    return bool(_CHECKOUT_HOST.match((parts.hostname or '').lower())
                or any(_CHECKOUT_SEGMENT.fullmatch(segment) for segment in _segments(parts)))


def is_checkout(page):
    """Where the agent stops acting and the person takes over. A button alone
    counts only on screen: a closed cart drawer is not a checkout, and no home
    page (of any language) is one."""
    parts = urlsplit(page.url)
    if checkout_address(page.url):
        return True
    for name, value in parse_qsl(parts.query):
        if _compact(name) in ('route', 'r', 'controller') and any(
                _CHECKOUT_SEGMENT.fullmatch(_compact(piece)) for piece in unquoted(value).split('/')):
            return True  # "?route=checkout/checkout"; "?redirect=/checkout" is only a way back
    if re.fullmatch(r'(/[a-z]{2}(-[a-z]{2})?)?/?', parts.path) and not parts.fragment:
        return False
    return any(_FINAL_BUTTON.fullmatch(part)
               for element in page.elements
               if element.get('on_screen', True) and (element.get('tag') == 'button' or element.get('type') == 'submit'
                                                      or element.get('role') == 'button')
               for part in _parts(element))


def _acting(pieces):
    if any(_ACT_SEGMENT.fullmatch(piece) or _ACT_PREFIX.match(piece) for piece in pieces):
        return True
    return any(word.fullmatch(piece) and any(beside.fullmatch(other) for other in pieces)
               for word, beside in _ACT_WITH for piece in pieces)


def acts(url, depth=0):
    """Some part of this address does something. Every value is looked at,
    whatever its name and however long, as it is written and as a router
    reads it (OpenCart drops what is not a letter, a digit or a slash, so
    "cod/conf&irm" is "cod/confirm"), and an address inside it as well.
    What cannot be read acts."""
    try:
        parts = urlsplit(url)
        if checkout_address(url) or _acting(_segments(parts)):
            return True
        pairs = parse_qsl(f'{parts.query}&{parts.fragment.partition("?")[2]}', keep_blank_values=True)
        for name, sent in pairs:
            name, value = _compact(unquoted(name)), unquoted(sent).strip()
            if _SIGNED.fullmatch(name) or _ACT_PREFIX.match(name) or _ACT_SEGMENT.fullmatch(name):
                return True
            if '://' in value and (depth >= 2 or acts(value, depth + 1)):
                return True
            if name in _SEARCH_KEYS and '/' not in value:
                continue
            as_written = [_compact(piece) for piece in re.split(r'[/?&=;]', value) if piece]
            # Strip first, then lower ("İ" and the Kelvin sign lower into
            # letters), and both as sent (a router decodes once) and as decoded.
            routed = ([piece for piece in re.sub(r'[^A-Za-z0-9/]', '', form).lower().split('/') if piece]
                      for form in (sent, value))
            for pieces in (as_written, *routed):
                if _acting(pieces):
                    return True
                if '://' not in value and ('/' in value or _ACT_KEYS.fullmatch(name)) and any(
                        _CHECKOUT_SEGMENT.fullmatch(piece) for piece in pieces):
                    return True
        return False
    except ValueError:
        return True


def hop_allowed(url, method, site, *, only_get=False):
    """Every document the store's browser asks for while the agent acts: the
    first address and each redirect after it."""
    return sites.within(url, site) and not acts(url) and (method == 'GET' or not only_get)


def sent_to(method, url, action=''):
    """While an act is being sent, whatever sends it (a form, or a script the
    page hung on the button): reading what does not act, and the one address
    judged. A script's GET can act just as a link's can."""
    if method in ('GET', 'HEAD', 'OPTIONS'):
        return not acts(url)
    return bool(action) and url.split('#')[0] == action.split('#')[0]


def person_needed(page):
    """Why this page is the person's to handle, or ''."""
    if page.captcha:
        return 'captcha'
    if page.secret or _LOGIN_URL.search(urlsplit(page.url).path):
        return 'login'
    return ''


def blocked(page):
    """The store refused us. The task stops: no retry, no way around it."""
    return len(page.text) < 1500 and bool(_BLOCKED_PAGE.search(fold(page.text[:1500])))


def address_refusal(url, site):
    """Why the agent may not send a request to this address, or ''."""
    if not sites.within(url, site):
        return 'outside_store'
    return 'acts' if acts(url) else ''


def link_refusal(element, site, page=None):
    """'' to open this link's address by GET."""
    if element.get('disabled'):
        return 'disabled'
    if element.get('tag') != 'a' or not element.get('href'):
        return 'not_a_link'
    refused = address_refusal(element['href'], site)
    if refused:
        return refused
    if page is not None and element['href'].split('#')[0] == page.url.split('#')[0]:
        return 'same_page'  # a script's button dressed as a link: opening it does nothing
    return 'acts' if any(_ACT_WORDS.search(part) for part in _parts(element)) else ''


def cart_address(url):
    """A cart's own endpoint: the path ends in the cart (or in adding to it),
    and no script file or fragment stands in for that."""
    parts = urlsplit(url)
    if parts.query:
        return False
    raw = [piece for piece in unquoted(parts.path).split('/') if piece]
    if not raw or any(re.search(r'\.(php|aspx?|jsp|cgi|do)$', piece, re.I) for piece in raw[:-1]):
        return False
    segments = [_compact(piece) for piece in raw]
    if _CART.fullmatch(segments[-1]):
        return True
    return len(segments) > 1 and bool(_CART.fullmatch(segments[-2])
                                      and (re.fullmatch(r'add|adicionar|agregar|items?|v\d+', segments[-1])
                                           or re.match(r'ref[=-]', raw[-1], re.I)))


def press_refusal(element, page, site):
    """'' to press this button: only a submit of add-to-cart to a cart."""
    if is_checkout(page):
        return 'checkout'
    if element.get('disabled'):
        return 'disabled'
    if element.get('cut'):
        return 'unreadable'
    button = (element.get('tag') == 'button'
              or (element.get('tag') == 'input' and element.get('type') in ('button', 'submit'))
              or (element.get('role') == 'button' and element.get('tag') in ('div', 'span')))
    if not button:
        return 'not_a_button'
    if element.get('nested'):
        return 'inside_another_control'  # its click would be that control's click too
    parts = _parts(element)
    if not parts or not all(_ADD_TO_CART.fullmatch(part) for part in parts):
        return 'not_allowed'
    if element.get('new_window'):
        return 'new_window'  # a tab nobody is watching
    # Only a submit to a cart, with no instructions of its own: a seller's
    # description can hold a button or a form, and a store's generic script
    # does what a button's data-url says. Anything else is the person's tap.
    if element.get('scripted'):
        return 'scripted'
    if not element.get('action'):
        return 'not_a_cart'
    refused = address_refusal(element['action'], site)
    if refused:
        return refused
    if not cart_address(element['action']):
        return 'not_a_cart'
    for word in re.split(r'[.\s:]+', element.get('name') or ''):
        word = _compact(word)
        if _ACT_SEGMENT.fullmatch(word) or _CHECKOUT_SEGMENT.fullmatch(word):
            return 'acts'
    return ''


def search_refusal(element, text, page, site, goal):
    """'' to search these words in this box."""
    if is_checkout(page):
        return 'checkout'
    if element.get('disabled') or element.get('tag') != 'input' or not element.get('search'):
        return 'not_a_search'
    if element.get('type') not in ('', 'text', 'search') or element.get('autocomplete', '').split()[-1:] in (
            ['username'], ['email'], ['current-password'], ['new-password'], ['one-time-code'], ['cc-number']):
        return 'not_a_search'
    if element.get('new_window'):
        return 'new_window'
    if not element.get('action') and element.get('scripted'):
        return 'scripted'  # with no form only the page's script searches, and this one says what to send
    if element.get('action'):
        if element.get('method') != 'get' or element.get('secret_form'):
            return 'not_a_search'  # a search is a GET
        refused = address_refusal(element['action'], site)
        if refused:
            return refused
    value = str(text or '').strip()
    if not value or len(value) > MAX_SEARCH_CHARS or any(unicodedata.category(ch) == 'Cc' for ch in value):
        return 'bad_text'
    if '@' in value or '://' in value:
        return 'not_said'
    said = set(re.findall(r'\d+', re.sub(r'(?<=\d)[.-](?=\d)', '', fold(goal))))
    for run in re.findall(r'\d[\d .-]*', value):
        groups = re.findall(r'\d+', re.sub(r'(?<=\d)[.-](?=\d)', '', run))
        joined = ''.join(groups)
        if len(joined) >= 5 and joined not in said and not all(group in said for group in groups):
            return 'not_said'
    return ''
