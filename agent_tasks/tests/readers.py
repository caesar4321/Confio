"""Stand-ins for the models, for tests: what a careful reader would say, worked out from words.

Production decides none of this by words any more (agent.judge and agent.review are models; operate.py
checks facts). These keep the unit tests deterministic and offline; the models' real judgment is tested
on recorded pages against the live models (scripts/ops/eval_agent_readers.py).
"""
import re

from agent_tasks import countries, guard
from agent_tasks.guard import _GRAND_TOTAL, _METHOD_LABEL
from agent_tasks.operate import amount_of

# Where a checkout shows the way to pay it chose (Amazon's review page shows it as text).
# The country's own way to pay, as a checkout names it.
# Where the person pays it themselves: a way to pay with no card and no account of theirs at a
# wallet the agent would have to sign in to (never PSE, PayPal, Mercado Pago, instalments).
MANUAL_WORDS = re.compile(r'\b(transferencia|transferencia bancaria|deposito|efectivo|oxxo|pago movil|pagomovil'
                          r'|pagoefectivo|efecty|baloto|rapipago|pago facil|pagofacil|servipag|abitab|redpagos'
                          r'|qr|spei|pix|sinpe)\b')
# Completed inside the checkout (a bank login, an app approval, a wallet): never "paid later", even
# when the label also says "transferencia" or "QR".
MANUAL_NEVER = re.compile(r'\b(pse|mercado ?pago|paypal|khipu|webpay|yape|plin|niubiz|tigo money|bancard|nequi'
                          r'|daviplata|tarjeta|credito|debito|cuotas|mach|onepay|modo|uala|cuenta dni|billetera'
                          r'|bancolombia|boton de pago|boton bancolombia|transferencia con|pago con qr|wallet)\b')
# A cash or voucher network paid later at an agent or from any bank: itself even when its label lists the
# apps that can pay it ("PagoEfectivo (banca móvil, Yape, Plin, agentes)").
MANUAL_VOUCHER = re.compile(r'\b(pagoefectivo|rapipago|pago facil|pagofacil|oxxo|efecty|baloto|servipag|abitab'
                            r'|redpagos)\b')
RAIL_WORDS = {'BR': re.compile(r'\bpix\b'), 'MX': re.compile(r'\b(spei|transferencia)\b'), 'BO': re.compile(r'\bqr\b')}



# What a checkout writes beside the sum the person pays.
_TOTAL_LABEL = re.compile(r'(?<!sub)\btotal\b|\bvoce pagara\b|\bpagaras\b|\bvas a pagar\b|\bvai pagar\b')
# A checked option naming another way to pay: the page's text never outweighs it.
_OTHER_METHOD = re.compile(r'\b(oxxo|boleto|efectivo|dinheiro|deposito|paypal|mercado ?pago|saldo|cuotas|parcel\w*'
                           r'|dinero en cuenta|puntos|points|rewards|cashback|bono|credito en cuenta'
                           r'|seven|7-eleven|kueski|aplazo|paycash|pse|nequi|yape|tigo|lotérica|loterica'
                           r'|contra ?entrega|cash)\b')


def total_on(page_text, total):
    """`total` is the page's grand total: the figure right after the LAST total-like label
    (a "Total de productos" or a "Total" before a discount is not the sum the person pays)."""
    text = guard.fold(page_text[:100000])
    amount = amount_of(total)

    def figures(labels):
        found = []
        for label in labels.finditer(text):
            # "Total (2 productos): $500", "Total (IVA incluido, en caso de ser aplicable) $129.00" (Amazon
            # México's real review page): what is in brackets is not the figure, nor in its way.
            after = re.sub(r'\([^)]{0,80}\)', ' ', text[label.end():label.end() + 160])
            figure = re.match(r'[^\d]{0,40}?(\d[\d.,]*\d|\d)', after)
            if figure:
                found.append(amount_of(figure.group(1)))
        return found

    # A grand total's own words ("Total del pedido", "Você pagará"): every one of them must agree,
    # so a seller's title written with them is a second total and nothing is approved.
    strong = figures(_GRAND_TOTAL)
    if strong:
        return amount is not None and set(strong) == {amount}
    plain = figures(_TOTAL_LABEL)
    return amount is not None and bool(plain) and plain[-1] == amount


