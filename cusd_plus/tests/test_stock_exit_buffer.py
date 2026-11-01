from django.test import SimpleTestCase, override_settings

from cusd_plus.stock_fees import MAX_EXIT_BUFFER_BPS, MIN_EXIT_BUFFER_BPS, exit_buffer_bps


class StockExitBufferTests(SimpleTestCase):
    @override_settings(CUSD_PLUS_STOCK_EXIT_BUFFER_BPS=12)
    def test_follows_the_setting(self):
        self.assertEqual(exit_buffer_bps(), 12)

    @override_settings(CUSD_PLUS_STOCK_EXIT_BUFFER_BPS=5000)
    def test_a_bad_setting_cannot_drain_savings(self):
        self.assertEqual(exit_buffer_bps(), MAX_EXIT_BUFFER_BPS)

    @override_settings(CUSD_PLUS_STOCK_EXIT_BUFFER_BPS=-3)
    def test_never_zero_or_negative(self):
        self.assertEqual(exit_buffer_bps(), MIN_EXIT_BUFFER_BPS)
