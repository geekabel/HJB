"""Test runner of the project.

Django replaces sending e-mails with an in-memory outbox during tests
(``mail.outbox``). In the same way, we replace the SMS provider here: no test
can send a real SMS, whatever the environment.

With ``--parallel`` and the "spawn" or "forkserver" start method (macOS,
Windows, Linux from Python 3.14), each process reads the settings again
from the environment: the ``process_setup`` hook of ParallelTestSuite
puts the test provider back.
Django docs: https://docs.djangoproject.com/en/6.1/topics/testing/advanced/#defining-a-test-runner
"""

from django.conf import settings
from django.test.runner import DiscoverRunner, ParallelTestSuite

TEST_SMS = {"BACKEND": "sms.providers.memory.MemoryProvider", "OPTIONS": {}}


def force_test_sms(*args):
    settings.SMS = TEST_SMS


class HJBParallelTestSuite(ParallelTestSuite):
    process_setup = force_test_sms


class HJBTestRunner(DiscoverRunner):
    parallel_test_suite = HJBParallelTestSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._sms_before = getattr(settings, "SMS", None)
        force_test_sms()

    def teardown_test_environment(self, **kwargs):
        settings.SMS = self._sms_before
        super().teardown_test_environment(**kwargs)