def _method_refusal(task, seen):
    """'' when the store's local payment method is the one selected and no card is."""
    rail = RAIL_WORDS.get(task.country)
    manual = rail is None and countries.rail(task.country) is not None
    if manual:
        rail = MANUAL_WORDS   # a country where the person pays it from their bank or in cash
    if rail is None:
        return 'this store\'s country has no payment method here'
    chosen = [guard.fold(element.get('label')) for element in seen.elements if element.get('checked')]
    if manual and any(MANUAL_NEVER.search(label) and not MANUAL_VOUCHER.search(label) for label in chosen):
        return 'that way to pay is completed inside the checkout: choose one paid later from a bank or in cash'
    if any(guard.card_words(label) for label in chosen):
        return 'a card is selected: choose the local payment method'
    # Another way to pay ticked beside it (a balance, instalments): the order is not paid by the rail alone.
    if any(_OTHER_METHOD.search(label) and not rail.search(label) for label in chosen):
        return 'another payment method is selected: choose the local one'
    if any(rail.search(label) for label in chosen):
        return ''
    # A review page states the chosen method as text, beside its label: that block alone is read
    # (the rest of a page always offers cards, gift cards, instalments).
    text = guard.fold(seen.text[:100000])
    blocks = []
    for found in _METHOD_LABEL.finditer(text):
        if re.search(r'\b(cambiar|editar|alterar|change|modificar|trocar|elige|elegir|escolher|escolha|selecciona'
                     r'|seleciona|otro|outra|outro|otra|agregar|adicionar|add)\b\W*(el |la |o |a |tu |seu |sua )?$',
                     text[max(0, found.start() - 25):found.start()]) and not found.group(0).startswith('pag'):
            # "Cambiar método de pago": a link, not the method. Never "Pagando con SPEI" after the address's
            # own "Cambiar" (Amazon México's review page): that IS the method.
            continue
        block = text[found.end():found.end() + 120]
        # Only that method's own words: up to its "change" link or the next section's label.
        # ("Pagando con SPEI  Agregar tarjeta de regalo…": the next link is not the method.)
        end = re.search(r'\b(cambiar|editar|alterar|change|modificar|trocar|total|subtotal|resumen|resumo|entrega'
                        r'|agregar|anadir|adicionar|add)\b', block)
        block = block[:end.start()] if end else block
        if re.search(r'[a-z]', block):
            blocks.append(block)   # an empty one is a heading whose method sits elsewhere
    if any(rail.search(block) for block in blocks) and not any(guard.card_words(block) for block in blocks) \
            and not (manual and any(MANUAL_NEVER.search(block) and not MANUAL_VOUCHER.search(block)
                                    for block in blocks)):
        return ''
    return 'the local payment method is not the one selected'


def ship_to(text):
    """The delivery address as the checkout writes it (folded), or '': part of what the person approves."""
    folded = guard.fold(text[:100000])
    found = list(re.finditer(
        r'\b(enviar a|enviando a|enviaremos a|direccion de envio|direccion de entrega|entregar a|entregando a'
        r'|entrega en|envio a|se enviara a|endereco de entrega|entregar em|enviar para|shipping address'
        r'|deliver(ing)? to|ship(ping)? to|domicilio( de entrega)?|recibir en|recibe en)\b\s*'
        r'((cambiar|editar|alterar|change)\s*)?', folded))
    if not found:
        return ''
    # The checkout's own address block: the label nearest its payment method (not a header's location bar).
    method = _METHOD_LABEL.search(folded)
    best = min(found, key=lambda m: abs(m.start() - method.start())) if method else found[-1]
    block = re.split(r'\b(cambiar|editar|alterar|change|modificar|trocar|metodo de pago|forma de pago|total'
                     r'|llega|llegada|entrega estimada|pide en|arrives?|chega|receba|enviar a|enviando a'
                     r'|agregar|anadir|adicionar|recoleccion|instrucciones)\b'
                     r'|\ben \d+ ?h(rs?|oras?)?\b', folded[best.end():best.end() + 140])[0]
    return ' '.join(block.split())[:120]


