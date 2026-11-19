import io
import json
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from blockchain.models import GmAssetProfile
from cusd_plus import gm_profiles
from cusd_plus.tasks import _fetch_logo

GOOD = ('Take-Two Interactive crea videojuegos como Grand Theft Auto y NBA 2K, y gana dinero '
        'vendiéndolos y con compras dentro de los juegos. Es la versión digital, emitida por Ondo, de su acción.')


def _response(answer, *, searched=True, cited=('https://take2games.com/about',)):
    return {'status': 'completed', 'output': [
        *([{'type': 'web_search_call', 'status': 'completed'}] if searched else []),
        {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer),
                                         'annotations': [{'type': 'url_citation', 'url': u} for u in cited]}]},
    ]}


def _answer(**over):
    return {'identified': True, 'description': GOOD, 'website': 'https://www.take2games.com/', **over}


def _market(*rows):
    return [{'primaryMarket': {'symbol': f'{t}on', 'price': '1'}, 'underlyingMarket': {'ticker': t, 'name': n}}
            for t, n in rows]


class GenerateTests(TestCase):
    def _gen(self, data):
        with mock.patch('assistant.engine._openai_post', return_value=data):
            return gm_profiles.generate('TTWO', 'Take-Two Interactive Software Inc')

    def test_cited_neutral_description_is_accepted_and_website_cleaned(self):
        profile = self._gen(_response(_answer()))
        self.assertEqual(profile['description'], GOOD)
        self.assertEqual(profile['website'], 'take2games.com')
        self.assertEqual(profile['sources'], ['https://take2games.com/about'])

    def test_rejections(self):
        cases = {
            'not_identified': _response(_answer(identified=False, description='')),
            'banned:recomend': _response(_answer(description=GOOD + ' Te la recomendamos.')),
            'length': _response(_answer(description='Corta. Ondo.')),
        }
        for reason, data in cases.items():
            with self.subTest(reason), self.assertRaisesMessage(ValueError, reason):
                self._gen(data)

    def test_a_search_without_results_is_intermittent_not_a_content_failure(self):
        cases = {
            'no_search': _response(_answer(), searched=False),
            # URLs the model types into its answer are not sources.
            'no_sources': _response({**_answer(), 'sources': ['https://made.up/x']}, cited=()),
        }
        for reason, data in cases.items():
            with self.subTest(reason), self.assertRaisesMessage(gm_profiles.SearchIncomplete, reason):
                self._gen(data)

    def test_intermittent_search_is_retried_then_counted_as_an_attempt(self):
        profile = {'description': GOOD, 'website': 'b.com', 'sources': ['https://x.test'], 'model': 'm'}
        incomplete = gm_profiles.SearchIncomplete('no_sources')
        market = _market(('AAAA', 'A'), ('BBBB', 'B'))
        with mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
                mock.patch('cusd_plus.gm_profiles.generate', side_effect=[incomplete, profile, incomplete, incomplete]), \
                mock.patch('config.ops_alerts.send_ops_alert') as alert:
            result = gm_profiles.describe_new_assets()
        self.assertEqual(result['written'], ['AAAA'])                     # retry succeeded
        row = GmAssetProfile.objects.get(ticker='BBBB')
        self.assertEqual((row.failed_attempts, row.description), (1, ''))  # bounded by MAX_ATTEMPTS
        self.assertNotIn('gm_profiles_outage', str(alert.call_args_list))  # not an outage

    def test_search_sources_count_when_the_answer_carries_no_citation(self):
        data = _response(_answer(), cited=())
        data['output'][0]['action'] = {'sources': [{'url': 'https://www.take2games.com/'}]}
        self.assertEqual(self._gen(data)['sources'], ['https://www.take2games.com/'])

    def test_banned_words_match_whole_words_only(self):
        neutral = 'Oscar Health es una aseguradora de salud que se compromete a dar seguros simples. Es la versión digital, emitida por Ondo, de su acción.'
        self.assertIsNone(gm_profiles.check_description(neutral))
        honest = GOOD + ' El fondo no garantiza ganancias y tu dinero no está asegurado.'
        self.assertIsNone(gm_profiles.check_description(honest))
        for bad in ('Te lo recomendamos.', 'Es una buena inversión.', 'Promete ganancias.', 'Tu dinero está asegurado.',
                    'Garantiza que no pierdas.', 'No deberías venderla en caídas.', 'No recomendamos venderla.',
                    'No te conviene esperar.'):
            with self.subTest(bad):
                self.assertTrue(gm_profiles.check_description(GOOD + ' ' + bad).startswith('banned:'))

    def test_garbled_output_is_rejected(self):
        data = {'status': 'completed', 'output': [{'type': 'web_search_call', 'status': 'completed'},
                                                  {'type': 'message', 'content': [{'type': 'output_text', 'text': 'nope'}]}]}
        with self.assertRaisesMessage(ValueError, 'bad_json'):
            self._gen(data)


