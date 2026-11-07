"""Rate limit on login attempts, per IP address (card T14).

A passkey cannot be guessed: there is no password to try. So we do not
block after failures (such a block would let a single person stop the
whole residence wifi from logging in). We only limit login begins, which
each open a session in the database: enough to slow a bot without
bothering residents.

- The threshold is high, because the whole residence wifi often shares
  a single address.
- An IPv6 address counts for its /64 network: a client cannot change
  address to get around the limit.
- Behind Caddy, the address is the client's, read by audit.service
  client_ip from the proxy's X-Forwarded-For (card T38).
- The counter lives in the Django cache: in production a database cache
  shared by every process (card T38).

Django docs: https://docs.djangoproject.com/en/6.1/topics/cache/#the-low-level-cache-api
Python docs: https://docs.python.org/3/library/ipaddress.html
"""

import ipaddress
import time

from django.core.cache import cache

MAX_BEGINS = 300  # login begins per address...
BEGIN_WINDOW = 10 * 60  # ...over 10 minutes


def address_group(address):
    """The IPv4 address as is, or the /64 network of an IPv6 address."""
    try:
        ip = ipaddress.ip_address(address or "")
    except ValueError:
        return "unknown"
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _cache_key(name, address):
    return f"hjb:limit:{name}:{address_group(address)}"


def _count(key, now):
    """(count, end of the window) for a key, or (0, 0) once over."""
    value = cache.get(key)
    if isinstance(value, tuple) and len(value) == 2 and value[1] > now:
        return value
    return 0, 0


def limit_reached(name, address, maximum):
    """True if ``maximum`` is already reached for this address."""
    return _count(_cache_key(name, address), time.time())[0] >= maximum


def record_attempt(name, address, window):
    """Count one attempt. The counter resets ``window`` seconds after the first one.

    The end of the window is kept next to the count: the database cache of
    production (card T38) has no incr of its own, and its default incr
    would set a new timeout at each attempt. Two processes counting at the
    same instant may count one attempt less: a limit this wide allows it.
    """
    key = _cache_key(name, address)
    now = time.time()
    count, until = _count(key, now)
    if not until:
        until = now + window
    cache.set(key, (count + 1, until), timeout=max(1, int(until - now) + 1))
