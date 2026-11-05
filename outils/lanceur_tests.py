"""Lanceur de tests du projet.

Comme Django remplace l'envoi d'e-mails par une boîte en mémoire pendant les
tests (``mail.outbox``), on remplace ici le fournisseur de SMS : aucun test ne
peut envoyer un vrai SMS, quel que soit l'environnement.
Doc : https://docs.djangoproject.com/en/6.1/topics/testing/advanced/#defining-a-test-runner
"""

from django.conf import settings
from django.test.runner import DiscoverRunner

SMS_DE_TEST = {"BACKEND": "sms.fournisseurs.memoire.FournisseurMemoire", "OPTIONS": {}}


class LanceurTests(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._sms_avant = getattr(settings, "SMS", None)
        settings.SMS = SMS_DE_TEST

    def teardown_test_environment(self, **kwargs):
        settings.SMS = self._sms_avant
        super().teardown_test_environment(**kwargs)
