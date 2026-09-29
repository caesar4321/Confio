from django.test import SimpleTestCase, override_settings

from ramps.koywe import on_ramp_paused


class OnRampPauseTests(SimpleTestCase):
    @override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=['CO'])
    def test_paused_country_is_case_insensitive(self):
        self.assertTrue(on_ramp_paused('CO'))
        self.assertTrue(on_ramp_paused('co'))
        self.assertFalse(on_ramp_paused('MX'))
        self.assertFalse(on_ramp_paused(None))

    @override_settings(KOYWE_ON_RAMP_PAUSED_COUNTRIES=[])
    def test_empty_setting_lifts_the_pause(self):
        self.assertFalse(on_ramp_paused('CO'))

    def test_colombia_is_paused_by_default(self):
        self.assertTrue(on_ramp_paused('CO'))
        self.assertFalse(on_ramp_paused('PE'))
