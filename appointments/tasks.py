"""Background tasks of the appointments (card T28).

Docs: https://docs.djangoproject.com/en/6.1/topics/tasks/
Arguments are JSON values (ids, strings), never model instances.
"""

import logging

from django.core.exceptions import ImproperlyConfigured
from django.tasks import task

from accounts.models import User
from push.services import send_to_user

logger = logging.getLogger(__name__)


@task
def notify_task(user_id, title, body, url, tag):
    """A notification on the devices of the person (best effort)."""
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    try:
        send_to_user(user, title=title, body=body, url=url, tag=tag)
    except ImproperlyConfigured:
        logger.warning("Direct message notification not sent: push is not configured")