class DescribeTests(TestCase):
    def test_writes_only_missing_listed_assets_and_never_overwrites_staff_copy(self):
        GmAssetProfile.objects.create(ticker='ZJAN', description='Staff text', source='edited')
        market = _market(('SPY', 'SPDR S&P 500'), ('TTWO', 'Take-Two'), ('ZJAN', 'Innovator Jan'))
        profile = {'description': GOOD, 'website': 'take2games.com', 'sources': ['https://x.test'], 'model': 'm'}
        with mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
                mock.patch('cusd_plus.gm_profiles.generate', return_value=profile) as gen, \
                mock.patch('config.ops_alerts.send_ops_alert'):
            result = gm_profiles.describe_new_assets()
        gen.assert_called_once_with('TTWO', 'Take-Two')  # SPY is hand-written
        self.assertEqual(result['written'], ['TTWO'])
        self.assertEqual(GmAssetProfile.objects.get(ticker='ZJAN').description, 'Staff text')

    def test_failure_is_recorded_backed_off_and_capped(self):
        from datetime import timedelta
        from django.utils import timezone
        market = _market(('TTWO', 'Take-Two'))
        with mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
                mock.patch('cusd_plus.gm_profiles.generate', side_effect=ValueError('no_search')):
            result = gm_profiles.describe_new_assets()
            self.assertEqual(result['failed'], {'TTWO': 'no_search'})
            row = GmAssetProfile.objects.get(ticker='TTWO')
            self.assertEqual((row.description, row.failed_attempts, row.last_error), ('', 1, 'no_search'))
            self.assertIsNone(gm_profiles.description_for('TTWO'))
            self.assertEqual(gm_profiles.missing_listed(), [])           # backing off
            GmAssetProfile.objects.update(last_attempt_at=timezone.now() - timedelta(days=8))
            self.assertEqual(gm_profiles.missing_listed(), [('TTWO', 'Take-Two')])
            GmAssetProfile.objects.update(failed_attempts=gm_profiles.MAX_ATTEMPTS)
            self.assertEqual(gm_profiles.missing_listed(), [])           # capped

    def test_new_listings_go_before_retries_and_a_retry_fills_the_blank_row(self):
        from datetime import timedelta
        from django.utils import timezone
        GmAssetProfile.objects.create(ticker='AAAA', failed_attempts=1,
                                      last_attempt_at=timezone.now() - timedelta(days=8))
        market = _market(('AAAA', 'Old fail'), ('ZZZZ', 'New listing'))
        with mock.patch('cusd_plus.gm_api.all_market', return_value=market):
            self.assertEqual(gm_profiles.missing_listed(), [('ZZZZ', 'New listing'), ('AAAA', 'Old fail')])
            profile = {'description': GOOD, 'website': 'aaaa.com', 'sources': ['https://x.test'], 'model': 'm'}
            with mock.patch('cusd_plus.gm_profiles.generate', return_value=profile), \
                    mock.patch('config.ops_alerts.send_ops_alert') as alert:
                gm_profiles.describe_new_assets()
        self.assertEqual(gm_profiles.description_for('AAAA'), GOOD)
        self.assertIn('ZZZZ', alert.call_args.args[0])

    def test_website_is_reduced_to_a_domain_and_hidden_rows_feed_no_logo(self):
        GmAssetProfile.objects.create(ticker='TTWO', description=GOOD, website='https://WWW.Take2Games.com/x?y=1')
        GmAssetProfile.objects.create(ticker='ZJAN', description=GOOD, website='wrong.com', is_hidden=True)
        self.assertEqual(gm_profiles.websites(), {'TTWO': 'take2games.com'})

    def test_description_lookup_prefers_curated_and_respects_hidden(self):
        GmAssetProfile.objects.create(ticker='SPY', description='generated')
        GmAssetProfile.objects.create(ticker='TTWO', description=GOOD)
        GmAssetProfile.objects.create(ticker='ZJAN', description='bad', is_hidden=True)
        self.assertNotEqual(gm_profiles.description_for('spy'), 'generated')
        self.assertEqual(gm_profiles.description_for('ttwo'), GOOD)
        self.assertIsNone(gm_profiles.description_for('ZJAN'))


