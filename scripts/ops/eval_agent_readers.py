# The shopping agent's readers (agent.judge, agent.review, agent.payment_page) against pages recorded from
# real stores (agent_tasks/tests/pages), with the live models. Code decides nothing by a store's words, so
# this is where a prompt or model change is checked before a person meets it. Costs a few cents.
# Usage: AWS_PROFILE=... CONFIO_ENV=testnet myvenv/bin/python manage.py shell < scripts/ops/eval_agent_readers.py
from types import SimpleNamespace

from agent_tasks import agent, operate
from agent_tasks.tests.test_real_pages import recorded

task = SimpleNamespace(site='www.amazon.com.mx', country='MX', goal='un chocolate', user_id=None)
meter = agent.Meter()
failed = []


def control(page, label):
    return next(e for e in page.elements if e['label'].startswith(label))


def check(name, got, want):
    ok = got == want if not callable(want) else want(got)
    print(('ok   ' if ok else 'FAIL ') + name + ('' if ok else f'  got {got!r}'))
    if not ok:
        failed.append(name)


spei, card, pay = recorded('amazon_mx_review_spei'), recorded('amazon_mx_review'), recorded('amazon_mx_pay')
item = 'chocolate'

JUDGE = (
    (spei, 'Realiza tu pedido y paga', ('places_order',)),
    (spei, 'Prueba Prime gratis', ('account',)),
    (spei, 'Empieza tu prueba gratis', ('account',)),
    (spei, 'Cambiar | Cambiar el método de pago', ('safe',)),
    (spei, 'Cambiar | Cambiar dirección de entrega', ('safe', 'account')),
    (spei, 'jueves 26 de nov | Envío estándar', ('safe',)),
    (spei, 'Cambiar fecha y hora de entrega', ('safe',)),
    (card, 'Realiza tu pedido y paga', ('places_order',)),
    (card, 'Revisa tu opción de envío. Marca esta casilla', ('account', 'unsure')),
    (pay, 'Transferencia electrónica (Finaliza tu pago', ('safe',)),
    (pay, 'Usar este método de pago', ('safe',)),
    (pay, 'MasterCard que termina en 1111', ('card',)),
    (pay, 'Paga en efectivo en tienda', ('safe', 'card', 'unsure')),
)
for page, label, wanted in JUDGE:
    verdict, why = agent.judge(task, page, control(page, label), meter)
    check(f'judge  {page.url[-4:]:5} {label[:44]:44} -> {verdict} ({why[:50]})', verdict, lambda got, w=wanted: got in w)

read = agent.review(task, spei, control(spei, 'Realiza tu pedido y paga'), item, meter)
print('review spei:', read)
check('review spei places_order', read['places_order'], True)
check('review spei pays_with', read['pays_with'], 'asked')
check('review spei total', operate.amount_of(read['total']), operate.amount_of('99.48'))
check('review spei ship_to is written on the page', operate.written_on(spei.text, read['ship_to']), True)
read = agent.review(task, card, control(card, 'Realiza tu pedido y paga'), item, meter)
print('review card:', read)
check('review card pays_with', read['pays_with'], 'card')
check('review card total', operate.amount_of(read['total']), operate.amount_of('129.00'))
read = agent.review(task, spei, control(spei, 'Prueba Prime gratis'), item, meter)
check('review: a Prime trial is not the order', read['places_order'], False)
read = agent.review(task, pay, control(pay, 'Usar este método de pago'), item, meter)
check('review: choosing the method is not the order', read['places_order'], False)

for page in (spei, pay):
    is_it, why = agent.payment_page(task, page, meter)
    check(f'payment_page {page.url[-4:]} is not one ({why[:50]})', is_it, False)

print(f'\n{len(failed)} failed; cost ${meter.usd:.4f}')