# A cancellation, a return, a refund, a claim: the words that send one (beside the judge's own reading).
_REQUEST_WORDS = re.compile(r'\b(cancelar (el |la |mi |este |los |las )?(pedido|compra|orden|producto|articulos?)'
                            r'|cancel (the |this )?(order|items?)|cancelar (articulos )?seleccionados'
                            r'|solicitar (la |una )?(devolucion|devolucao|cancelacion|cancelamento|reembolso)'
                            r'|devolver (el |este |los )?(producto|articulo)s?|return items?|devolver|devolucao'
                            r'|enviar (la )?solicitud|confirmar (la )?(cancelacion|devolucion|devolucao|cancelamento)'
                            r'|request (a )?(refund|return)|reembolsar|abrir (un )?reclamo|iniciar (una )?devolucion'
                            r'|si,? cancelar)\b')
# A page that writes a request: its reason, its refund, a return or a cancellation.
_FORM_WORDS = re.compile(r'\b(motivo|razon|reason|devolucion|devolucao|cancelacion|cancelamento|reembolso|refund'
                         r'|reclamo|return)\b')


def _sends_request(element):
    return any(_REQUEST_WORDS.search(part) for part in guard._parts(element))


def _request_form(seen):
    return bool(_FORM_WORDS.search(guard.fold(seen.text[:100000])))


def _a_sender(element):
    """A button that may send the form it sits in: anything but a link, a choice, or an edit or choice by
    its whole words (guard._FINAL_SAFE)."""
    if element.get('tag') == 'a' or element.get('tag') == 'select' or element.get('type') in ('radio', 'checkbox') \
            or element.get('role') in ('radio', 'checkbox', 'option', 'tab'):
        return False
    parts = guard._parts(element)
    return not (parts and all(guard._FINAL_SAFE.fullmatch(part) for part in parts))


def judge_by_words(task, page, element, meter):
    parts = guard._parts(element)
    if getattr(task, 'kind', 'buy') == 'manage':
        # An order already placed: what sends a request about it, as a careful reader would tell.
        if (_sends_request(element) and element.get('tag') != 'a') or (_request_form(page) and _a_sender(element)):
            if not (guard.final_looking(element) and guard.final_step(page.text, page.elements)
                    and not _sends_request(element)):
                return 'request', 'it sends the request'
    if guard.final_looking(element) or guard.final_button(element):
        return 'places_order', 'final words'
    if any(guard.card_words(part) for part in parts):
        return 'card', 'a card'
    if any(guard._NEVER.search(part) for part in parts) or guard.account_address(element.get('href') or ''):
        return 'account', 'the account'
    on_checkout = guard.is_checkout(page)
    stage = guard.stage_of(page, on_checkout=on_checkout)
    if stage in ('final', 'money') and not guard.may_press(element, on_checkout=on_checkout, stage=stage, page=page):
        return 'places_order', 'the last step'   # as the real judge reads "Continuar" on the final review
    return 'safe', ''


def grand_total(page_text):
    """The figure a careful reader takes as the sum to pay, as the page writes it."""
    for found in re.finditer(r'\d[\d.,]*\d|\d', str(page_text or '')):
        if total_on(page_text, found.group(0)):
            return found.group(0)
    return ''


def review_by_words(task, page, element, item, meter):
    verdict, _ = judge_by_words(task, page, element, meter)
    refusal = _method_refusal(task, page)
    text = guard.fold(page.text[:100000])

    def shown(title):
        words = [word for word in guard.fold(title).split() if len(word) >= 4][:6]
        return not words or any(word in text for word in words)

    # A chosen cart ([{'title', 'quantity'}]): a careful reader sees each product on the page.
    item_shown = all(shown(entry['title']) for entry in item) if isinstance(item, list) else shown(item)
    return {'places_order': verdict == 'places_order' and not guard.product_address(page.url),
            'pays_with': 'asked' if not refusal else ('card' if 'card' in refusal else 'other'),
            'total': grand_total(page.text),
            'item_shown': item_shown,
            'ship_to': ship_to(page.text), 'why': refusal or 'read by words', 'lines': []}


def payment_page_by_words(task, page, meter):
    return guard.order_address(page.url), 'by its address'
