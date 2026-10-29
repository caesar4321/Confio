"""Central device location (security/location.py)."""
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from security import location
from security.models import LocationReading

User = get_user_model()

LA_PAZ = (-16.4897, -68.1193)
BOGOTA = (4.7110, -74.0721)
CARACAS = (10.4806, -66.9036)


class CountryAtTests(TestCase):
    def test_points_resolve_to_their_country(self):
        # protects=coordinates map to the right ISO-2 via the tz database; fails_when=a capital lands in a neighbour or the sea returns a country; no_claim=border precision under ~1 km
        self.assertEqual(location.country_at(*LA_PAZ), 'BO')
        self.assertEqual(location.country_at(*BOGOTA), 'CO')
        self.assertEqual(location.country_at(*CARACAS), 'VE')
        self.assertEqual(location.country_at(0.0, -30.0), '')


class RecordAndResidenceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='located', firebase_uid='located')

    def reading(self, point, days_ago, ip_country=None, **extra):
        r = location.record_reading(self.user, purpose=extra.pop('purpose', 'residence'), latitude=point[0],
                                    longitude=point[1], accuracy_m=extra.pop('accuracy', 50), **extra)
        # The request's IP agrees with the point unless a test says otherwise.
        LocationReading.objects.filter(pk=r.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago), ip_address='190.0.0.1',
            ip_country=r.country if ip_country is None else ip_country)
        return r

    def test_bad_values_are_not_recorded(self):
        # protects=only real coordinates are kept; fails_when=NaN or out-of-range points are stored; no_claim=device honesty
        self.assertIsNone(location.record_reading(self.user, purpose='residence', latitude=float('nan'), longitude=1))
        self.assertIsNone(location.record_reading(self.user, purpose='residence', latitude=91, longitude=1))
        self.assertEqual(LocationReading.objects.count(), 0)

    def test_gps_majority_of_days_decides_and_mocks_never_count(self):
        # protects=residence follows where the phone is on most days, ignoring mock and imprecise fixes; fails_when=a single day, a mock or a 20 km fix moves residence; no_claim=IP fallback
        self.reading(LA_PAZ, 1)
        self.assertIsNone(location.gps_residence_country_for(self.user))  # one day is not enough
        self.reading(LA_PAZ, 2)
        self.reading(BOGOTA, 3, mocked=True)
        self.reading(BOGOTA, 4, accuracy=20000)
        self.assertEqual(location.gps_residence_country_for(self.user), 'BO')
        self.reading(BOGOTA, 5)
        self.reading(BOGOTA, 6)
        self.assertIsNone(location.gps_residence_country_for(self.user))  # 2 vs 2: no majority

    def test_device_location_outranks_ip_for_residence(self):
        # protects=a VPN moves the IP, not the phone; fails_when=refresh writes the IP country over two GPS days; no_claim=review-link precedence (tested elsewhere)
        from users.residence import refresh_residence_country
        User.objects.filter(pk=self.user.pk).update(country='CO', country_source='residence')
        self.user.refresh_from_db()
        self.reading(LA_PAZ, 1)
        self.reading(LA_PAZ, 2)
        self.assertTrue(refresh_residence_country(self.user))
        self.user.refresh_from_db()
        self.assertEqual((self.user.country, self.user.country_source), ('BO', 'gps'))

    def test_record_location_mutation_stores_and_rate_limits(self):
        # protects=the app's daily reading lands with its coordinates and cannot flood; fails_when=a second call in 10 min writes again; no_claim=the app's daily schedule
        from users.schema import RecordLocation
        info = SimpleNamespace(context=SimpleNamespace(user=self.user, META={}))
        self.assertTrue(RecordLocation.mutate(None, info, latitude=LA_PAZ[0], longitude=LA_PAZ[1], accuracy=30).success)
        RecordLocation.mutate(None, info, latitude=BOGOTA[0], longitude=BOGOTA[1], accuracy=30)
        self.assertEqual(list(LocationReading.objects.values_list('country', 'purpose')), [('BO', 'residence')])

    def test_unverified_gps_never_beats_the_ip_it_came_with(self):
        # protects=fake coordinates cannot move residence past IP evidence (US-person exclusion); fails_when=GPS days with a foreign or VPN IP decide residence; no_claim=IP residence itself
        from security.models import IPAddress
        self.reading(LA_PAZ, 1, ip_country='US')
        self.reading(LA_PAZ, 2, ip_country='US')
        self.assertIsNone(location.gps_residence_country_for(self.user))
        LocationReading.objects.all().delete()
        self.reading(LA_PAZ, 1)
        self.reading(LA_PAZ, 2)
        IPAddress.objects.create(ip_address='190.0.0.1', is_vpn=True)
        self.assertIsNone(location.gps_residence_country_for(self.user))

    def test_verified_readings_count_alone_and_refused_breb_never(self):
        # protects=device-attested readings stand on their own; refused Bre-B attempts are evidence only; fails_when=a refused attempt votes or an attested one needs IP; no_claim=attestation itself
        self.reading(LA_PAZ, 1, ip_country='US', purpose='breb', verified=True)
        self.reading(LA_PAZ, 2, ip_country='US', purpose='breb', verified=True)
        self.assertEqual(location.gps_residence_country_for(self.user), 'BO')
        LocationReading.objects.all().delete()
        self.reading(LA_PAZ, 1, purpose='breb', verified=False)
        self.reading(LA_PAZ, 2, purpose='breb', verified=False)
        self.assertIsNone(location.gps_residence_country_for(self.user))

    def test_a_day_in_two_countries_votes_once_or_not_at_all(self):
        # protects=row order never decides residence; fails_when=a tied day votes for both countries; no_claim=none beyond protects
        for days_ago in (1, 2):
            self.reading(LA_PAZ, days_ago)
            self.reading(BOGOTA, days_ago)
        self.assertIsNone(location.gps_residence_country_for(self.user))

    def test_a_forged_country_header_does_not_corroborate(self):
        # protects=a direct-origin request cannot claim a country by header; fails_when=CF-IPCountry without Cloudflare is stored as the reading's IP country; no_claim=Cloudflare's own geo accuracy
        r = location.record_reading(self.user, purpose='residence', latitude=LA_PAZ[0], longitude=LA_PAZ[1],
                                    accuracy_m=50, meta={'REMOTE_ADDR': '127.0.0.1', 'HTTP_CF_IPCOUNTRY': 'BO'})
        self.assertNotEqual(r.ip_country, 'BO')