def _png(side):
    out = io.BytesIO()
    Image.new('RGBA', (side, side), (200, 30, 30, 255)).save(out, format='PNG')
    return out.getvalue()


class LogoFallbackTests(TestCase):
    def _resp(self, status, content=b'', ctype='image/png'):
        return mock.Mock(status_code=status, content=content, headers={'Content-Type': ctype})

    def test_falls_back_to_the_website_icon_and_rejects_tiny_icons(self):
        with mock.patch('cusd_plus.tasks.requests.get', side_effect=[self._resp(404), self._resp(200, _png(256))]) as get:
            self.assertEqual(_fetch_logo('ANT', 'anthropic.com'), (_png(256), True))
        self.assertIn('domain=anthropic.com', get.call_args_list[1].args[0])
        with mock.patch('cusd_plus.tasks.requests.get', side_effect=[self._resp(404), self._resp(200, _png(16))]):
            self.assertEqual(_fetch_logo('ANT', 'anthropic.com'), (None, False))
        with mock.patch('cusd_plus.tasks.requests.get', side_effect=[self._resp(404)]):
            self.assertEqual(_fetch_logo('ANT', None), (None, False))
        import requests
        with mock.patch('cusd_plus.tasks.requests.get',
                        side_effect=[requests.Timeout(), self._resp(200, _png(128))]):
            self.assertEqual(_fetch_logo('ANT', 'anthropic.com'), (_png(128), True))


class AnnounceAndOutageTests(TestCase):
    def test_announce_splits_under_telegram_limit(self):
        written = [(f'T{i}', 'x' * 600) for i in range(20)]
        with mock.patch('config.ops_alerts.send_ops_alert', return_value=True) as alert:
            gm_profiles._announce(written)
        sent = [call.args[0] for call in alert.call_args_list]
        self.assertGreater(len(sent), 1)
        self.assertTrue(all(len(text) <= 4096 for text in sent))
        self.assertEqual(sum(text.count('\n• ') for text in sent), 20)

    def test_provider_outage_stops_the_sweep_without_burning_attempts(self):
        from assistant.engine import AssistantUnavailable
        market = _market(*[(f'T{i:03}', 'X') for i in range(6)])
        with mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
                mock.patch('cusd_plus.gm_profiles.generate', side_effect=AssistantUnavailable('OpenAI 429')) as gen, \
                mock.patch('config.ops_alerts.send_ops_alert') as alert:
            gm_profiles.describe_new_assets()
        self.assertEqual(gen.call_count, gm_profiles.OUTAGE_STREAK)
        self.assertEqual(set(GmAssetProfile.objects.values_list('failed_attempts', flat=True)), {0})
        self.assertEqual(alert.call_args.kwargs['dedupe_key'], 'gm_profiles_outage')

    def test_one_erroring_asset_backs_off_and_the_sweep_continues(self):
        from assistant.engine import AssistantUnavailable
        profile = {'description': GOOD, 'website': 'b.com', 'sources': ['https://x.test'], 'model': 'm'}
        market = _market(('AAAA', 'Slow'), ('BBBB', 'Fine'))
        with mock.patch('cusd_plus.gm_api.all_market', return_value=market), \
                mock.patch('cusd_plus.gm_profiles.generate',
                           side_effect=[AssistantUnavailable('timeout'), profile]), \
                mock.patch('config.ops_alerts.send_ops_alert') as alert:
            result = gm_profiles.describe_new_assets()
            self.assertEqual(result['written'], ['BBBB'])
            row = GmAssetProfile.objects.get(ticker='AAAA')
            self.assertEqual((row.failed_attempts, row.description), (0, ''))
            self.assertIsNotNone(row.last_attempt_at)
            self.assertEqual(gm_profiles.missing_listed(), [])    # AAAA backing off
            from datetime import timedelta
            GmAssetProfile.objects.filter(ticker='AAAA').update(last_attempt_at=row.last_attempt_at - timedelta(days=1))
            self.assertEqual(gm_profiles.missing_listed(), [('AAAA', 'Slow')])  # a day, not a week
        self.assertNotIn('gm_profiles_outage', str(alert.call_args_list))


