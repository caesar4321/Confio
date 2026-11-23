"""Pages, elements and rows the tests share. No network, no browser."""
import itertools
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from agent_tasks import page as pages
from agent_tasks.models import AgentTask

SITE = 'mercadolivre.com.br'
BASE = f'https://www.{SITE}'
CODE = ('00020101021226800014br.gov.bcb.pix2558pix.example.com/qr/v2/cob/4d8f085b2d9149deb10c3d0be5c59783'
        '5204000053039865802BR5915INFINIA SANDBOX6009SAO PAULO62070503***63044C26')
CODE_TEXT = 'Pague com Pix\nCopia e cola'
_numbers = itertools.count(1)


def element(label='', ref=0, **over):
    base = dict(ref=ref, tag='button', role='', type='', name='', autocomplete='', label=label, cut=False, href='',
                action='', method='', secret_form=False, disabled=False, nested=False, search=False, new_window=False,
                scripted=False)
    return {**base, **over}


def cart_button(label='Adicionar ao carrinho', **over):
    return element(label, **{'action': f'{BASE}/cart/add', 'method': 'post', **over})


def link(label, path='/p/MLB1', **over):
    return element(label, tag='a', href=f'{BASE}{path}', **over)


def search_box(**over):
    return element('Buscar', **{'tag': 'input', 'search': True, 'action': f'{BASE}/jm/search', 'method': 'get', **over})


def picture(url=f'{BASE}/pedido/1', boxes=(), words=(), fields=(), text=()):
    from agent_tasks.cdp import Picture
    return Picture(url=url, png=b'', boxes=tuple(boxes), scale=1.0, words=tuple(words),
                   fields=tuple(fields), text=text if text is None else tuple(text))


def snap(text='Loja', url=f'{BASE}/', elements=(), **over):
    return pages.Snapshot(url=url, text=text, elements=list(elements), **over)


@override_settings(BROWSERBASE_API_KEY='test-key', AGENT_TASKS_ENABLED=True, AGENT_TASKS_HOLD_SECONDS=0)
class RowsBase(TestCase):
    """Rows, with every way out of the process stubbed."""

    def setUp(self):
        self.user, self.account = self.person()
        self.kick = self.patch('agent_tasks.runner.kick')
        self.post = self.patch('agent_tasks.notes.post', return_value=None)
        self.vendor = self.patch('agent_tasks.browsers.provider').return_value
        self.vendor.name = 'fake'
        self.qr = self.patch('agent_tasks.qr.available', return_value=True)
        # A browser worker answered the heartbeat lately.
        self.worker = self.patch('agent_tasks.service.worker_alive', return_value=True)
        # No real heartbeat leaves a test, and none is left pending between tests.
        self.heartbeat = self.patch('agent_tasks.tasks.heartbeat.apply_async')
        from django.core.cache import cache
        cache.delete('agent_tasks:heartbeat_pending')
        # No balance read reaches the chain: unknown unless a test says otherwise.
        self.held = self.patch('payment_accounts.shortfall.dollars_held', return_value=None)

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def person(self, kind='personal'):
        from users.models import Account, User
        name = f'agenttask{next(_numbers)}'
        user = User.objects.create_user(username=name, firebase_uid=name)
        return user, Account.objects.create(user=user, account_type=kind, account_index=0)

    def make_task(self, **over):
        fields = dict(account=self.account, user=self.user, goal='compra uma garrafa térmica de 750 ml', site=SITE,
                      country='BR', state='working', provider='fake', session_id='s-1',
                      connect_url='wss://browser.invalid/s-1', session_expires_at=timezone.now() + timedelta(minutes=20))
        return AgentTask.objects.create(**{**fields, **over})
