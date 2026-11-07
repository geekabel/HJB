from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase

from accounts.models import User
from accounts.phone import display_phone, mask_phone, normalize_phone

# Made-up sample numbers, in valid ranges.


class NormalizePhoneTests(SimpleTestCase):
    def test_common_formats_to_e164(self):
        for entry in ("06 12 34 56 78", "06.12.34.56.78", "+33 6 12 34 56 78", "0033612345678"):
            with self.subTest(entry=entry):
                self.assertEqual(normalize_phone(entry), "+33612345678")

    def test_foreign_number(self):
        self.assertEqual(normalize_phone("+32 470 12 34 56"), "+32470123456")

    def test_empty(self):
        self.assertEqual(normalize_phone("  "), "")

    def test_refusal_with_explicit_code(self):
        cases = {
            "06 12": "phone_invalid",
            "bonjour": "phone_unreadable",
            "03 84 00 00 00": "phone_not_mobile",
        }
        for entry, code in cases.items():
            with self.subTest(entry=entry), self.assertRaises(ValidationError) as ctx:
                normalize_phone(entry)
            self.assertEqual(ctx.exception.code, code)


class UserPhoneTests(TestCase):
    def test_full_clean_normalizes_before_validators(self):
        user = User(username="awa", phone="06 12 34 56 78")
        user.set_unusable_password()
        user.full_clean()
        self.assertEqual(user.phone, "+33612345678")

    def test_full_clean_explains_the_error(self):
        user = User(username="awa", phone="06 12")
        user.set_unusable_password()
        with self.assertRaises(ValidationError) as ctx:
            user.full_clean()
        self.assertIn("phone", ctx.exception.error_dict)

    def test_one_number_per_person(self):
        User.objects.create_user(username="a", phone="+33612345678")
        with self.assertRaises(IntegrityError):
            User.objects.create_user(username="b", phone="+33612345678")

    def test_several_accounts_without_number(self):
        User.objects.create_user(username="a")
        User.objects.create_user(username="b")
        self.assertEqual(User.objects.filter(phone="").count(), 2)


class DisplayTests(SimpleTestCase):
    def test_display_and_mask(self):
        cases = {
            "+33612345647": ("06 12 34 56 47", "06 •• •• •• 47"),
            "+41791234567": ("+41 79 123 45 67", "+41 •• ••• •• 67"),
            "": ("", ""),
        }
        # Number that phonenumbers cannot read: still masked, with no error.
        self.assertEqual(mask_phone("+999999999"), "+99•••••99")
        for e164, (displayed, masked) in cases.items():
            with self.subTest(e164=e164):
                self.assertEqual(display_phone(e164), displayed)
                self.assertEqual(mask_phone(e164), masked)
