from django.test import SimpleTestCase

from users.masking import mask_email


class MaskEmailTests(SimpleTestCase):
    def test_keeps_the_domain_and_a_recognizable_prefix(self):
        self.assertEqual(mask_email('julian@gmail.com'), 'ju•••@gmail.com')
        self.assertEqual(mask_email('previous@example.com'), 'pr•••@example.com')

    def test_short_local_parts_show_a_single_character(self):
        self.assertEqual(mask_email('anna@gmail.com'), 'a•••@gmail.com')
        self.assertEqual(mask_email('a@gmail.com'), 'a•••@gmail.com')

    def test_mask_does_not_reveal_the_address_length(self):
        self.assertEqual(len(mask_email('ab12345@x.com')), len(mask_email('ab1234567890@x.com')))

    def test_missing_or_malformed_addresses_reveal_nothing(self):
        for value in (None, '', '   ', 'no-at-sign', '@gmail.com', 'julian@'):
            with self.subTest(value=value):
                self.assertEqual(mask_email(value), '')
