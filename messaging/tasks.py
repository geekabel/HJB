"""Background tasks of the messages (card T21).

Docs: https://docs.djangoproject.com/en/6.1/topics/tasks/
Arguments are JSON values (ids, strings), never model instances.
"""

from django.tasks import task

from .sending import deliver


@task
def deliver_task(campaign_id, kind):
    deliver(campaign_id, kind)
