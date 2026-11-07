"""The client's address behind Caddy (card T38)."""

from django.test import RequestFactory, SimpleTestCase, override_settings

from audit.service import client_ip


class ClientIpTests(SimpleTestCase):
    def request(self, remote, forwarded=None):
        extra = {"REMOTE_ADDR": remote}
        if forwarded is not None:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return RequestFactory().get("/", **extra)

    def test_without_proxy_the_header_is_never_read(self):
        self.assertEqual(client_ip(self.request("203.0.113.5", "1.2.3.4")), "203.0.113.5")

    @override_settings(TRUSTED_PROXIES=["127.0.0.1", "::1"])
    def test_behind_caddy(self):
        # Caddy appends the address it saw: the last one.
        self.assertEqual(client_ip(self.request("127.0.0.1", "203.0.113.5")), "203.0.113.5")
        # A client that makes up the start of the header changes nothing.
        self.assertEqual(
            client_ip(self.request("127.0.0.1", "10.0.0.1, 203.0.113.5")), "203.0.113.5"
        )
        self.assertEqual(client_ip(self.request("::1", "2001:db8::7")), "2001:db8::7")
        # A request that does not come from the proxy: its header is ignored.
        self.assertEqual(client_ip(self.request("198.51.100.9", "1.2.3.4")), "198.51.100.9")
        # No header, or a broken one: the proxy address, never a made-up one.
        self.assertEqual(client_ip(self.request("127.0.0.1")), "127.0.0.1")
        self.assertEqual(client_ip(self.request("127.0.0.1", "nonsense")), "127.0.0.1")
