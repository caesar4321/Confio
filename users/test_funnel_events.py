from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from users.funnel_schema import CLIENT_EMITTABLE_EVENTS, TrackFunnelEvent
from users.models_analytics import FunnelEvent


class TrackFunnelEventTests(TestCase):
    """A client funnel event also keeps the country of the request IP, so demand
    for a rail someone is blocked from can be counted by estimated location
    (Venezuelans asking for Colombia's rail from Colombia, say)."""

    def track(self, event_name='local_rail_blocked_interest', meta=None, user=None, **kwargs):
        info = SimpleNamespace(context=SimpleNamespace(
            META=meta if meta is not None else {'HTTP_CF_IPCOUNTRY': 'CO'}, user=user))
        with self.captureOnCommitCallbacks(execute=True):
            return TrackFunnelEvent.mutate(None, info, event_name=event_name, **kwargs)

    def test_a_blocked_rail_interest_keeps_both_countries(self):
        result = self.track(
            country='VE', platform='ios', source_type='rail_interest', channel='receive',
            properties={'rail': 'co_breb_receive', 'country': 'CO', 'stage': 'confirmed'})
        self.assertTrue(result.recorded)
        row = FunnelEvent.objects.get(event_name='local_rail_blocked_interest')
        # country = declared country; ip_country = estimated request country.
        self.assertEqual((row.country, row.ip_country), ('VE', 'CO'))
        self.assertEqual(row.properties['stage'], 'confirmed')

    def test_the_blocked_rail_event_is_client_emittable(self):
        self.assertIn('local_rail_blocked_interest', CLIENT_EMITTABLE_EVENTS)

    def test_an_unknown_event_is_never_recorded(self):
        result = self.track(event_name='not_whitelisted')
        self.assertFalse(result.recorded)
        self.assertEqual(FunnelEvent.objects.count(), 0)

    def test_an_unresolvable_ip_leaves_the_country_empty(self):
        result = self.track(meta={'REMOTE_ADDR': '192.168.1.10'})
        self.assertTrue(result.recorded)
        self.assertEqual(FunnelEvent.objects.get().ip_country, '')

    def test_app_uses_authenticated_phone_country_without_a_client_country(self):
        from users.models import User
        user = User.objects.create_user(username='funnel-demand', phone_country='VE')
        result = self.track(user=user, properties={
            'country': 'CO', 'rail': 'co_breb', 'direction': 'send',
            'reason': 'infinia_nationality_not_supported', 'stage': 'tap',
        })
        self.assertTrue(result.recorded)
        row = FunnelEvent.objects.get()
        self.assertEqual(row.user_id, user.pk)
        self.assertEqual((row.country, row.ip_country, row.properties['country']), ('VE', 'CO', 'CO'))

    def test_ip_country_survives_the_deduplicated_insert(self):
        for _ in range(2):
            self.assertTrue(self.track(properties={'dedupe_key': 'one-interest'}).recorded)
        row = FunnelEvent.objects.get()
        self.assertEqual(row.ip_country, 'CO')

    def test_geo_failure_does_not_drop_the_interest(self):
        with patch('users.funnel_schema._cached_ip_country', side_effect=RuntimeError('unavailable')):
            result = self.track()
        self.assertTrue(result.recorded)
        self.assertEqual(FunnelEvent.objects.get().ip_country, '')

    def test_ip_country_uses_existing_cache_without_an_external_lookup(self):
        from security.models import IPAddress
        IPAddress.objects.create(ip_address='8.8.8.8', country_code='CO')
        with patch('requests.get') as lookup:
            result = self.track(meta={'REMOTE_ADDR': '8.8.8.8'})
        self.assertTrue(result.recorded)
        lookup.assert_not_called()
        self.assertEqual(FunnelEvent.objects.get().ip_country, 'CO')

    def test_uncached_public_ip_does_not_trigger_an_external_lookup(self):
        with patch('requests.get') as lookup:
            result = self.track(meta={'REMOTE_ADDR': '8.8.4.4'})
        self.assertTrue(result.recorded)
        lookup.assert_not_called()
        self.assertEqual(FunnelEvent.objects.get().ip_country, '')

    def test_unknown_edge_country_falls_back_to_cached_country(self):
        from security.models import IPAddress
        IPAddress.objects.create(ip_address='8.8.8.8', country_code='CO')
        result = self.track(meta={
            'REMOTE_ADDR': '8.8.8.8', 'HTTP_CF_IPCOUNTRY': 'XX'})
        self.assertTrue(result.recorded)
        self.assertEqual(FunnelEvent.objects.get().ip_country, 'CO')

    def test_malformed_ip_does_not_break_the_event_transaction(self):
        result = self.track(meta={'REMOTE_ADDR': 'not-an-ip'})
        self.assertTrue(result.recorded)
        self.assertEqual(FunnelEvent.objects.get().ip_country, '')
