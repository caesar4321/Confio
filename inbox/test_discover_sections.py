from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone
from graphql import GraphQLError, GraphQLResolveInfo

from security.models import IdentityVerification
from users.models import Account, Business, User
from .admin import ChannelAdminForm
from .models import Channel, ContentItem, ContentSurface
from .official import (
    NOT_GRANTED, OFFICIAL, OWNER_NOT_ELIGIBLE, OWNER_NOT_VERIFIED, official_channel_ids, official_status,
)
from .schema import Query, build_discover_feed_item_payload


def MockInfo(user):
    return Mock(spec=GraphQLResolveInfo, context=SimpleNamespace(user=user))


class DiscoverSectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='discover-user', email='d@example.com', firebase_uid='discover-user')
        self.account = Account.objects.create(user=self.user, account_type='personal', account_index=0)
        self.founder = Channel.objects.create(
            slug='t-founder', kind='FOUNDER', title='Julian', official_granted_at=timezone.now(),
        )
        self.business = Business.objects.create(name='CIP Lima', category='other')
        self.institution = Channel.objects.create(
            slug='t-cip', kind='INSTITUTION', title='CIP Lima',
            owner_type='BUSINESS', owner_business=self.business,
        )
        self.founder_item = self.publish(self.founder, 'Founder post')
        self.institution_item = self.publish(self.institution, 'Institution post')
        self.info = MockInfo(self.user)
        context = patch('inbox.schema.get_context_models', return_value=(self.user, self.account, None, {}))
        context.start()
        self.addCleanup(context.stop)

    def publish(self, channel, title, status='PUBLISHED'):
        item = ContentItem.objects.create(channel=channel, item_type='TEXT', status=status,
                                          title=title, published_at=timezone.now())
        ContentSurface.objects.create(content_item=item, surface='DISCOVER')
        return item

    def feed(self, **kwargs):
        return Query().resolve_discover_feed(self.info, limit=20, **kwargs)

    def titles(self, **kwargs):
        return {item.title for item in self.feed(**kwargs).items}

    def test_para_ti_keeps_every_source(self):
        self.assertEqual(self.titles(), {'Founder post', 'Institution post'})
        self.assertEqual(self.titles(section='for_you'), {'Founder post', 'Institution post'})

    def test_oficial_follows_the_live_rule(self):
        self.assertEqual(self.titles(section='official'), {'Founder post'})
        self.institution.official_granted_at = timezone.now()
        self.institution.save()
        # Granted but no KYB yet: still out.
        self.assertEqual(self.titles(section='official'), {'Founder post'})
        kyb = self.verify_kyb(self.business)
        self.assertEqual(self.titles(section='official'), {'Founder post', 'Institution post'})
        kyb.delete()
        self.assertEqual(self.titles(section='official'), {'Founder post'})

    def test_comunidad_is_user_owned_channels_only(self):
        self.assertEqual(self.titles(section='community'), set())
        member = User.objects.create_user(username='member', email='m@example.com', firebase_uid='member')
        user_channel = Channel.objects.create(slug='t-user', kind='SYSTEM', title='LunaVerde',
                                              owner_type='USER', owner_user=member)
        self.publish(user_channel, 'User post')
        self.assertEqual(self.titles(section='community'), {'User post'})
        self.assertNotIn('User post', self.titles(section='official'))

    def test_member_post_on_an_official_board_is_community_not_official(self):
        member = User.objects.create_user(username='colegiado', email='c@example.com', firebase_uid='colegiado')
        item = self.publish(self.founder, 'Member post')
        item.owner_type, item.owner_user = 'USER', member
        item.save()
        self.assertNotIn('Member post', self.titles(section='official'))
        self.assertIn('Member post', self.titles(section='community'))
        by_title = {entry.title: entry for entry in self.feed().items}
        self.assertFalse(by_title['Member post'].is_official)
        self.assertTrue(by_title['Founder post'].is_official)

    def test_publisher_type_keys_from_older_builds_still_filter(self):
        self.assertEqual(self.titles(section='confio'), {'Founder post'})
        self.assertEqual(self.titles(section='institutions'), {'Institution post'})
        self.assertEqual(self.titles(section='businesses'), set())

    def test_byline_carries_channel_avatar_and_publish_date(self):
        self.founder.avatar_type, self.founder.avatar_value = 'IMAGE_URL', 'https://cdn.example/julian.jpg'
        self.founder.save()
        self.institution.avatar_type, self.institution.avatar_value = 'EMOJI', '🏛️'
        self.institution.save()
        by_title = {item.title: item for item in self.feed().items}
        founder, institution = by_title['Founder post'], by_title['Institution post']
        self.assertEqual((founder.source_avatar_url, founder.source_avatar_emoji), ('https://cdn.example/julian.jpg', None))
        self.assertEqual((institution.source_avatar_url, institution.source_avatar_emoji), (None, '🏛️'))
        self.assertEqual(founder.published_at, self.founder_item.published_at)

    def test_retired_sections_field_still_answers_for_older_builds(self):
        self.assertEqual(Query().resolve_discover_sections(self.info), [])

    def test_unknown_section_is_rejected_not_widened(self):
        for section in ('oficial', 'comunidad', 'everything'):
            with self.subTest(section=section), self.assertRaises(GraphQLError):
                self.feed(section=section)

    def test_items_carry_source_and_official_flag(self):
        by_title = {item.title: item for item in self.feed().items}
        founder = by_title['Founder post']
        self.assertEqual((founder.source_name, founder.source_section, founder.is_official), ('Julian', 'confio', True))
        institution = by_title['Institution post']
        self.assertEqual(
            (institution.source_name, institution.source_section, institution.is_official),
            ('CIP Lima', 'institutions', False),
        )

    def verify_kyb(self, business, status='verified'):
        return IdentityVerification.objects.create(
            user=self.user, verified_first_name=business.name, verified_last_name='Business',
            verified_date_of_birth=date(2020, 1, 1), verified_nationality='PER', verified_address='Av. 1',
            verified_city='Lima', verified_state='Lima', verified_country='PER', document_type='national_id',
            document_number=f'ruc-{business.id}', document_issuing_country='PER', status=status,
            risk_factors={'account_type': 'business', 'business_id': str(business.id)},
        )

    def test_business_channel_is_official_only_with_grant_and_live_kyb(self):
        self.assertEqual(official_status(self.institution), NOT_GRANTED)
        self.institution.official_granted_at = timezone.now()
        self.institution.save()
        self.assertEqual(official_status(self.institution), OWNER_NOT_VERIFIED)
        self.verify_kyb(self.business, status='pending')
        self.assertEqual(official_status(self.institution), OWNER_NOT_VERIFIED)
        kyb = self.verify_kyb(self.business)
        self.assertEqual(official_status(self.institution), OFFICIAL)
        self.assertTrue(build_discover_feed_item_payload(self.institution_item, self.user, self.account, None).is_official)
        # Losing the KYB drops the badge with no one touching the channel.
        kyb.delete()
        self.assertEqual(official_status(self.institution), OWNER_NOT_VERIFIED)
        self.assertFalse(build_discover_feed_item_payload(self.institution_item, self.user, self.account, None).is_official)

    def test_system_owner_cannot_skip_kyb_by_posing_as_an_institution(self):
        fake = Channel.objects.create(slug='t-fake', kind='INSTITUTION', title='CIP', official_granted_at=timezone.now())
        self.assertEqual(official_status(fake), OWNER_NOT_ELIGIBLE)
        self.assertEqual(official_status(self.founder), OFFICIAL)

    def test_feed_page_checks_kyb_once(self):
        self.institution.official_granted_at = timezone.now()
        self.institution.save()
        self.verify_kyb(self.business)
        other = Business.objects.create(name='Café Juan', category='other')
        shop = Channel.objects.create(slug='t-shop2', kind='BUSINESS', title='Café', owner_type='BUSINESS',
                                      owner_business=other, official_granted_at=timezone.now())
        with self.assertNumQueries(1):
            ids = official_channel_ids([self.founder, self.institution, shop])
        self.assertEqual(ids, {self.founder.id, self.institution.id})

    def admin_form(self, channel, **changes):
        data = {
            'title': channel.title, 'slug': channel.slug, 'kind': channel.kind, 'avatar_type': 'EMOJI',
            'subscription_mode': channel.subscription_mode, 'channel_scope': channel.channel_scope,
            'owner_type': channel.owner_type, 'owner_business': channel.owner_business_id or '',
            'sort_order': 0, 'is_active': 'on', 'official_note': '', **changes,
        }
        return ChannelAdminForm(data=data, instance=channel)

    def avatar_file(self, name='logo.png', fmt='PNG', size=(8, 8), mode='RGB'):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buffer = BytesIO()
        Image.new(mode, size, 128 if mode == 'L' else (16, 185, 129)).save(buffer, format=fmt)
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    @patch('inbox.admin.settings.AWS_PUBLICATIONS_BUCKET', 'test-publications')
    def upload_form(self, upload):
        form = ChannelAdminForm(data=self.admin_form(self.institution).data, instance=self.institution,
                                files={'avatar_upload': upload})
        form.is_valid()
        return form

    def test_admin_avatar_upload_rejects_a_truncated_image(self):
        import random
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        # Detailed pixels so the cut lands in scan data: the header stays valid
        # (passes ImageField's verify) and only a full decode notices.
        rng = random.Random(1)
        image = Image.new('RGB', (64, 64))
        image.putdata([(rng.randint(0, 255),) * 3 for _ in range(64 * 64)])
        buffer = BytesIO()
        image.save(buffer, format='JPEG')
        data = buffer.getvalue()
        truncated = SimpleUploadedFile('logo.jpg', data[: int(len(data) * 0.7)], content_type='image/jpeg')
        form = self.upload_form(truncated)
        self.assertIn('avatar_upload', form.errors)

    def test_admin_avatar_upload_rejects_huge_dimensions(self):
        form = self.upload_form(self.avatar_file(size=(4097, 4097), mode='L'))
        self.assertIn('avatar_upload', form.errors)

    def test_admin_avatar_upload_needs_the_publications_bucket(self):
        with patch('inbox.admin.settings.AWS_PUBLICATIONS_BUCKET', None):
            form = ChannelAdminForm(data=self.admin_form(self.institution).data, instance=self.institution,
                                    files={'avatar_upload': self.avatar_file()})
            self.assertFalse(form.is_valid())
        self.assertIn('AWS_PUBLICATIONS_BUCKET', str(form.errors['avatar_upload']))

    def test_admin_avatar_upload_is_reencoded_without_metadata(self):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        source = BytesIO()
        exif = Image.Exif()
        exif[0x010F] = 'PhoneMaker'  # Make; stands in for GPS and other metadata
        Image.new('RGB', (8, 8), (16, 185, 129)).save(source, format='JPEG', exif=exif)
        form = self.upload_form(SimpleUploadedFile('me.jpg', source.getvalue(), content_type='image/jpeg'))
        self.assertTrue(form.is_valid(), form.errors)
        encoded = form.cleaned_data['avatar_upload'].confio_bytes
        self.assertNotEqual(encoded, source.getvalue())
        with Image.open(BytesIO(encoded)) as reopened:
            self.assertEqual(reopened.format, 'JPEG')
            self.assertEqual(dict(reopened.getexif()), {})

    def test_admin_avatar_upload_becomes_the_channel_image(self):
        from django.contrib.admin.sites import AdminSite
        from .admin import ChannelAdmin
        form = self.upload_form(self.avatar_file())
        self.assertTrue(form.is_valid(), form.errors)
        request = SimpleNamespace(user=self.user)
        with patch('inbox.admin.upload_object', return_value='https://cdn.example/cip.png') as upload:
            ChannelAdmin(Channel, AdminSite()).save_model(request, form.save(commit=False), form, True)
        self.institution.refresh_from_db()
        self.assertEqual((self.institution.avatar_type, self.institution.avatar_value), ('IMAGE_URL', 'https://cdn.example/cip.png'))
        kwargs = upload.call_args.kwargs
        self.assertEqual(kwargs['content_type'], 'image/png')
        self.assertIn('/channel-avatars/', kwargs['key'])

    def test_admin_avatar_upload_rejects_a_non_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile('logo.png', b'<svg onload=alert(1)>', content_type='image/png')
        form = ChannelAdminForm(data=self.admin_form(self.institution).data, instance=self.institution,
                                files={'avatar_upload': fake})
        self.assertFalse(form.is_valid())
        self.assertIn('avatar_upload', form.errors)

    def test_admin_grant_requires_note_and_verified_owner(self):
        form = self.admin_form(self.institution, grant_official='on', official_note='')
        self.assertFalse(form.is_valid())
        self.assertIn('official_note', form.errors)
        self.assertIn('grant_official', form.errors)
        self.verify_kyb(self.business)
        form = self.admin_form(self.institution, grant_official='on', official_note='Llamada con secretaría CN')
        self.assertTrue(form.is_valid(), form.errors)
