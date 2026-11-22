from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from users.funnel_schema import TrackFunnelEvent


class VerificationSdkEventTests(SimpleTestCase):
    def track(self, properties):
        import json
        info = SimpleNamespace(context=SimpleNamespace(META={}, user=None))
        with patch('users.funnel.emit_event') as emit, patch('users.funnel_schema._cached_ip_country', return_value=''):
            out = TrackFunnelEvent.mutate(None, info, event_name='verification_sdk_result',
                                          properties=json.dumps(properties))
        return out, emit

    def test_only_a_known_outcome_is_kept(self):
        out, emit = self.track({'outcome': 'cancelled', 'document_number': '123'})
        self.assertEqual(emit.call_args.kwargs['properties']['outcome'], 'cancelled')
        self.assertEqual(set(emit.call_args.kwargs['properties']), {'outcome', 'app_version'})

    def test_anything_else_is_dropped(self):
        for properties in ({'outcome': 'S-1234'}, {}, {'outcome': ['x']}):
            out, emit = self.track(properties)
            self.assertFalse(out.recorded)
            emit.assert_not_called()
