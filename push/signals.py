"""Receivers that stop the notifications of a device (card T19)."""

from django.db import transaction

from .models import PushSubscription

SESSION_KEY = "push_endpoint"  # the device of this session, forgotten at logout
CHECKED_KEY = "push_checked"  # this session already told the server which device it is


def forget_devices_after_passkey_delete(sender, instance, **kwargs):
    """A passkey was deleted (lost phone, departure, new activation): stop all devices."""
    user_id = instance.user_id
    transaction.on_commit(lambda: PushSubscription.objects.filter(user_id=user_id).delete())


def forget_device_on_logout(sender, request, user, **kwargs):
    """Logout: the device of this session stops receiving the notifications of the account."""
    if request is None or user is None:
        return
    endpoint = request.session.get(SESSION_KEY)
    if endpoint:
        PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()
