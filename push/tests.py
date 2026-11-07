"""Web Push notifications (card T19)."""

import json
from unittest import mock

import requests
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.roles import Role
from accounts.tests.helpers import log_in_verified, make_user
from tools.html_capture import save_page

from . import services
from .checks import vapid_settings
from .models import PushSubscription
from .vapid import application_server_key, new_private_key, vapid

CHROME = "https://fcm.googleapis.com/fcm/send/abc123"
SAFARI = "https://web.push.apple.com/QGuQyavXutnMH"
KEYS = {
    "p256dh": (
        "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM"
    ),
    "auth": "tBHItJI5svbpez7KI4CCXg",
}
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)


def push_error(status):
    from pywebpush import WebPushException

    response = requests.Response()
    response.status_code = status
    return WebPushException("push failed", response=response)


class VapidTests(TestCase):
    def test_key_and_public_key(self):
        self.assertEqual(len(application_server_key()), 87)  # 65 bytes in base64url
        self.assertEqual(vapid_settings(None), [])

    def test_new_key_is_valid(self):
        with override_settings(VAPID_PRIVATE_KEY=new_private_key()):
            vapid()

    def test_missing_or_invalid(self):
        for key in ("", "not-a-key"):
            with self.subTest(key=key), override_settings(VAPID_PRIVATE_KEY=key):
                with self.assertRaises(ImproperlyConfigured):
                    vapid()
                self.assertEqual(vapid_settings(None)[0].id, "push.E001")
        with override_settings(VAPID_CONTACT="nobody"):
            self.assertEqual(vapid_settings(None)[0].id, "push.E002")


class EndpointTests(TestCase):
    def test_only_known_push_services(self):
        for url in (
            CHROME,
            SAFARI,
            "https://updates.push.services.mozilla.com/wpush/v2/gAAA",
            "https://wns2-par02p.notify.windows.com/w/?token=x",
        ):
            self.assertTrue(services.endpoint_allowed(url), url)
        for url in (
            "http://fcm.googleapis.com/fcm/send/x",
            "https://fcm.googleapis.com.evil.example/x",
            "https://evilfcm.googleapis.com.example/x",
            "https://localhost/x",
            "https://127.0.0.1/x",
            "https://fcm.googleapis.com:8443/x",
            "https://user@fcm.googleapis.com/x",
            "https://[::1]/x",
            "not a url",
        ):
            self.assertFalse(services.endpoint_allowed(url), url)

    def test_device_label(self):
        self.assertEqual(services.device_label(IPHONE_UA), "Safari sur iPhone")
        self.assertEqual(
            services.device_label(
                "Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile Safari/537.36"
            ),
            "Chrome sur Android",
        )
        self.assertEqual(services.device_label(""), "Navigateur")


class PushTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ines = make_user("ines", first_name="Inès")
        cls.yanis = make_user("yanis")

    def add(self, user=None, endpoint=CHROME):
        return services.save_subscription(
            user or self.ines, endpoint=endpoint, user_agent=IPHONE_UA, **KEYS
        )


