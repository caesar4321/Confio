"""The number typed as the answer to code's "¿Cuántos dólares …?" for a
Cuenta inteligente change (confirm.answer): code makes the proposal with it.

A buy rule becomes the proposal the person reviews and signs (the "Revisar y
firmar" button). A target split is saved and its buy rules proposed; an
alert with a prepared buy is saved: the number answered a question that named
the whole split or alert. What is saved is saved only after the reply's own
checks, under the person's lock (service._answer_to_question runs `deferred`):
never when the team took the thread or they wrote again meanwhile. The words
they wrote when asking (`said`, kept with the question) still name the
investment and the alert's level; only the amount comes from the number.
"""
import logging

logger = logging.getLogger(__name__)

_FAILED = {'es': 'No pude prepararlo ahora. Inténtalo de nuevo.', 'pt': 'Não consegui preparar agora. Tente de novo.',
           'en': "I couldn't prepare it now. Please try again."}
# The Cuenta inteligente's own reasons are written in Spanish.
_REFUSED = {'pt': 'Não consegui preparar isso: confira na sua Cuenta inteligente.',
            'en': "I couldn't prepare that: check it in your Cuenta inteligente."}
_SIGN = {
    True: {'es': 'Revísala y fírmala con el botón de abajo: nada cambia hasta que la firmes.',
           'pt': 'Revise e assine no botão abaixo: nada muda até você assinar.',
           'en': 'Review and sign it with the button below: nothing changes until you sign.'},
    False: {'es': 'Hazlo en tu Cuenta inteligente → Reglas: nada cambia hasta que la firmes.',
            'pt': 'Faça isso na sua Cuenta inteligente → Reglas: nada muda até você assinar.',
            'en': 'Do it in your Cuenta inteligente → Reglas: nothing changes until you sign.'},
}


_LINES = {
    'pt': {'buy': 'comprar {amount} de {what}', 'send': 'enviar {amount} para {what}', 'payout': 'pagar {amount} para {what}',
           'create': 'Nova regra: {terms} {every}{start}.', 'update': 'Regra alterada: {terms} {every}{start}.',
           'cancel': 'Cancelar a regra de {terms}.'},
    'en': {'buy': 'buy {amount} of {what}', 'send': 'send {amount} to {what}', 'payout': 'pay {amount} to {what}',
           'create': 'New rule: {terms} {every}{start}.', 'update': 'Changed rule: {terms} {every}{start}.',
           'cancel': 'Cancel the rule for {terms}.'},
}


def _step_lines(steps, lang, tz=None):
    """What a proposal changes, in Portuguese or English (its own sentences are Spanish)."""
    from decimal import Decimal

    from .engine import _EVERY
    words = _LINES[lang]
    out = []
    for step in steps or []:
        what = step.get('asset_name') or step.get('payee_name') or step.get('payout_label') or ''
        amount = f"US${Decimal(step['amount_usd']):.2f}" if step.get('amount_usd') else ''
        terms = what if step.get('action') == 'cancel' else words.get(step.get('kind'), '{what}').format(
            amount=amount, what=what)
        start = ''
        try:
            from datetime import datetime
            when = datetime.fromisoformat(str(step.get('first_run_at')))
            when = when.astimezone(tz) if tz is not None and when.tzinfo else when      # the day on their clock
            start = {'pt': ', a partir de {d}', 'en': ', starting {d}'}[lang].format(d=when.strftime('%d/%m'))
        except (TypeError, ValueError):
            pass
        line = words.get(step.get('action'), words['update']).format(
            terms=' '.join(terms.split()), every=_EVERY[lang].get(step.get('frequency'), ''), start=start)
        out.append(' '.join(line.split()).replace(' .', '.').replace(' ,', ','))
    return out


def _refused(message, lang):
    return message if lang == 'es' else _REFUSED[lang]