class AdminWebsiteTests(TestCase):
    def test_admin_rejects_a_website_that_is_not_a_domain(self):
        from django.contrib.admin.sites import AdminSite
        from blockchain.admin import GmAssetProfileAdmin
        form_class = GmAssetProfileAdmin(GmAssetProfile, AdminSite()).get_form(request=None)
        data = {'ticker': 'TTWO', 'name': '', 'description': GOOD, 'source': 'generated'}
        bad = form_class(data={**data, 'website': 'not a domain'})
        self.assertFalse(bad.is_valid())
        self.assertIn('website', bad.errors)
        GmAssetProfile.objects.create(ticker='TTWO', description=GOOD)
        dupe = form_class(data={**data, 'ticker': 'ttwo', 'website': ''})
        self.assertIn('ticker', dupe.errors)                    # form error, not a 500
        data['ticker'] = 'NEW'
        good = form_class(data={**data, 'website': 'https://www.take2games.com/'})
        self.assertTrue(good.is_valid(), good.errors)
        self.assertEqual(good.cleaned_data['website'], 'take2games.com')


@override_settings(AWS_PUBLICATIONS_BUCKET='bucket', GM_LOGOS_S3_PREFIX='logos/')
class MirrorWebsiteLogoTests(TestCase):
    def _run(self, s3, fetched=(None, False)):
        from cusd_plus.tasks import mirror_gm_logos
        with mock.patch('boto3.client', return_value=s3), \
                mock.patch('cusd_plus.gm_api.all_market', return_value=_market(('ZJAN', 'Innovator'))), \
                mock.patch('cusd_plus.tasks._fetch_logo', return_value=fetched) as fetch:
            return mirror_gm_logos(), fetch

    def _s3(self, keys=()):
        s3 = mock.Mock()
        s3.get_paginator.return_value.paginate.return_value = [{'Contents': [{'Key': k} for k in keys]}]
        return s3

    def test_website_logo_is_remembered_then_dropped_when_profile_is_hidden(self):
        GmAssetProfile.objects.create(ticker='ZJAN', description=GOOD, website='innovatoretfs.com')
        first = self._s3()
        self._run(first, fetched=(_png(128), True))
        self.assertEqual(GmAssetProfile.objects.get().logo_website, 'innovatoretfs.com')
        self.assertEqual(first.put_object.call_args.kwargs['CacheControl'], 'public, max-age=86400')
        GmAssetProfile.objects.update(is_hidden=True)
        s3 = self._s3(keys=['logos/ZJAN.png'])
        result, fetch = self._run(s3)
        s3.delete_object.assert_called_once_with(Bucket='bucket', Key='logos/ZJAN.png')
        fetch.assert_called_once_with('ZJAN', None)          # re-fetched, hidden website unused
        self.assertEqual((result['dropped'], GmAssetProfile.objects.get().logo_website), (1, ''))

    def test_unchanged_website_logo_is_kept(self):
        GmAssetProfile.objects.create(ticker='ZJAN', description=GOOD, website='innovatoretfs.com',
                                      logo_website='innovatoretfs.com')
        s3 = self._s3(keys=['logos/ZJAN.png'])
        result, fetch = self._run(s3)
        s3.delete_object.assert_not_called()
        fetch.assert_not_called()