class SendTests(PushTestCase):
    @mock.patch("push.services.webpush")
    def test_send_to_each_device(self, webpush):
        self.add()
        self.add(endpoint=SAFARI)
        self.add(self.yanis, endpoint=CHROME + "-yanis")
        result = services.send_to_user(
            self.ines, title="Visite demain", body="Entre 15 h et 17 h", url="/", tag="visit"
        )
        self.assertEqual((result.sent, result.failed, result.removed), (2, 0, 0))
        self.assertEqual(webpush.call_count, 2)
        info, payload = webpush.call_args.args
        self.assertEqual(info["keys"], KEYS)
        self.assertEqual(
            json.loads(payload),
            {"title": "Visite demain", "body": "Entre 15 h et 17 h", "url": "/", "tag": "visit"},
        )
        kwargs = webpush.call_args.kwargs
        self.assertEqual(kwargs["vapid_claims"], {"sub": "mailto:dev@example.org"})
        self.assertEqual(kwargs["headers"], {"Urgency": "normal"})
        self.assertIsNotNone(PushSubscription.objects.get(endpoint=SAFARI).last_success_at)

    @mock.patch("push.services.webpush", side_effect=push_error(410))
    def test_gone_device_is_removed(self, webpush):
        self.add()
        result = services.send_to_user(self.ines, title="t", body="b")
        self.assertEqual(result.removed, 1)
        self.assertFalse(PushSubscription.objects.exists())

    @mock.patch("push.services.webpush", side_effect=push_error(403))
    def test_failures_then_removed(self, webpush):
        self.add()
        with self.assertLogs("push.services", "WARNING") as logs:
            for _ in range(services.MAX_FAILURES - 1):
                self.assertEqual(services.send_to_user(self.ines, title="t", body="b").failed, 1)
            self.assertEqual(services.send_to_user(self.ines, title="t", body="b").removed, 1)
        # The endpoint (it lets anyone send to the device) never goes to the logs.
        self.assertNotIn("abc123", "".join(logs.output))
        self.assertFalse(PushSubscription.objects.exists())

    @mock.patch("push.services.webpush")
    def test_success_resets_failures(self, webpush):
        device = self.add()
        PushSubscription.objects.filter(pk=device.pk).update(failures=3)
        services.send_to_user(self.ines, title="t", body="b")
        device.refresh_from_db()
        self.assertEqual(device.failures, 0)

    def test_url_must_be_a_path_of_this_site(self):
        for url in ("https://evil.example/", "//evil.example/", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                services.send_to_user(self.ines, title="t", body="b", url=url)

    @mock.patch("push.services.webpush")
    def test_long_texts_are_cut(self, webpush):
        self.add()
        services.send_to_user(self.ines, title="t" * 200, body="b" * 1000)
        payload = json.loads(webpush.call_args.args[1])
        self.assertEqual(len(payload["title"]), services.TITLE_LENGTH)
        self.assertEqual(len(payload["body"]), services.BODY_LENGTH)

    def test_at_most_ten_devices(self):
        for number in range(services.MAX_DEVICES + 2):
            self.add(endpoint=f"{CHROME}{number}")
        self.assertEqual(self.ines.push_subscriptions.count(), services.MAX_DEVICES)

    def test_prune(self):
        self.add()
        self.add(self.yanis, endpoint=SAFARI)
        self.yanis.is_active = False
        self.yanis.save()
        call_command("prune_push_subscriptions", stdout=__import__("io").StringIO())
        self.assertEqual(
            list(PushSubscription.objects.values_list("user", flat=True)), [self.ines.pk]
        )


class StopTests(PushTestCase):
    def test_deleted_passkey_stops_the_devices(self):
        from access.services import cut_access

        log_in_verified(self.client, self.ines)  # creates a passkey
        self.add()
        self.add(self.yanis, endpoint=SAFARI)
        with self.captureOnCommitCallbacks(execute=True):
            cut_access(self.ines)
        self.assertEqual(
            list(PushSubscription.objects.values_list("user", flat=True)), [self.yanis.pk]
        )

    def test_departure_stops_the_devices(self):
        from datetime import date

        from django.utils import timezone

        from housing.models import Floor, Room, Stay
        from residents.departure import record_departure

        room = Room.objects.create(number="312", floor=Floor.objects.create(number=3))
        Stay.objects.create(resident=self.ines, room=room, arrival=date(2026, 9, 1))
        log_in_verified(self.client, self.ines)  # creates a passkey
        self.add()
        with self.captureOnCommitCallbacks(execute=True):
            record_departure(self.ines, timezone.localdate())
        self.assertFalse(PushSubscription.objects.exists())

    def test_logout_stops_this_device_only(self):
        log_in_verified(self.client, self.ines)
        self.add(endpoint=SAFARI)  # another device of the same person
        self.client.post(
            reverse("push:subscribe"),
            {"endpoint": CHROME, "keys": KEYS, "mode": "enable"},
            content_type="application/json",
        )
        self.client.post(reverse("access:logout"))
        self.assertEqual(
            list(PushSubscription.objects.values_list("endpoint", flat=True)), [SAFARI]
        )


class ViewTests(PushTestCase):
    def post_json(self, name, data):
        return self.client.post(reverse(name), data, content_type="application/json")

    def test_login_required(self):
        response = self.client.get(reverse("push:settings"))
        self.assertIn(reverse("access:login"), response["Location"])
        self.assertEqual(self.post_json("push:subscribe", {}).status_code, 302)

    def test_settings_page(self):
        log_in_verified(self.client, self.ines)
        self.add()
        response = self.client.get(reverse("push:settings"))
        save_page("push-settings", response)
        self.assertContains(response, f'data-public-key="{application_server_key()}"')
        self.assertContains(response, "Safari sur iPhone")
        self.assertNotContains(response, "abc123")  # never the endpoint

    def test_staff_page_keeps_the_staff_menu(self):
        nadia = make_user("nadia", Role.FRONT_DESK)
        log_in_verified(self.client, nadia)
        response = self.client.get(reverse("push:settings"))
        save_page("push-settings-staff", response)
        self.assertContains(response, '<a href="/compte/" aria-current="true">')

    def test_enable_then_sync(self):
        log_in_verified(self.client, self.ines)
        response = self.post_json(
            "push:subscribe", {"endpoint": CHROME, "keys": KEYS, "mode": "enable"}
        )
        self.assertEqual(response.json(), {"known": True})
        device = PushSubscription.objects.get()
        self.assertEqual((device.user, device.device), (self.ines, "Navigateur"))
        self.assertEqual(self.client.session["push_endpoint"], CHROME)
        new_keys = {**KEYS, "auth": "AAAAAAAAAAAAAAAAAAAAAA"}
        response = self.post_json("push:subscribe", {"endpoint": CHROME, "keys": new_keys})
        self.assertEqual(response.json(), {"known": True})
        device.refresh_from_db()
        self.assertEqual(device.auth, "AAAAAAAAAAAAAAAAAAAAAA")

    def test_sync_never_adds_a_device_and_stops_the_previous_person(self):
        # Shared phone: the browser was subscribed by Inès; her session expired and
        # Yanis logs in after her (review of T19).
        self.add()
        log_in_verified(self.client, self.yanis)
        response = self.post_json("push:subscribe", {"endpoint": CHROME, "keys": KEYS})
        self.assertEqual(response.json(), {"known": False})
        self.assertFalse(PushSubscription.objects.exists())
        # Only his own tap on "Activer" gives him the device.
        self.post_json("push:subscribe", {"endpoint": CHROME, "keys": KEYS, "mode": "enable"})
        self.assertEqual(PushSubscription.objects.get().user, self.yanis)

    def test_refused_subscriptions(self):
        log_in_verified(self.client, self.ines)
        for data in (
            {"endpoint": "https://evil.example/x", "keys": KEYS, "mode": "enable"},
            {"endpoint": CHROME, "keys": {"p256dh": "x" * 500, "auth": "a"}, "mode": "enable"},
            {"endpoint": CHROME, "mode": "enable"},
            {"endpoint": ["x"], "keys": KEYS},
            "not json",
        ):
            with self.subTest(data=data):
                self.assertEqual(self.post_json("push:subscribe", data).status_code, 400)
        response = self.client.post(
            reverse("push:subscribe"), "x" * 5000, content_type="application/json"
        )
        self.assertEqual(response.status_code, 413)
        self.assertFalse(PushSubscription.objects.exists())

    def test_csrf_required(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        log_in_verified(client, self.ines)
        response = client.post(
            reverse("push:subscribe"),
            {"endpoint": CHROME, "keys": KEYS, "mode": "enable"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_unsubscribe_and_remove_device(self):
        log_in_verified(self.client, self.ines)
        self.add()
        other = self.add(endpoint=SAFARI)
        theirs = self.add(self.yanis, endpoint=CHROME + "-yanis")
        self.post_json("push:unsubscribe", {"endpoint": CHROME})
        self.assertFalse(PushSubscription.objects.filter(endpoint=CHROME).exists())
        # Someone else's device: not found.
        response = self.client.post(reverse("push:remove_device", args=[theirs.pk]))
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse("push:remove_device", args=[other.pk]), follow=True)
        self.assertContains(response, "notifications arrêtées")
        self.assertEqual(list(PushSubscription.objects.all()), [theirs])

    @mock.patch("push.services.webpush")
    def test_send_test_once_a_minute(self, webpush):
        from django.core.cache import cache

        cache.clear()
        log_in_verified(self.client, self.ines)
        self.add()
        response = self.client.post(reverse("push:test"), follow=True)
        self.assertContains(response, "Essai envoyé à 1 appareil.")
        response = self.client.post(reverse("push:test"), follow=True)
        self.assertContains(response, "Attendez une minute")
        self.assertEqual(webpush.call_count, 1)


class ReviewTests(PushTestCase):
    """Cases found by the independent review of T19."""

    def test_endpoint_tricks(self):
        for url in (
            "https://attacker.example\\.fcm.googleapis.com/x",
            "https://fcm.googleapis.com:abc/x",
            "https://fcm.googleapis.com#@evil.example/x",
            "https://FCM.googleapis.com/x",
            "https://fcm.googleapis.com/x y",
            "https://fcm.googleapis.com/é",
        ):
            self.assertFalse(services.endpoint_allowed(url), url)
        log_in_verified(self.client, self.ines)
        response = self.client.post(
            reverse("push:subscribe"),
            {"endpoint": "https://fcm.googleapis.com:abc/x", "keys": KEYS, "mode": "enable"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_keys_refused(self):
        self.assertTrue(services.keys_valid(KEYS["p256dh"], KEYS["auth"]))
        for p256dh, auth in (("!!!!", KEYS["auth"]), ("AAAA", KEYS["auth"]), (KEYS["p256dh"], "x")):
            self.assertFalse(services.keys_valid(p256dh, auth), (p256dh, auth))

    @mock.patch("push.services.webpush")
    def test_redirects_are_refused(self, webpush):
        self.add()
        services.send_to_user(self.ines, title="t", body="b")
        self.assertEqual(webpush.call_args.kwargs["requests_session"].max_redirects, 0)

    @mock.patch("push.services.webpush")
    def test_broken_device_does_not_stop_the_others(self, webpush):
        good = self.add()
        PushSubscription.objects.create(
            user=self.ines, endpoint=SAFARI, p256dh="AAAA", auth=KEYS["auth"]
        )
        webpush.side_effect = [None]
        result = services.send_to_user(self.ines, title="t", body="b")
        self.assertEqual((result.sent, result.removed), (1, 1))
        self.assertEqual(list(PushSubscription.objects.all()), [good])

    @mock.patch("push.services.webpush", side_effect=IndexError("bad key"))
    def test_unexpected_error_is_counted(self, webpush):
        self.add()
        with self.assertLogs("push.services", "WARNING"):
            self.assertEqual(services.send_to_user(self.ines, title="t", body="b").failed, 1)
        self.assertEqual(PushSubscription.objects.get().failures, 1)

    def test_temporary_errors_keep_the_device(self):
        self.add()
        for error in (push_error(503), push_error(429), requests.Timeout()):
            with (
                self.subTest(error=error),
                mock.patch("push.services.webpush", side_effect=error),
                self.assertLogs("push.services", "WARNING"),
            ):
                for _ in range(services.MAX_FAILURES + 1):
                    services.send_to_user(self.ines, title="t", body="b")
        self.assertEqual(PushSubscription.objects.get().failures, 0)
        with mock.patch("push.services.webpush", side_effect=push_error(403)):
            with self.assertLogs("push.services", "WARNING"):
                services.send_to_user(self.ines, title="t", body="b")
        self.assertEqual(PushSubscription.objects.get().failures, 1)

    def test_moved_device_gets_a_new_date(self):
        from datetime import timedelta

        from django.utils import timezone

        device = self.add()
        PushSubscription.objects.filter(pk=device.pk).update(
            created_at=timezone.now() - timedelta(days=100)
        )
        moved = self.add(self.yanis)
        self.assertEqual(moved.pk, device.pk)
        self.assertGreater(moved.created_at, timezone.now() - timedelta(minutes=1))

    def test_pages_ask_once_per_session(self):
        log_in_verified(self.client, self.ines)
        home = reverse("home")
        self.assertContains(self.client.get(home), "data-push-sync=")
        self.assertContains(self.client.get(home), f'data-push-key="{application_server_key()}"')
        self.client.post(
            reverse("push:subscribe"),
            {"endpoint": CHROME, "keys": KEYS},
            content_type="application/json",
        )
        self.assertNotContains(self.client.get(home), "data-push-sync=")

    def test_dev_key_is_in_range(self):
        from django.conf import settings

        scalar = int.from_bytes(services._b64url_decode(settings.VAPID_PRIVATE_KEY))
        self.assertTrue(
            1 <= scalar < 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
        )
