"""Lanceur de tests du projet.

Comme Django remplace l'envoi d'e-mails par une boîte en mémoire pendant les
tests (``mail.outbox``), on remplace ici le fournisseur de SMS : aucun test ne
peut envoyer un vrai SMS, quel que soit l'environnement.

Avec ``--parallel`` et le démarrage « spawn » ou « forkserver » (macOS,
Windows, Linux à partir de Python 3.14), chaque processus relit les réglages
depuis l'environnement : le crochet ``process_setup`` de ParallelTestSuite
y remet le fournisseur de test.
Doc : https://docs.djangoproject.com/en/6.1/topics/testing/advanced/#defining-a-test-runner
"""

from django.conf import settings
from django.test.runner import DiscoverRunner, ParallelTestSuite

SMS_DE_TEST = {"BACKEND": "sms.fournisseurs.memoire.FournisseurMemoire", "OPTIONS": {}}


def imposer_sms_de_test(*args):
    settings.SMS = SMS_DE_TEST


class SuiteParallele(ParallelTestSuite):
    process_setup = imposer_sms_de_test


class LanceurTests(DiscoverRunner):
    parallel_test_suite = SuiteParallele

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._sms_avant = getattr(settings, "SMS", None)
        imposer_sms_de_test()

    def teardown_test_environment(self, **kwargs):
        settings.SMS = self._sms_avant
        super().teardown_test_environment(**kwargs)