def _proposal(belt, proposal, lang):
    """The proposal on this reply, with its button, in code's words."""
    if proposal.get('ok') is False:
        return False, _refused(proposal.get('motivo') or _FAILED[lang], lang), {}
    out = belt._attach_rule_proposal(proposal)
    # What the proposal changes, in their language: the terms they review before signing.
    said = '; '.join(out.get('cambios') or []) if lang == 'es' else ' '.join(_step_lines(proposal.get('steps'), lang, belt.viewer.tz))
    if belt.result.rule_proposal is None:
        return True, said or _FAILED[lang], {}
    sign = _SIGN[bool(belt.can_navigate)][lang]
    return True, f'{said}\n\n{sign}' if said else sign, {
        'actions': list(belt.result.actions), 'rule_proposal': belt.result.rule_proposal}


def _call(belt, fn, data, **amount):
    from smart_account.assistant_ops import OpsRefused
    viewer = belt.viewer
    args = {key: value for key, value in (data.get('args') or {}).items()}
    try:
        return fn(viewer.user, said=data.get('said') or '', meta=viewer.request_meta, tz=viewer.tz,
                  amount_given=True, **{**args, **amount})
    except OpsRefused as exc:
        return {'ok': False, 'motivo': exc.message}


def _warm_prices():
    """Read the stock market (cached for a minute) before the person's lock is taken: the save below runs under
    that lock, which a reply from the team waits on, and must not wait on the network there."""
    try:
        from smart_account import assets
        assets._stock_market()
        assets.stock_registry()
    except Exception:  # noqa: BLE001 - only a warm-up: the save reads it again, and says so if it can't
        logger.warning('Confio Assistant: market not warmed before a save', exc_info=True)


def rule(belt, data, amount, lang):
    from smart_account import assistant_ops
    return _proposal(belt, _call(belt, assistant_ops.propose_rule, data, amount_usd=str(amount)), lang)


def allocation(belt, data, amount, lang):
    def save():
        from smart_account import assistant_ops
        proposal = _call(belt, assistant_ops.propose_target_allocation, data, total_usd=str(amount))
        if proposal.get('ok') is False:
            return _proposal(belt, proposal, lang)
        from .engine import _EVERY
        every = _EVERY.get(lang, {}).get(proposal.get('frequency'), '')
        saved = proposal.get('texto') if lang == 'es' else {
            'pt': f"Salvei seu objetivo: {proposal.get('split')}, com {proposal.get('total_text')} {every} no total. "
                  'Ele se mantém só com compras novas: nunca vendo nada. Cada regra vale quando você assina.',
            'en': f"I saved your target: {proposal.get('split')}, with {proposal.get('total_text')} {every} in total. "
                  'It is kept with new buys only: I never sell anything. Each rule starts when you sign it.'}[lang]
        if not proposal.get('steps'):
            return True, saved, {'writes': True}       # the rules already buy that: nothing new to sign
        _done, text, extra = _proposal(belt, {k: v for k, v in proposal.items() if k != 'texto'}, lang)
        return True, f'{saved}\n\n{text}' if saved else text, {**extra, 'writes': True}
    _warm_prices()
    return True, '', {'deferred': save}


def watch(belt, data, amount, lang):
    def save():
        from smart_account import watches
        from smart_account.assistant_ops import OpsRefused
        viewer = belt.viewer
        try:
            draft = watches.propose(viewer.user, said=data.get('said') or '', meta=viewer.request_meta,
                                    amount_given=True,
                                    **{**(data.get('args') or {}), 'action_amount_usd': str(amount)})
            watches.save(viewer.user, draft)
        except OpsRefused as exc:
            return False, _refused(exc.message, lang), {}
        from decimal import Decimal
        terms = draft['texto'] if lang == 'es' else watches.describe_in(
            lang, draft['kind'], asset_key=draft.get('asset_key') or '', currency=draft.get('currency') or '',
            threshold=Decimal(draft['threshold']), action=draft.get('action') or None)
        return True, {
            'es': f'Listo, guardé tu alerta. {terms} Solo te aviso: nada se compra ni se vende sin tu firma.',
            'pt': f'Pronto, salvei seu alerta. {terms} Só aviso: nada é comprado nem vendido sem sua assinatura.',
            'en': f"Done, I saved your alert. {terms} I only let you know: nothing is bought or sold without your "
                  'signature.'}[lang], {'writes': True}
    _warm_prices()
    return True, '', {'deferred': save}
